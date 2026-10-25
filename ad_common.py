#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ad_common.py
"""
Общие функции для full_sync и delta_sync.
"""

import os
import re
import ssl
import sys
import string
import secrets
import sqlite3
import functools
from datetime import datetime

import requests
from cryptography.fernet import Fernet, InvalidToken
from ldap3 import Server, Connection, ALL, SUBTREE, MODIFY_ADD, MODIFY_REPLACE, MODIFY_DELETE, Tls
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import escape_rdn
from ldap3.core.exceptions import (
    LDAPNoSuchObjectResult, LDAPEntryAlreadyExistsResult,
    LDAPInvalidAttributeSyntaxResult, LDAPOtherResult,
    LDAPUnwillingToPerformResult, LDAPConstraintViolationResult,
)

# Принудительный flush stdout — важно в Docker
print = functools.partial(print, flush=True)

# ================= КОНФИГУРАЦИЯ (из env) =================
BITRIX_WEBHOOK         = os.getenv("BITRIX_WEBHOOK", "")
BITRIX_NOTIFY_WEBHOOK  = os.getenv("BITRIX_NOTIFY_WEBHOOK", "") or BITRIX_WEBHOOK
# Тестовый режим: если задан — сообщения уходят только этому UID Битрикс24
TEST_RECIPIENT_ID      = os.getenv("TEST_RECIPIENT_ID", "").strip()

AD_SERVER        = os.getenv("AD_SERVER", "localhost")
AD_USER          = os.getenv("AD_USER", "")
AD_PASSWORD      = os.getenv("AD_PASSWORD", "")
AD_UPN_SUFFIX    = os.getenv("AD_UPN_SUFFIX", "example.org")
AD_BASE_DN       = os.getenv("AD_BASE_DN", "DC=example,DC=org")

ROOT_OU_NAME = "Bitrix24_Structure"
ROOT_OU_DN = f"OU={ROOT_OU_NAME},{AD_BASE_DN}"

GROUPS_OU_NAME = "Bitrix24_Groups"
GROUPS_OU_DN = f"OU={GROUPS_OU_NAME},{ROOT_OU_DN}"

DEPT_GROUPS_OU_NAME = "Bitrix24_DeptGroups"
DEPT_GROUPS_OU_DN = f"OU={DEPT_GROUPS_OU_NAME},{ROOT_OU_DN}"

DISABLED_OU_NAME = "Disabled"
DISABLED_OU_DN = f"OU={DISABLED_OU_NAME},{ROOT_OU_DN}"

PROTECTED_OU_NAME = "Protected"
PROTECTED_OU_DN = f"OU={PROTECTED_OU_NAME},{ROOT_OU_DN}"

# Длина генерируемого пароля (можно переопределить через .env)
PASSWORD_LENGTH = int(os.getenv("PASSWORD_LENGTH", "14"))
# Оставлено для обратной совместимости / ручного сброса
DEFAULT_PASSWORD = os.getenv("DEFAULT_PASSWORD", "")

COMPANY_NAME = os.getenv("COMPANY_NAME", "Example Company")

ADMIN_GROUP_NAME = os.getenv("ADMIN_GROUP_NAME", "").strip()
ADMIN_DEPT_KEYWORDS = [
    "департамент ит", "отдел разработки",
    "отдел технической поддержки", "спбдепартамент ит",
]

DISABLED_RETENTION_DAYS = int(os.getenv("DISABLED_RETENTION_DAYS", "180"))
DEPT_GROUP_PREFIX = "DEPT_"

# Ссылка на инструкцию, добавляется в конец приветственного сообщения
INSTRUCTION_URL = os.getenv(
    "INSTRUCTION_URL",
    "https://bitrix24public.com/anlasvegas.bitrix24.ru/doc/bUhH4JzUOR1KmllQOQKK"
)
# Ссылка на инструкцию для шаблона "почта" (если не задана — просто не добавляется в сообщение)
MAIL_INSTRUCTION_URL = os.getenv("MAIL_INSTRUCTION_URL", "")

# Путь к общей SQLite БД веб-панели. Если задан — send_b24_credentials_message
# best-effort пишет туда строку в message_log (нужно веб-панели/боту, чтобы
# корректно считать "кто ещё не получал сообщение вообще"). Если не задан —
# полный no-op, full_sync.py/delta_sync.py работают как раньше.
MESSAGE_LOG_DB_PATH = os.getenv("MESSAGE_LOG_DB_PATH", "").strip()

