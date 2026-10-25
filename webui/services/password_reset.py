"""
Флагманские функции панели/бота: сброс пароля (+ отправка в Bitrix24) и
повторная отправка уже выданного пароля без его смены.

Текущий пароль хранится зашифрованным (ad_common.store_encrypted_password,
ключ CREDENTIAL_ENCRYPTION_KEY) — это осознанное решение: без этого
"напомнить" невозможно, т.к. иначе пароль нигде не живёт даже секунду
дольше одного запроса. Доверительный контур — тот же, что у AD_PASSWORD.

do_password_reset()/do_password_reset_batch() — новый пароль + отправка.
do_resend()/do_resend_batch() — тот же пароль, AD не трогаем; если пароль
ни разу не сохранялся для этой учётки — возвращает ошибку no_stored_password,
нужно сначала сделать обычный сброс.
*_batch — один AD-коннект на весь батч (как у full_sync.py), для
массовых рассылок из бота.
"""
import threading
from datetime import datetime, timezone

from .ad_client import ad_connection, ADUnavailable, get_user
from .settings_store import get_effective
from .audit import record as audit_record

# Защищает от гонки, если два администратора одновременно жмут "сброс
# пароля" — send_b24_credentials_message читает TEST_RECIPIENT_ID/
# INSTRUCTION_URL как модульные глобалы ad_common в момент вызова.
_send_lock = threading.Lock()


def _log_message(db, user_dn, b24_uid, login, action, ad_password_set, message_sent, performed_by, error_detail):
    db.execute(
        "INSERT INTO message_log "
        "(user_dn, b24_uid, login, action, ad_password_set, message_sent, performed_by, performed_at, error_detail) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            user_dn, b24_uid, login, action,
            int(bool(ad_password_set)), int(bool(message_sent)),
            performed_by, datetime.now(timezone.utc).isoformat(), error_detail,
        ),
    )
    db.commit()


def _apply_runtime_settings(ad_common):
    """Подтягивает актуальные TEST_RECIPIENT_ID/INSTRUCTION_URL из .env перед
    отправкой — настройки, изменённые через панель, применяются немедленно
    даже в уже запущенном долгоживущем процессе (webui/бот)."""
    ad_common.TEST_RECIPIENT_ID = get_effective("TEST_RECIPIENT_ID", ad_common.TEST_RECIPIENT_ID)
    ad_common.INSTRUCTION_URL = get_effective("INSTRUCTION_URL", ad_common.INSTRUCTION_URL)


def _reset_one(conn, ad_common, db, user_dn, actor, template="ad"):
    """Тело одного сброса. Вызывается под уже открытым conn и уже взятым
    _send_lock — см. do_password_reset()/do_password_reset_batch()."""
    user = get_user(conn, ad_common, user_dn)
    if not user:
        return {"success": False, "error": "not_found"}

    length_raw = get_effective("PASSWORD_LENGTH", ad_common.PASSWORD_LENGTH)
    try:
        length = int(length_raw)
    except (TypeError, ValueError):
        length = ad_common.PASSWORD_LENGTH
    new_password = ad_common.generate_password(length=length)

    ok = ad_common.set_user_password(conn, user_dn, new_password)
    if not ok:
        new_password = None
        _log_message(
            db, user_dn, user["b24_uid"], user["login"], "password_reset",
            ad_password_set=False, message_sent=False,
            performed_by=actor, error_detail="AD password set failed",
        )
        audit_record(db, actor=actor, action="password_reset", target=user_dn,
                      detail="ad_set_failed", outcome="failure")
        return {"success": False, "error": "ad_set_failed"}

    ad_common.store_encrypted_password(user_dn, new_password)

    sent = False
    if user["b24_uid"]:
        sent = ad_common.send_b24_credentials_message(
            user["b24_uid"], user["login"], new_password, user["email"],
            template=template, action="password_reset",
            user_dn=user_dn, ad_password_set=True,
        )
    new_password = None  # больше нигде не используется и не сохраняется

    _log_message(
        db, user_dn, user["b24_uid"], user["login"], "password_reset",
        ad_password_set=True, message_sent=sent, performed_by=actor, error_detail=None,
    )
    audit_record(db, actor=actor, action="password_reset", target=user_dn,
                  detail=f"message_sent={sent}, template={template}", outcome="success")
    return {"success": True, "message_sent": sent}


def _resend_one(conn, ad_common, db, user_dn, actor, template="ad"):
    """Отправляет ТЕКУЩИЙ (ранее сохранённый) пароль повторно — без смены
    пароля в AD. Если пароль ни разу не сохранялся (учётка создана до этой
    функции, или ещё не было ни одного сброса) — возвращает ошибку,
    нужно использовать обычный сброс."""
    user = get_user(conn, ad_common, user_dn)
    if not user:
        return {"success": False, "error": "not_found"}

    password = ad_common.get_stored_password(user_dn)
    if not password:
        return {"success": False, "error": "no_stored_password"}

    sent = False
    if user["b24_uid"]:
        sent = ad_common.send_b24_credentials_message(
            user["b24_uid"], user["login"], password, user["email"],
            template=template, action="credentials_resend",
            user_dn=user_dn, ad_password_set=True,
        )
    password = None

    _log_message(
        db, user_dn, user["b24_uid"], user["login"], "credentials_resend",
        ad_password_set=True, message_sent=sent, performed_by=actor, error_detail=None,
    )
    audit_record(db, actor=actor, action="credentials_resend", target=user_dn,
                  detail=f"message_sent={sent}, template={template}", outcome="success")
    return {"success": True, "message_sent": sent}


def do_password_reset(db, user_dn, actor, template="ad"):
    try:
        with ad_connection() as (conn, ad_common):
            with _send_lock:
                _apply_runtime_settings(ad_common)
                return _reset_one(conn, ad_common, db, user_dn, actor, template)
    except ADUnavailable as e:
        return {"success": False, "error": "ad_unavailable", "detail": str(e)}


def do_password_reset_batch(db, user_dns, actor, template="ad"):
    """Один AD-коннект на весь батч — для массовых рассылок из бота."""
    try:
        with ad_connection() as (conn, ad_common):
            with _send_lock:
                _apply_runtime_settings(ad_common)
                return [
                    {"user_dn": dn, **_reset_one(conn, ad_common, db, dn, actor, template)}
                    for dn in user_dns
                ]
    except ADUnavailable as e:
        return [{"user_dn": dn, "success": False, "error": "ad_unavailable", "detail": str(e)} for dn in user_dns]


def do_resend(db, user_dn, actor, template="ad"):
    """Напомнить текущий пароль, не меняя его в AD."""
    try:
        with ad_connection() as (conn, ad_common):
            with _send_lock:
                _apply_runtime_settings(ad_common)
                return _resend_one(conn, ad_common, db, user_dn, actor, template)
    except ADUnavailable as e:
        return {"success": False, "error": "ad_unavailable", "detail": str(e)}


def do_resend_batch(db, user_dns, actor, template="ad"):
    """Напомнить текущий пароль N пользователям — один AD-коннект на весь
    батч (для чтения login/email/b24_uid, саму AD-запись не трогаем)."""
    try:
        with ad_connection() as (conn, ad_common):
            with _send_lock:
                _apply_runtime_settings(ad_common)
                return [
                    {"user_dn": dn, **_resend_one(conn, ad_common, db, dn, actor, template)}
                    for dn in user_dns
                ]
    except ADUnavailable as e:
        return [{"user_dn": dn, "success": False, "error": "ad_unavailable", "detail": str(e)} for dn in user_dns]
