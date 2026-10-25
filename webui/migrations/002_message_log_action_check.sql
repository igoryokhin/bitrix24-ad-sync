-- Расширяет CHECK на message_log.action: добавляет 'credentials_initial'
-- (сообщение, отправленное full_sync.py/delta_sync.py при создании
-- учётки — теперь тоже попадает в message_log, см. ad_common.py).
-- SQLite не умеет ALTER CHECK — пересоздаём таблицу и переносим данные.
-- Выполняется один раз благодаря версионированию PRAGMA user_version в
-- webui/db.py:init_db().

CREATE TABLE IF NOT EXISTS message_log_v2 (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_dn          TEXT NOT NULL,
    b24_uid          TEXT,
    login            TEXT,
    action           TEXT NOT NULL CHECK (action IN (
                         'password_reset', 'credentials_resend', 'credentials_initial'
                     )),
    ad_password_set  INTEGER NOT NULL DEFAULT 0,
    message_sent     INTEGER NOT NULL DEFAULT 0,
    performed_by     TEXT NOT NULL,
    performed_at     TEXT NOT NULL,
    error_detail     TEXT
);

INSERT INTO message_log_v2
    SELECT id, user_dn, b24_uid, login, action, ad_password_set,
           message_sent, performed_by, performed_at, error_detail
    FROM message_log;

DROP TABLE message_log;
ALTER TABLE message_log_v2 RENAME TO message_log;

CREATE INDEX IF NOT EXISTS idx_message_log_user ON message_log(user_dn);
CREATE INDEX IF NOT EXISTS idx_message_log_b24uid ON message_log(b24_uid);
