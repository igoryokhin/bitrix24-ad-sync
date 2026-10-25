import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_IDS = {int(x) for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip()}

SQLITE_PATH = os.getenv("SQLITE_PATH", "/app/data/webui.db")
AD_SCRIPTS_DIR = os.getenv("AD_SCRIPTS_DIR", "/ad-scripts")
ENV_FILE_PATH = os.getenv("ENV_FILE_PATH", "/app/.env")
