from flask import Blueprint, jsonify

from services.ad_client import ad_connection, ADUnavailable, list_users
from db import get_db

bp = Blueprint("api_dashboard", __name__)


@bp.route("/api/dashboard")
def api_dashboard():
    result = {
        "ad_users_total": None, "ad_users_disabled": None,
        "bitrix_active": None, "bitrix_inactive": None,
        "ad_error": None, "bitrix_error": None,
    }

    try:
        with ad_connection() as (conn, ad_common):
            users = list_users(conn, ad_common)
            result["ad_users_total"] = len(users)
            result["ad_users_disabled"] = sum(1 for u in users if u["disabled"])

            try:
                active = ad_common.get_active_users()
                inactive = ad_common.get_inactive_users()
                result["bitrix_active"] = len(active)
                result["bitrix_inactive"] = len(inactive)
            except Exception as e:
                result["bitrix_error"] = str(e)
    except ADUnavailable as e:
        result["ad_error"] = str(e)

    db = get_db()
    rows = db.execute(
        "SELECT run_type, status, started_at, finished_at FROM sync_runs "
        "WHERE id IN (SELECT MAX(id) FROM sync_runs GROUP BY run_type)"
    ).fetchall()
    result["last_runs"] = [dict(r) for r in rows]
    return jsonify(result)
