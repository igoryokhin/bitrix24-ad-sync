-- Хранилище ТЕКУЩЕГО пароля пользователя (зашифрован, ключ —
-- CREDENTIAL_ENCRYPTION_KEY в .env) — нужно для "напомнить пароль" без
-- его смены при каждой рассылке. См. ad_common.py:store_encrypted_password/
-- get_stored_password и webui/services/password_reset.py:do_resend*.

CREATE TABLE IF NOT EXISTS credential_store (
    user_dn            TEXT PRIMARY KEY,
    encrypted_password TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
