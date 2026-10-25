import sqlite3
from pathlib import Path

from flask import g, current_app

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["SQLITE_PATH"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        # Теперь в этот файл пишут 3 процесса (webui, бот, ad-sync) —
        # короткий busy_timeout убирает редкие "database is locked".
        g.db.execute("PRAGMA busy_timeout=5000")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    """Применяет migrations/NNN_*.sql по порядку, по одному разу каждую —
    версия отслеживается через встроенный PRAGMA user_version (без
    отдельной таблицы). Важно для миграций, которые пересоздают таблицу
    (SQLite не умеет ALTER CHECK) — такие нельзя гонять на каждом старте."""
    Path(app.config["SQLITE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(app.config["SQLITE_PATH"])
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(migration.stem.split("_", 1)[0])
            if version <= current:
                continue
            conn.executescript(migration.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
    finally:
        conn.close()
    app.teardown_appcontext(close_db)
