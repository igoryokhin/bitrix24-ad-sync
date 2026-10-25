from flask import Blueprint, request, jsonify

from db import get_db

bp = Blueprint("api_audit", __name__)


@bp.route("/api/audit")
def api_list_audit():
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = max(int(request.args.get("offset", 0)), 0)
    db = get_db()
    rows = db.execute(
        "SELECT id, actor, action, target, detail, outcome, created_at FROM audit_log "
        "ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return jsonify(entries=[dict(r) for r in rows])
