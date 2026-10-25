from pathlib import Path

from flask import Blueprint, request, jsonify, session, Response

from services import sync_runner
from db import get_db

bp = Blueprint("api_sync", __name__)


@bp.route("/api/sync/trigger", methods=["POST"])
def api_trigger_sync():
    data = request.get_json(force=True, silent=True) or {}
    run_type = data.get("type")
    if run_type not in ("full", "delta"):
        return jsonify(error="type должен быть 'full' или 'delta'"), 400

    result = sync_runner.trigger_sync(run_type, session["user"]["name"])
    if "error" in result:
        return jsonify(result), 409
    return jsonify(result), 202


@bp.route("/api/sync/runs")
def api_list_runs():
    db = get_db()
    rows = db.execute(
        "SELECT id, run_type, status, triggered_by, started_at, finished_at, exit_code "
        "FROM sync_runs ORDER BY started_at DESC LIMIT 50"
    ).fetchall()
    return jsonify(runs=[dict(r) for r in rows])


@bp.route("/api/sync/runs/<int:run_id>")
def api_get_run(run_id):
    db = get_db()
    row = db.execute("SELECT * FROM sync_runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return jsonify(error="not_found"), 404
    return jsonify(run=dict(row))


@bp.route("/api/sync/runs/<int:run_id>/log")
def api_get_run_log(run_id):
    db = get_db()
    row = db.execute("SELECT log_path FROM sync_runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return jsonify(error="not_found"), 404
    log_path = Path(row["log_path"])
    if not log_path.exists():
        return Response("(лог ещё не создан)", mimetype="text/plain; charset=utf-8")
    return Response(log_path.read_text(encoding="utf-8", errors="replace"), mimetype="text/plain; charset=utf-8")
