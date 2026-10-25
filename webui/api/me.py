from flask import Blueprint, session, jsonify

bp = Blueprint("api_me", __name__)


@bp.route("/api/me")
def api_me():
    user = session.get("user") or {}
    return jsonify(name=user.get("name"), method=user.get("method"))