# Ключ шифрования для хранения ТЕКУЩЕГО пароля пользователя (чтобы можно
# было "напомнить" пароль повторно, не генерируя новый при каждой рассылке).
# Тот же доверительный контур, что и AD_PASSWORD — тот, у кого есть .env и
# доступ к общей SQLite, и так уже может делать что угодно через AD-бинд.
CREDENTIAL_ENCRYPTION_KEY = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip()

# ================= ТРАНСЛИТЕРАЦИЯ =================
TRANSLIT_MAP = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z',
    'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
    'с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh',
    'щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
    'А':'A','Б':'B','В':'V','Г':'G','Д':'D','Е':'E','Ё':'E','Ж':'Zh','З':'Z',
    'И':'I','Й':'Y','К':'K','Л':'L','М':'M','Н':'N','О':'O','П':'P','Р':'R',
    'С':'S','Т':'T','У':'U','Ф':'F','Х':'H','Ц':'Ts','Ч':'Ch','Ш':'Sh',
    'Щ':'Sch','Ъ':'','Ы':'Y','Ь':'','Э':'E','Ю':'Yu','Я':'Ya',
}

def transliterate(text):
    result = []
    for c in text:
        if c in TRANSLIT_MAP:
            result.append(TRANSLIT_MAP[c])
        elif c.isascii() and (c.isalnum() or c in "._-"):
            result.append(c)
    return "".join(result).lower()

# ================= ГЕНЕРАЦИЯ ПАРОЛЯ =================
# Символы, безопасные для AD, JSON, shell и логов.
# Исключены кавычки, backslash, доллар, бэктик — они ломают парсинг.
_PWD_UPPER   = string.ascii_uppercase
_PWD_LOWER   = string.ascii_lowercase
_PWD_DIGITS  = string.digits
_PWD_SPECIAL = "!@#%^&*()-_=+"
_PWD_ALPHABET = _PWD_UPPER + _PWD_LOWER + _PWD_DIGITS + _PWD_SPECIAL

def generate_password(length: int = None) -> str:
    """
    Генерирует криптостойкий случайный пароль, удовлетворяющий
    дефолтной политике сложности AD (≥7 символов, ≥3 из 4 категорий).
    Гарантирует наличие заглавной, строчной, цифры и спецсимвола.
    """
    if length is None:
        length = PASSWORD_LENGTH
    if length < 8:
        length = 8
    rng = secrets.SystemRandom()

    required = [
        secrets.choice(_PWD_UPPER),
        secrets.choice(_PWD_LOWER),
        secrets.choice(_PWD_DIGITS),
        secrets.choice(_PWD_SPECIAL),
    ]
    rest = [secrets.choice(_PWD_ALPHABET) for _ in range(length - len(required))]

    pwd_list = required + rest
    rng.shuffle(pwd_list)
    return "".join(pwd_list)

# ================= BITRIX =================
def call_bitrix(method, params=None):
    if not BITRIX_WEBHOOK:
        raise Exception("BITRIX_WEBHOOK не задан в .env")
    try:
        r = requests.post(BITRIX_WEBHOOK + method, json=params or {}, timeout=30)
        r.raise_for_status()
        data = r.json()
        if 'error' in data:
            raise Exception(f"Bitrix API Error: {data.get('error_description', data['error'])}")
        return data.get('result', [])
    except requests.exceptions.RequestException as e:
        raise Exception(f"Ошибка соединения с Битрикс24: {e}")

def bitrix_paginate(method, params):
    """Пагинация: собирает все страницы."""
    all_items = []
    start = 0
    while True:
        p = dict(params)
        p['start'] = start
        page = call_bitrix(method, p)
        if not page:
            break
        all_items.extend(page)
        if len(page) < 50:
            break
        start += 50
    return all_items

def get_all_departments():
    return bitrix_paginate("department.get", {"sort": "ID", "order": "ASC"})

def get_all_groups():
    return bitrix_paginate("sonet_group.get", {"IS_ADMIN": "Y"})

def get_active_users():
    # sort/order обязательны для стабильной пагинации — без них Bitrix
    # может возвращать страницы в разном порядке, часть пользователей проваливается.
    return bitrix_paginate("user.get", {
        "FILTER": {"ACTIVE": True},
        "sort": "ID",
        "order": "ASC",
        "select": ["ID","NAME","LAST_NAME","EMAIL","UF_DEPARTMENT",
                   "WORK_POSITION","UF_HEAD"],
    })

