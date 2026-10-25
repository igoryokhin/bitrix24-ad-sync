CREATE TABLE IF NOT EXISTS sync_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type      TEXT NOT NULL CHECK (run_type IN ('full','delta')),
    status        TEXT NOT NULL CHECK (status IN ('running','success','failed')),
    triggered_by  TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    exit_code     INTEGER,
    log_path      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sync_runs_started ON sync_runs(started_at DESC);

-- Пароли нигде не хранятся: только факт установки/отправки.
CREATE TABLE IF NOT EXISTS message_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_dn          TEXT NOT NULL,
    b24_uid          TEXT,
    login            TEXT,
    action           TEXT NOT NULL CHECK (action IN ('password_reset','credentials_resend')),
    ad_password_set  INTEGER NOT NULL DEFAULT 0,
    message_sent     INTEGER NOT NULL DEFAULT 0,
    performed_by     TEXT NOT NULL,
    performed_at     TEXT NOT NULL,
    error_detail     TEXT
);
CREATE INDEX IF NOT EXISTS idx_message_log_user ON message_log(user_dn);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT,
    detail      TEXT,
    outcome     TEXT NOT NULL CHECK (outcome IN ('success','failure')),
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at DESC);
