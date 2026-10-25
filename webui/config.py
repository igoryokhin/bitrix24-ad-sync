import os
from datetime import timedelta


def _bool(name, default="false"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    ENV_FILE_PATH = os.getenv("ENV_FILE_PATH", "/app/.env")
    SQLITE_PATH = os.getenv("SQLITE_PATH", "/app/data/webui.db")
    SYNC_LOG_DIR = os.getenv("SYNC_LOG_DIR", "/app/sync-logs")
    AD_SCRIPTS_DIR = os.getenv("AD_SCRIPTS_DIR", "/ad-scripts")

    SECRET_KEY = os.getenv("SESSION_SECRET", "")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", "true")
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

    OIDC_ISSUER = os.getenv("OIDC_ISSUER", "").strip()
    OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "").strip()
    OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "").strip()
    WEB_ADMIN_USERS = {x.strip().lower() for x in os.getenv("WEB_ADMIN_USERS", "").split(",") if x.strip()}

    ADMIN_FALLBACK_ENABLED = _bool("ADMIN_FALLBACK_ENABLED", "false")
    ADMIN_FALLBACK_USERNAME = os.getenv("ADMIN_FALLBACK_USERNAME", "").strip()
    ADMIN_FALLBACK_PASSWORD_HASH = os.getenv("ADMIN_FALLBACK_PASSWORD_HASH", "").strip()

    SYNC_TIMEOUT_SECONDS = int(os.getenv("SYNC_TIMEOUT_SECONDS", "1800"))
