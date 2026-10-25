import json

from flask import Blueprint, request, jsonify, session

from services import settings_store
from services.audit import record
from db import get_db

bp = Blueprint("api_settings", __name__)


@bp.route("/api/settings")
def api_get_settings():
    return jsonify(
        editable=settings_store.read_safe(),
        readonly=settings_store.read_readonly_masked(),
    )


@bp.route("/api/settings", methods=["POST"])
def api_post_settings():
    data = request.get_json(force=True, silent=True) or {}
    before = settings_store.read_safe()

    try:
        validated = settings_store.write_safe(data)
    except ValueError as e:
        return jsonify(error=str(e)), 400

    db = get_db()
    actor = session["user"]["name"]
    for key, new_value in validated.items():
        detail = json.dumps({"old": before.get(key, ""), "new": new_value}, ensure_ascii=False)
        record(db, actor=actor, action="settings_update", target=key, detail=detail, outcome="success")

    return jsonify(success=True, values=settings_store.read_safe())
