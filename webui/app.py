import secrets

from flask import Flask, session, redirect, url_for, request, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from db import init_db
from extensions import init_oauth
from auth.routes import bp as auth_bp
from api import register_api


def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="/static", template_folder="templates")
    app.config.from_object(Config)

    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        app.logger.warning(
            "SESSION_SECRET не задан в .env — сгенерирован временный ключ, "
            "все сессии слетят при перезапуске контейнера."
        )

    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    init_db(app)
    app.config["OIDC_ENABLED"] = init_oauth(app)

    app.register_blueprint(auth_bp)
    register_api(app)

    @app.before_request
    def _global_auth_gate():
        path = request.path
        if path.startswith("/api/"):
            if not session.get("user"):
                return jsonify(error="unauthorized"), 401
        elif path == "/":
            if not session.get("user"):
                return redirect(url_for("auth.login_page"))

    @app.route("/")
    def index():
        return app.send_static_file("index.html")

    @app.route("/healthz")
    def healthz():
        return jsonify(status="ok")

    return app
