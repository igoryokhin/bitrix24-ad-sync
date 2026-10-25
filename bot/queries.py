"""Тонкие обёртки над webui/services (смонтирован read-only в /app/services)
для вызова из asyncio.to_thread — сам этот модуль синхронный."""
from services.ad_client import ad_connection, list_users, list_ous


def get_active_users(base_dn=None, search=None):
    with ad_connection() as (conn, ad_common):
        return list_users(conn, ad_common, status="active", search=search, base_dn=base_dn)


def get_ous():
    with ad_connection() as (conn, ad_common):
        return list_ous(conn, ad_common)


def get_not_received(db, users):
    """users — список dict с ключом 'dn'. Возвращает тех, кого нет в
    message_log с message_sent=1 (включая сообщения, отправленные
    full_sync.py/delta_sync.py при создании учётки — см. ad_common.py)."""
    rows = db.execute("SELECT DISTINCT user_dn FROM message_log WHERE message_sent = 1").fetchall()
    received = {r["user_dn"] for r in rows}
    return [u for u in users if u["dn"] not in received]
