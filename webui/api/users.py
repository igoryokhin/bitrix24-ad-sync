import base64

from flask import Blueprint, request, jsonify, session

from services.ad_client import ad_connection, ADUnavailable, list_users, get_user, list_ous, update_user_attrs, ALLOWED_EDIT_ATTRS
from services.password_reset import do_password_reset, do_resend
from services.audit import record
from db import get_db

bp = Blueprint("api_users", __name__)


def _encode_dn(dn):
    return base64.urlsafe_b64encode(dn.encode("utf-8")).decode("ascii")


def _decode_dn(token):
    return base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")


def _actor():
    return session["user"]["name"]


@bp.route("/api/users")
def api_list_users():
    try:
        with ad_connection() as (conn, ad_common):
            users = list_users(
                conn, ad_common,
                department=request.args.get("department") or None,
                status=request.args.get("status") or None,
                search=request.args.get("q") or None,
            )
    except ADUnavailable as e:
        return jsonify(error=str(e)), 503
    for u in users:
        u["id"] = _encode_dn(u["dn"])
    return jsonify(users=users)


@bp.route("/api/ous")
def api_list_ous():
    try:
        with ad_connection() as (conn, ad_common):
            ous = list_ous(conn, ad_common)
    except ADUnavailable as e:
        return jsonify(error=str(e)), 503
    return jsonify(ous=ous)


@bp.route("/api/users/<user_id>")
def api_get_user(user_id):
    dn = _decode_dn(user_id)
    try:
        with ad_connection() as (conn, ad_common):
            user = get_user(conn, ad_common, dn)
    except ADUnavailable as e:
        return jsonify(error=str(e)), 503
    if not user:
        return jsonify(error="not_found"), 404
    user["id"] = user_id
    return jsonify(user=user)


@bp.route("/api/users/<user_id>", methods=["PATCH"])
def api_patch_user(user_id):
    dn = _decode_dn(user_id)
    data = request.get_json(force=True, silent=True) or {}
    changes = {ALLOWED_EDIT_ATTRS[k]: v for k, v in data.items() if k in ALLOWED_EDIT_ATTRS}

    try:
        with ad_connection() as (conn, ad_common):
            ok = update_user_attrs(conn, dn, changes)
    except ADUnavailable as e:
        return jsonify(error=str(e)), 503
    except ValueError as e:
        return jsonify(error=str(e)), 400

    record(get_db(), actor=_actor(), action="user_update", target=dn,
           detail=str(changes), outcome="success" if ok else "failure")
    return jsonify(success=ok)


def _toggle(user_id, enable):
    dn = _decode_dn(user_id)
    try:
        with ad_connection() as (conn, ad_common):
            ok = ad_common.enable_user(conn, dn) if enable else ad_common.disable_user(conn, dn)
            if ok:
                user = get_user(conn, ad_common, dn)
                if user and user.get("b24_uid"):
                    if enable:
                        ad_common.clear_disabled_at(conn, dn, user["b24_uid"])
                    else:
                        ad_common.set_disabled_at(conn, dn, user["b24_uid"])
    except ADUnavailable as e:
        return jsonify(error=str(e)), 503

    record(get_db(), actor=_actor(), action="user_enable" if enable else "user_disable",
           target=dn, detail=None, outcome="success" if ok else "failure")
    return jsonify(success=ok)


@bp.route("/api/users/<user_id>/enable", methods=["POST"])
def api_enable_user(user_id):
    return _toggle(user_id, enable=True)


@bp.route("/api/users/<user_id>/disable", methods=["POST"])
def api_disable_user(user_id):
    return _toggle(user_id, enable=False)


@bp.route("/api/users/<user_id>/move", methods=["POST"])
def api_move_user(user_id):
    dn = _decode_dn(user_id)
    data = request.get_json(force=True, silent=True) or {}
    target_ou = data.get("target_ou")
    if not target_ou:
        return jsonify(error="target_ou обязателен"), 400

    try:
        with ad_connection() as (conn, ad_common):
            ok = ad_common.move_user(conn, dn, target_ou)
    except ADUnavailable as e:
        return jsonify(error=str(e)), 503

    record(get_db(), actor=_actor(), action="user_move", target=dn,
           detail=target_ou, outcome="success" if ok else "failure")
    return jsonify(success=ok)


@bp.route("/api/users/<user_id>/reset-password", methods=["POST"])
def api_reset_password(user_id):
    dn = _decode_dn(user_id)
    result = do_password_reset(get_db(), dn, _actor())
    if result.get("success"):
        status = 200
    elif result.get("error") == "ad_unavailable":
        status = 503
    elif result.get("error") == "not_found":
        status = 404
    else:
        status = 500
    return jsonify(result), status


@bp.route("/api/users/<user_id>/resend", methods=["POST"])
def api_resend(user_id):
    dn = _decode_dn(user_id)
    result = do_resend(get_db(), dn, _actor())
    if result.get("success"):
        status = 200
    elif result.get("error") == "ad_unavailable":
        status = 503
    elif result.get("error") in ("not_found", "no_stored_password"):
        status = 404
    else:
        status = 500
    return jsonify(result), status


@bp.route("/api/users/<user_id>/messages")
def api_user_messages(user_id):
    dn = _decode_dn(user_id)
    db = get_db()
    rows = db.execute(
        "SELECT id, action, ad_password_set, message_sent, performed_by, performed_at, error_detail "
        "FROM message_log WHERE user_dn = ? ORDER BY performed_at DESC",
        (dn,),
    ).fetchall()
    return jsonify(messages=[dict(r) for r in rows])