def get_inactive_users():
    return bitrix_paginate("user.get", {
        "FILTER": {"ACTIVE": False},
        "sort": "ID",
        "order": "ASC",
        "select": ["ID","NAME","LAST_NAME","EMAIL","UF_DEPARTMENT",
                   "WORK_POSITION","UF_HEAD"],
    })

def check_bitrix_user_status(uid):
    """
    Точечная проверка статуса пользователя в Битрикс24 по ID.
    Используется как ЗАЩИТА ОТ ЛОЖНЫХ ОТКЛЮЧЕНИЙ: если bulk-выборка
    по какой-то причине не увидела пользователя, мы делаем отдельный
    API-запрос и не отключаем активных.

    Возвращает:
      'active'     — пользователь есть и ACTIVE=Y
      'inactive'   — пользователь есть и ACTIVE=N
      'not_found'  — пользователь отсутствует в Битриксе
      'error'      — ошибка API (решение принимать нельзя → fail-safe)
    """
    try:
        result = call_bitrix("user.get", {"FILTER": {"ID": str(uid)}})
    except Exception as e:
        print(f"  [WARN] check_bitrix_user_status(UID={uid}): {e}")
        return 'error'

    if not result:
        return 'not_found'

    u = result[0]
    active = u.get('ACTIVE')
    # Bitrix может отдать True/False или "Y"/"N" в зависимости от версии
    if active in (True, "Y", "y", 1, "1", "true", "TRUE"):
        return 'active'
    return 'inactive'

# ================= ОТПРАВКА СООБЩЕНИЙ В БИТРИКС24 =================
def _is_test_allowed(user_id):
    """Проверка тестового режима. Если TEST_RECIPIENT_ID задан —
    отправляем только ему. Сравниваем как строки (Bitrix отдаёт ID строкой)."""
    if not TEST_RECIPIENT_ID:
        return True
    return str(user_id) == str(TEST_RECIPIENT_ID)

