import time
from urllib.parse import urlencode

from flask import Blueprint, render_template, redirect, url_for, request, session, current_app, abort
from werkzeug.security import check_password_hash

from extensions import oauth
from db import get_db
from services.audit import record

bp = Blueprint("auth", __name__)


@bp.route("/login")
def login_page():
    if session.get("user"):
        return redirect("/")
    return render_template(
        "login.html",
        oidc_enabled=current_app.config.get("OIDC_ENABLED", False),
        fallback_enabled=current_app.config["ADMIN_FALLBACK_ENABLED"],
        error=request.args.get("error"),
    )


@bp.route("/auth/oidc/login")
def oidc_login():
    if not current_app.config.get("OIDC_ENABLED"):
        return redirect(url_for("auth.login_page"))
    redirect_uri = current_app.config["PUBLIC_BASE_URL"] + url_for("auth.oidc_callback")
    return oauth.keycloak.authorize_redirect(redirect_uri)


@bp.route("/auth/oidc/callback")
def oidc_callback():
    if not current_app.config.get("OIDC_ENABLED"):
        return redirect(url_for("auth.login_page"))
    token = oauth.keycloak.authorize_access_token()
    userinfo = token.get("userinfo") or {}
    username = userinfo.get("preferred_username") or userinfo.get("email") or userinfo.get("sub") or "unknown"

    session.clear()
    session.permanent = True
    session["user"] = {"name": username, "method": "oidc"}
    session["id_token"] = token.get("id_token")

    record(get_db(), actor=username, action="login", target=None, detail="oidc", outcome="success")
    return redirect("/")


@bp.route("/auth/fallback", methods=["POST"])
def fallback_login():
    if not current_app.config["ADMIN_FALLBACK_ENABLED"]:
        abort(404)

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    expected_user = current_app.config["ADMIN_FALLBACK_USERNAME"]
    expected_hash = current_app.config["ADMIN_FALLBACK_PASSWORD_HASH"]

    if username and expected_hash and username == expected_user and check_password_hash(expected_hash, password):
        session.clear()
        session.permanent = True
        session["user"] = {"name": username, "method": "fallback"}
        record(get_db(), actor=username, action="login", target=None, detail="fallback", outcome="success")
        return redirect("/")

    # Наивный троттлинг брутфорса без внешних зависимостей.
    time.sleep(1)
    record(get_db(), actor=username or "?", action="login", target=None, detail="fallback", outcome="failure")
    return redirect(url_for("auth.login_page", error="invalid_credentials"))


@bp.route("/auth/logout")
def logout():
    user = session.get("user") or {}
    id_token = session.get("id_token")
    method = user.get("method")
    session.clear()

    if method == "oidc" and current_app.config.get("OIDC_ENABLED"):
        try:
            metadata = oauth.keycloak.load_server_metadata()
            end_session_endpoint = metadata.get("end_session_endpoint")
            if end_session_endpoint:
                params = {"post_logout_redirect_uri": current_app.config["PUBLIC_BASE_URL"] + url_for("auth.login_page")}
                if id_token:
                    params["id_token_hint"] = id_token
                return redirect(f"{end_session_endpoint}?{urlencode(params)}")
        except Exception:
            pass

    return redirect(url_for("auth.login_page"))
