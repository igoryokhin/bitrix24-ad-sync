"""Лёгкий sqlite3-коннект без Flask — каждый вызов открывает своё
соединение (вызывается из asyncio.to_thread, соединения между потоками
не шарятся)."""
import sqlite3

import config


def get_db():
    conn = sqlite3.connect(config.SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
