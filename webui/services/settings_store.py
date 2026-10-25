"""
Настройки читаются/пишутся напрямую в общий .env (без отдельной таблицы
оверрайдов в БД) — самый простой вариант, который всё ещё даёт мгновенный
эффект для запусков синка из панели (sync_runner берёт свежий .env на
момент запуска subprocess). Для cron-запусков внутри ad-sync эффект наступит
только после ручного `docker compose restart ad-sync` — панель явно
предупреждает об этом в UI.
"""
import os
import re

from dotenv import dotenv_values, set_key

SAFE_KEYS = [
    "TEST_RECIPIENT_ID",
    "PASSWORD_LENGTH",
    "DISABLED_RETENTION_DAYS",
    "ADMIN_GROUP_NAME",
    "INSTRUCTION_URL",
]

# Ключи, которые НИКОГДА нельзя менять через API — даже если фронтенд их
# случайно пришлёт. В частности ADMIN_FALLBACK_* умышленно недоступны для
# правки из самой панели: скомпрометированная сессия не должна суметь снова
# включить локальный вход в обход Keycloak.
FORBIDDEN_PREFIXES = ("ADMIN_FALLBACK_", "AD_PASSWORD", "SESSION_SECRET")

BOUNDS = {
    "PASSWORD_LENGTH": (8, 64),
    "DISABLED_RETENTION_DAYS": (1, 3650),
}

_WEBHOOK_TOKEN_RE = re.compile(r"(rest/)[^/]+/[^/]+/")


def _env_path():
    # Читается напрямую из env (не через Flask current_app), чтобы этот
    # модуль был импортируем и из не-Flask процессов (Telegram-бот).
    return os.getenv("ENV_FILE_PATH", "/app/.env")


def read_safe():
    values = dotenv_values(_env_path())
    return {k: values.get(k, "") for k in SAFE_KEYS}


def _mask_webhook(url):
    if not url:
        return ""
    return _WEBHOOK_TOKEN_RE.sub(r"\1•••/•••/", url)


def read_readonly_masked():
    values = dotenv_values(_env_path())
    return {
        "AD_SERVER": values.get("AD_SERVER", ""),
        "AD_USER": values.get("AD_USER", ""),
        "AD_BASE_DN": values.get("AD_BASE_DN", ""),
        "AD_UPN_SUFFIX": values.get("AD_UPN_SUFFIX", ""),
        "COMPANY_NAME": values.get("COMPANY_NAME", ""),
        "BITRIX_WEBHOOK": _mask_webhook(values.get("BITRIX_WEBHOOK", "")),
        "BITRIX_NOTIFY_WEBHOOK": _mask_webhook(values.get("BITRIX_NOTIFY_WEBHOOK", "")),
    }


def write_safe(changes: dict):
    for key in changes:
        if key not in SAFE_KEYS or key.startswith(FORBIDDEN_PREFIXES):
            raise ValueError(f"{key} нельзя редактировать через панель")

    validated = {}
    for key, raw_value in changes.items():
        value = str(raw_value).strip()
        if key in BOUNDS:
            lo, hi = BOUNDS[key]
            try:
                n = int(value)
            except ValueError:
                raise ValueError(f"{key} должно быть числом")
            if not (lo <= n <= hi):
                raise ValueError(f"{key} должно быть в диапазоне {lo}–{hi}")
            value = str(n)
        validated[key] = value

    path = _env_path()
    for key, value in validated.items():
        set_key(path, key, value, quote_mode="never")
    return validated


def get_effective(key, fallback=None):
    values = dotenv_values(_env_path())
    val = values.get(key)
    return val if val not in (None, "") else fallback