def _log_credentials_send(user_dn, b24_uid, login, action, ad_password_set, message_sent, error_detail=None):
    """Best-effort, не критичная запись в общий message_log веб-панели.
    No-op, если MESSAGE_LOG_DB_PATH не задан (т.е. для обычного запуска
    full_sync.py/delta_sync.py без веб-панели — поведение не меняется)."""
    if not MESSAGE_LOG_DB_PATH:
        return
    try:
        conn = sqlite3.connect(MESSAGE_LOG_DB_PATH, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "INSERT INTO message_log (user_dn, b24_uid, login, action, ad_password_set, "
            "message_sent, performed_by, performed_at, error_detail) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                user_dn, str(b24_uid) if b24_uid else None, login, action,
                int(bool(ad_password_set)), int(bool(message_sent)), "ad-sync",
                datetime.now().isoformat(), error_detail,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[B24] WARN: message_log запись не удалась (не критично): {e}")


def _fernet():
    if not CREDENTIAL_ENCRYPTION_KEY:
        return None
    try:
        return Fernet(CREDENTIAL_ENCRYPTION_KEY.encode())
    except Exception as e:
        print(f"[CRED] WARN: некорректный CREDENTIAL_ENCRYPTION_KEY: {e}")
        return None


def store_encrypted_password(user_dn, password):
    """Сохраняет ТЕКУЩИЙ пароль пользователя зашифрованным — чтобы потом
    можно было "напомнить" его без повторной генерации. Best-effort,
    no-op если CREDENTIAL_ENCRYPTION_KEY или MESSAGE_LOG_DB_PATH не заданы."""
    f = _fernet()
    if not f or not MESSAGE_LOG_DB_PATH:
        return
    try:
        token = f.encrypt(password.encode()).decode()
        conn = sqlite3.connect(MESSAGE_LOG_DB_PATH, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "INSERT INTO credential_store (user_dn, encrypted_password, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(user_dn) DO UPDATE SET encrypted_password=excluded.encrypted_password, "
            "updated_at=excluded.updated_at",
            (user_dn, token, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[CRED] WARN: не удалось сохранить пароль (не критично): {e}")


def get_stored_password(user_dn):
    """Возвращает расшифрованный текущий пароль пользователя, если он был
    сохранён ранее через store_encrypted_password(), иначе None."""
    f = _fernet()
    if not f or not MESSAGE_LOG_DB_PATH:
        return None
    try:
        conn = sqlite3.connect(MESSAGE_LOG_DB_PATH, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        row = conn.execute(
            "SELECT encrypted_password FROM credential_store WHERE user_dn = ?", (user_dn,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return f.decrypt(row[0].encode()).decode()
    except InvalidToken:
        print(f"[CRED] WARN: не удалось расшифровать пароль для {user_dn} (сменился ключ?)")
        return None
    except Exception as e:
        print(f"[CRED] WARN: не удалось прочитать пароль (не критично): {e}")
        return None


def send_b24_credentials_message(
    user_id, login, password, email, *,
    template="ad",
    action="credentials_initial",
    user_dn=None,
    ad_password_set=True,
):
    """
    Отправляет личное сообщение с учётными данными пользователю в Битрикс24.
    Отправитель — владелец вебхука BITRIX_NOTIFY_WEBHOOK.
    Возвращает True при успехе.

    template: "ad" (логин/пароль домена, по умолчанию) или "mail"
    (тот же логин/пароль — инструкция под почтовый клиент, т.к. почта
    совпадает с AD-учёткой: login@AD_UPN_SUFFIX).
    user_dn/action/ad_password_set — только для best-effort записи в
    message_log (см. _log_credentials_send), на саму отправку не влияют.
    """
    if not BITRIX_NOTIFY_WEBHOOK:
        print("[B24] BITRIX_NOTIFY_WEBHOOK не задан — сообщение не отправлено.")
        _log_credentials_send(user_dn, user_id, login, action, ad_password_set, False, "no webhook")
        return False

    if not _is_test_allowed(user_id):
        print(f"[B24] Тестовый режим: пропуск отправки для UID={user_id} "
              f"(разрешён только {TEST_RECIPIENT_ID})")
        _log_credentials_send(user_dn, user_id, login, action, ad_password_set, False, "test mode skip")
        return False

    method = "im.message.add"
    url = BITRIX_NOTIFY_WEBHOOK.rstrip("/") + "/" + method

    if template == "mail":
        mail_login = f"{login}@{AD_UPN_SUFFIX}"
        message_text = (
            f"Здравствуйте!\n\n"
            f"Для вас обновлён пароль почтового аккаунта.\n\n"
            f"📧 Адрес почты: {mail_login}\n"
            f"🔒 Пароль: {password}\n\n"
            f"📧 Веб-почта доступна по адресу: https://mail.arendok.ru/\n\n"
            f"Для использования на вашем компьютере или телефоне:\n"
            f"• Outlook / Apple Mail / Thunderbird\n"
            f"📖 Инструкция для Thunderbird: https://bitrix24public.com/anlasvegas.bitrix24.ru/doc/AIElaBkIsVuSkE2kjQdQ\n\n"
            f"Логин и пароль совпадают с учётной записью домена."
            + (f"\n\n📖 Дополнительная инструкция: {MAIL_INSTRUCTION_URL}" if MAIL_INSTRUCTION_URL else "")
        )
    else:
        message_text = (
            f"Здравствуйте!\n\n"
            f"Для вас создана учётная запись в корпоративной системе.\n\n"
            f"🔑 Логин: {login}\n"
            f"🔒 Пароль: {password}\n"
            f"📧 Почта: {email}\n\n"
            f"Пожалуйста, смените пароль при первом входе.\n\n"
            f"📖 Инструкция: {INSTRUCTION_URL}"
        )

    payload = {
        "DIALOG_ID": str(user_id),
        "MESSAGE": message_text,
    }

    try:
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            print(f"[B24] Ошибка отправки UID={user_id}: "
                  f"{data.get('error_description', data['error'])}")
            _log_credentials_send(user_dn, user_id, login, action, ad_password_set, False,
                                   str(data.get("error_description", data["error"])))
            return False
        print(f"[B24] ✓ Сообщение отправлено UID={user_id} (логин {login}).")
        _log_credentials_send(user_dn, user_id, login, action, ad_password_set, True)
        return True
    except requests.exceptions.RequestException as e:
        print(f"[B24] Ошибка соединения при отправке UID={user_id}: {e}")
        _log_credentials_send(user_dn, user_id, login, action, ad_password_set, False, str(e))
        return False
    except Exception as e:
        print(f"[B24] Непредвиденная ошибка при отправке UID={user_id}: {e}")
        _log_credentials_send(user_dn, user_id, login, action, ad_password_set, False, str(e))
        return False

# ================= AD =================
class ADConnectionError(RuntimeError):
    """Поднимается connect_ad(exit_on_failure=False) вместо sys.exit(1) —
    нужно для долгоживущих процессов (веб-панель), которым нельзя падать
    целиком из-за временной недоступности AD."""

def connect_ad(exit_on_failure: bool = True):
    if not AD_PASSWORD:
        msg = "[AD] AD_PASSWORD не задан. Проверьте .env / env_file в docker-compose.yml"
        print(msg)
        if exit_on_failure:
            sys.exit(1)
        raise ADConnectionError(msg)
    tls = Tls(validate=ssl.CERT_NONE, version=ssl.PROTOCOL_TLSv1_2,
              ciphers="DEFAULT@SECLEVEL=1")
    server = Server(AD_SERVER, get_info=ALL, use_ssl=True, tls=tls)
    try:
        conn = Connection(server, user=AD_USER, password=AD_PASSWORD,
                          auto_bind=True, raise_exceptions=True)
        print(f"[AD] Соединение установлено ({AD_SERVER})")
        return conn
    except Exception as e:
        msg = f"[AD] Ошибка подключения: {type(e).__name__}: {e}"
        print(msg)
        if exit_on_failure:
            sys.exit(1)
        raise ADConnectionError(msg) from e

def dn_exists(conn, dn):
    try:
        conn.search(dn, "(objectClass=*)", search_scope='BASE',
                    attributes=['distinguishedName'])
        return len(conn.entries) > 0
    except LDAPNoSuchObjectResult:
        return False

def make_unique_dn(conn, base_cn, parent_dn):
    cand = f"CN={escape_rdn(base_cn)},{parent_dn}"
    if not dn_exists(conn, cand):
        return cand, base_cn
    n = 2
    while True:
        alt = f"{base_cn} {n}"
        cand = f"CN={escape_rdn(alt)},{parent_dn}"
        if not dn_exists(conn, cand):
            return cand, alt
        n += 1

def ou_exists(conn, ou_dn):
    try:
        conn.search(ou_dn, "(objectClass=organizationalUnit)",
                    search_scope='BASE', attributes=['distinguishedName'])
        return len(conn.entries) > 0
    except LDAPNoSuchObjectResult:
        return False

def ensure_ou(conn, ou_name, parent_dn, quiet=False):
    ou_dn = f"OU={escape_rdn(ou_name)},{parent_dn}"
    if ou_exists(conn, ou_dn):
        return ou_dn
    try:
        conn.add(ou_dn, ['organizationalUnit'], {'ou': ou_name})
        if not quiet and conn.result['description'] == 'success':
            print(f"  [NEW] OU: {ou_name}")
    except LDAPEntryAlreadyExistsResult:
        pass
    except Exception as e:
        print(f"  [ERROR] OU {ou_name}: {e}")
    return ou_dn

def group_exists(conn, group_dn):
    try:
        conn.search(group_dn, "(objectClass=group)",
                    search_scope='BASE', attributes=['distinguishedName'])
        return len(conn.entries) > 0
    except LDAPNoSuchObjectResult:
        return False

def find_group_by_marker(conn, search_base, marker):
    conn.search(search_base, f"(&(objectClass=group)(description={marker}))",
                search_scope=SUBTREE, attributes=['distinguishedName'])
    if conn.entries:
        return str(conn.entries[0].entry_dn)
    return None

# ================= РАЗБОР description =================
def parse_uid(description):
    """
    Извлекает B24_UID из description.
    ВАЖНО: возвращает строку, как отдаёт Bitrix API (u['ID'] — str),
    чтобы сравнения `uid in ad_by_uid` работали корректно.
    """
    if not description:
        return None
    m = re.search(r'B24_UID=(\d+)', str(description))
    return m.group(1) if m else None

def parse_disabled_at(description):
    if not description:
        return None
    m = re.search(r'DISABLED_AT=([0-9T:\-]+)', str(description))
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None

def build_description(uid, disabled_at=None):
    parts = [f"B24_UID={uid}"]
    if disabled_at:
        parts.append(f"DISABLED_AT={disabled_at.strftime('%Y-%m-%dT%H:%M:%S')}")
    return " | ".join(parts)

# ================= АТРИБУТЫ =================
def valid_email(e):
    """Проверка валидности email. Без подчёркивания в имени —
    чтобы функция экспортировалась через `from ad_common import *`."""
    if not e or "@" not in e:
        return False
    l, _, d = e.partition("@")
    return bool(l) and "." in d and " " not in e

def generate_login(first, last, used_logins):
    f = transliterate(first) or "u"
    l = transliterate(last) or "user"
    fi = f[0]
    for length in range(3, len(l) + 1):
        cand = (fi + l[:length])[:20]
        if cand not in used_logins:
            used_logins.add(cand)
            return cand
    base = (fi + l)[:19]
    n = 1
    while True:
        cand = f"{base}{n}"[:20]
        if cand not in used_logins:
            used_logins.add(cand)
            return cand
        n += 1

# ================= ИЕРАРХИЯ ДЕПАРТАМЕНТОВ =================
def build_dept_ancestors(dept_info):
    """
    Возвращает dict: dept_id -> [dept_id, parent_id, grandparent_id, ...]
    (включая сам отдел, первый — самый глубокий).
    """
    def chain(dept_id):
        result = []
        cur = dept_id
        seen = set()
        while cur and cur not in seen and cur in dept_info:
            seen.add(cur)
            result.append(cur)
            cur = dept_info[cur]['parent']
        return result
    return {did: chain(did) for did in dept_info}

# ================= ПЕРЕМЕЩЕНИЕ =================
def move_user(conn, user_dn, new_parent_dn):
    """Перемещает пользователя в новый OU, сохраняя CN."""
    try:
        conn.search(user_dn, "(objectClass=user)", search_scope='BASE',
                    attributes=['cn'])
        if not conn.entries:
            return False
        cn = str(conn.entries[0].cn)
        new_dn = f"CN={escape_rdn(cn)},{new_parent_dn}"
        if new_dn == user_dn:
            return True
        conn.modify_dn(user_dn, f"CN={cn}", new_superior=new_parent_dn)
        return conn.result['description'] == 'success'
    except Exception as e:
        print(f"  [ERROR] перемещение {user_dn}: {e}")
        return False

def disable_user(conn, user_dn):
    """Отключает учётку. Возвращает True/False с логированием ошибки."""
    try:
        conn.modify(user_dn, {'userAccountControl': [(MODIFY_REPLACE, [514])]})
        if conn.result['description'] != 'success':
            print(f"  [ERROR] disable {user_dn}: {conn.result}")
            return False
        return True
    except Exception as e:
        print(f"  [ERROR] disable exception {user_dn}: {e}")
        return False

def enable_user(conn, user_dn):
    """Включает учётку. Возвращает True/False с логированием ошибки."""
    try:
        conn.modify(user_dn, {'userAccountControl': [(MODIFY_REPLACE, [512])]})
        if conn.result['description'] != 'success':
            print(f"  [ERROR] enable {user_dn}: {conn.result}")
            return False
        return True
    except Exception as e:
        print(f"  [ERROR] enable exception {user_dn}: {e}")
        return False

def set_user_password(conn, user_dn, new_password):
    """
    Сбрасывает пароль существующего пользователя AD (ручной сброс из веб-панели).
    Использует то же расширение ldap3, что и при создании пользователя в
    full_sync.py (conn.extend.microsoft.modify_password) — оно само кодирует
    unicodePwd в UTF-16LE и требует LDAPS-соединения (обеспечивается connect_ad()).
    Пароль нигде не логируется. Возвращает True/False.
    """
    try:
        conn.extend.microsoft.modify_password(user_dn, new_password)
        return True
    except LDAPUnwillingToPerformResult as e:
        print(f"  [ERROR] set_user_password {user_dn}: сервер отклонил (политика паролей?): {e}")
        return False
    except LDAPConstraintViolationResult as e:
        print(f"  [ERROR] set_user_password {user_dn}: нарушение политики паролей: {e}")
        return False
    except Exception as e:
        print(f"  [ERROR] set_user_password exception {user_dn}: {e}")
        return False

def set_disabled_at(conn, user_dn, uid, when=None):
    """Устанавливает description с DISABLED_AT. Логирует ошибки."""
    try:
        desc = build_description(uid, when or datetime.now())
        conn.modify(user_dn, {'description': [(MODIFY_REPLACE, [desc])]})
        if conn.result['description'] != 'success':
            print(f"  [WARN] set_disabled_at {user_dn}: {conn.result}")
            return False
        return True
    except Exception as e:
        print(f"  [WARN] set_disabled_at exception {user_dn}: {e}")
        return False

def clear_disabled_at(conn, user_dn, uid):
    """Убирает DISABLED_AT из description. Логирует ошибки."""
    try:
        desc = build_description(uid)
        conn.modify(user_dn, {'description': [(MODIFY_REPLACE, [desc])]})
        if conn.result['description'] != 'success':
            print(f"  [WARN] clear_disabled_at {user_dn}: {conn.result}")
            return False
        return True
    except Exception as e:
        print(f"  [WARN] clear_disabled_at exception {user_dn}: {e}")
        return False