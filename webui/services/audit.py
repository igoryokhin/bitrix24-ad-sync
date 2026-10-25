from datetime import datetime, timezone


def record(db, actor, action, target, detail, outcome):
    db.execute(
        "INSERT INTO audit_log (actor, action, target, detail, outcome, created_at) VALUES (?,?,?,?,?,?)",
        (actor, action, target, detail, outcome, datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
