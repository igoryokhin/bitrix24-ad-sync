"""
Тонкая обёртка над ad_common.py (единственный источник правды для логики
AD — модуль монтируется в контейнер read-only, а не копируется). Здесь же —
несколько read/write-хелперов для веб-панели, которых нет в ad_common.py,
потому что full_sync.py/delta_sync.py их не используют.
"""
import os
import sys
from contextlib import contextmanager

from ldap3 import SUBTREE, MODIFY_REPLACE
from ldap3.utils.conv import escape_filter_chars

USER_ATTRS = [
    "cn", "sAMAccountName", "userPrincipalName", "mail", "department",
    "title", "description", "userAccountControl", "distinguishedName",
    "displayName", "memberOf",
]

ALLOWED_EDIT_ATTRS = {
    "department": "department",
    "title": "title",
    "email": "mail",
    "display_name": "displayName",
}


class ADUnavailable(Exception):
    """AD недоступен (нет пароля/не удалось подключиться) — не падение процесса."""


def _ad_common():
    # Читается напрямую из env (не через Flask current_app), чтобы этот
    # модуль был импортируем и из не-Flask процессов (Telegram-бот).
    scripts_dir = os.getenv("AD_SCRIPTS_DIR", "/ad-scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import ad_common
    return ad_common


@contextmanager
def ad_connection():
    ad_common = _ad_common()
    try:
        conn = ad_common.connect_ad(exit_on_failure=False)
    except ad_common.ADConnectionError as e:
        raise ADUnavailable(str(e)) from e
    try:
        yield conn, ad_common
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


def _uac_disabled(entry):
    try:
        uac = int(str(entry.userAccountControl)) if entry.userAccountControl else 0
    except (TypeError, ValueError):
        uac = 0
    return bool(uac & 2)


def _to_dict(entry, ad_common):
    description = str(entry.description) if entry.description else ""
    return {
        "dn": str(entry.entry_dn),
        "login": str(entry.sAMAccountName) if entry.sAMAccountName else "",
        "display_name": str(entry.displayName) if entry.displayName else str(entry.cn),
        "email": str(entry.mail) if entry.mail else "",
        "department": str(entry.department) if entry.department else "",
        "title": str(entry.title) if entry.title else "",
        "b24_uid": ad_common.parse_uid(description),
        "disabled": _uac_disabled(entry),
    }


def list_users(conn, ad_common, department=None, status=None, search=None, base_dn=None):
    """base_dn — поиск в конкретном поддереве OU (например, рассылка "по
    отделу" в боте), по умолчанию — весь ROOT_OU_DN."""
    filters = ["(objectClass=user)", "(objectCategory=person)"]
    if search:
        # Каждое слово ищется независимо (AND), порядок слов (Имя Фамилия
        # или Фамилия Имя) не важен — иначе подстрока "Фамилия Имя" не
        # совпадает с cn вида "Имя Фамилия", который создаёт full_sync.py.
        for token in search.split():
            esc = escape_filter_chars(token)
            filters.append(f"(|(cn=*{esc}*)(sAMAccountName=*{esc}*)(mail=*{esc}*))")
    if department:
        filters.append(f"(department={escape_filter_chars(department)})")
    filter_str = "(&" + "".join(filters) + ")"

    conn.search(
        base_dn or ad_common.ROOT_OU_DN, filter_str, search_scope=SUBTREE,
        attributes=USER_ATTRS, size_limit=1000,
    )

    results = []
    for entry in conn.entries:
        user = _to_dict(entry, ad_common)
        if status == "active" and user["disabled"]:
            continue
        if status == "disabled" and not user["disabled"]:
            continue
        results.append(user)
    return sorted(results, key=lambda u: u["display_name"])


def get_user(conn, ad_common, dn):
    conn.search(dn, "(objectClass=user)", search_scope="BASE", attributes=USER_ATTRS)
    if not conn.entries:
        return None
    entry = conn.entries[0]
    user = _to_dict(entry, ad_common)
    member_of = [str(m) for m in entry.memberOf] if entry.memberOf else []
    user["is_admin"] = any(ad_common.ADMIN_GROUP_NAME in m for m in member_of)
    return user


def list_ous(conn, ad_common):
    conn.search(
        ad_common.ROOT_OU_DN, "(objectClass=organizationalUnit)",
        search_scope=SUBTREE, attributes=["distinguishedName", "ou"],
    )
    excluded = (
        ad_common.GROUPS_OU_DN, ad_common.DEPT_GROUPS_OU_DN,
        ad_common.DISABLED_OU_DN, ad_common.PROTECTED_OU_DN,
    )
    result = []
    for entry in conn.entries:
        dn = str(entry.entry_dn)
        if any(dn == p or dn.endswith("," + p) for p in excluded):
            continue
        name = str(entry.ou) if entry.ou else dn
        result.append({"dn": dn, "name": name})
    return sorted(result, key=lambda o: o["name"])


def update_user_attrs(conn, dn, changes: dict):
    """changes: словарь с ключами из ALLOWED_EDIT_ATTRS.values() (уже смаппленными)."""
    mods = {}
    for attr, value in changes.items():
        if attr not in ALLOWED_EDIT_ATTRS.values():
            raise ValueError(f"{attr} не редактируется через панель")
        mods[attr] = [(MODIFY_REPLACE, [value] if value else [])]
    if not mods:
        return True
    conn.modify(dn, mods)
    return conn.result["description"] == "success"
