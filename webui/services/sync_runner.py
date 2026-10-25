"""
Запуск full_sync.py/delta_sync.py как subprocess из веб-панели. Скрипты не
меняются и не дублируются — тот же файл, что запускает cron внутри ad-sync
(смонтирован read-only). Запрос возвращается почти мгновенно, реальная
синхронизация идёт в фоновом потоке.

Advisory-лок на общем с ad-sync volume (./logs) — единственная новая защита
от гонки: раньше от параллельных запусков берёг только `supercronic
-no-overlap` внутри одного контейнера, а теперь появился второй путь
запуска (панель), который может пересечься с cron в другом контейнере.
"""
import os
import sys
import sqlite3
import fcntl
import threading
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app
from dotenv import dotenv_values


def _lock_path(sync_log_dir, run_type):
    return Path(sync_log_dir) / f"{run_type}.lock"


def _try_acquire(sync_log_dir, run_type):
    path = _lock_path(sync_log_dir, run_type)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


def _release(fh):
    try:
        fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        fh.close()


def trigger_sync(run_type, triggered_by):
    if run_type not in ("full", "delta"):
        raise ValueError("run_type must be 'full' or 'delta'")

    app = current_app._get_current_object()
    sync_log_dir = app.config["SYNC_LOG_DIR"]
    db_path = app.config["SQLITE_PATH"]

    lock_fh = _try_acquire(sync_log_dir, run_type)
    if lock_fh is None:
        return {"error": "already_running"}

    started_at = datetime.now(timezone.utc)
    log_path = Path(sync_log_dir) / f"{run_type}_{started_at.strftime('%Y%m%dT%H%M%S')}.log"

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO sync_runs (run_type, status, triggered_by, started_at, log_path) "
            "VALUES (?, 'running', ?, ?, ?)",
            (run_type, triggered_by, started_at.isoformat(), str(log_path)),
        )
        run_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    thread = threading.Thread(
        target=_worker,
        args=(app.config["AD_SCRIPTS_DIR"], app.config["ENV_FILE_PATH"], app.config["SYNC_TIMEOUT_SECONDS"],
              run_id, run_type, str(log_path), db_path, lock_fh, triggered_by),
        daemon=True,
    )
    thread.start()
    return {"run_id": run_id, "status": "running"}


def _worker(scripts_dir, env_path, timeout, run_id, run_type, log_path, db_path, lock_fh, triggered_by):
    script = os.path.join(scripts_dir, "full_sync.py" if run_type == "full" else "delta_sync.py")
    fresh_env = {k: v for k, v in dotenv_values(env_path).items() if v is not None}
    env = {**os.environ, **fresh_env}

    exit_code = None
    status = "failed"
    try:
        with open(log_path, "wb") as logf:
            proc = subprocess.run(
                [sys.executable, script], cwd=scripts_dir, env=env,
                stdout=logf, stderr=subprocess.STDOUT, timeout=timeout,
            )
        exit_code = proc.returncode
        status = "success" if exit_code == 0 else "failed"
    except subprocess.TimeoutExpired:
        status = "failed"
        with open(log_path, "a", encoding="utf-8") as logf:
            logf.write(f"\n[webui] Превышен таймаут ({timeout}s), процесс остановлен\n")
    except Exception as e:
        with open(log_path, "a", encoding="utf-8") as logf:
            logf.write(f"\n[webui] Ошибка запуска: {e}\n")
    finally:
        finished_at = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE sync_runs SET status=?, finished_at=?, exit_code=? WHERE id=?",
                (status, finished_at, exit_code, run_id),
            )
            conn.execute(
                "INSERT INTO audit_log (actor, action, target, detail, outcome, created_at) "
                "VALUES (?, 'sync_trigger', ?, ?, ?, ?)",
                (triggered_by, run_type, f"exit_code={exit_code}", status, finished_at),
            )
            conn.commit()
        finally:
            conn.close()
        _release(lock_fh)
