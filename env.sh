# AD
export AD_SERVER=
export AD_USER=
export AD_PASSWORD=
export AD_UPN_SUFFIX=
export AD_BASE_DN=

# Bitrix24 — вставьте свои свежие коды!
export BITRIX_WEBHOOK=
export BITRIX_NOTIFY_WEBHOOK=

# Тестовый режим
export TEST_RECIPIENT_ID=

# Параметры
export PASSWORD_LENGTH=14
export COMPANY_NAME=
export ADMIN_GROUP_NAME=
export DISABLED_RETENTION_DAYS=180
export TZ=Europe/Moscow

# Web Admin Panel (webui) — для локального запуска вне Docker
export ENV_FILE_PATH="$(pwd)/.env"
export SQLITE_PATH="$(pwd)/webui/data/webui.db"
export SYNC_LOG_DIR="$(pwd)/logs"
export AD_SCRIPTS_DIR="$(pwd)"
export PUBLIC_BASE_URL='http://127.0.0.1:8088'
export SESSION_SECRET=
export SESSION_COOKIE_SECURE=false
export OIDC_ISSUER=
export OIDC_CLIENT_ID=ad-webui
export OIDC_CLIENT_SECRET=
export ADMIN_FALLBACK_ENABLED=true
export ADMIN_FALLBACK_USERNAME=admin
export ADMIN_FALLBACK_PASSWORD_HASH=

# Telegram-бот — для локального запуска вне Docker
export TELEGRAM_BOT_TOKEN=
export TELEGRAM_ADMIN_IDS=
export MAIL_INSTRUCTION_URL=
export MESSAGE_LOG_DB_PATH="$(pwd)/webui/data/webui.db"
export CREDENTIAL_ENCRYPTION_KEY=
