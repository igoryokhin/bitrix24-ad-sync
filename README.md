# Bitrix24 → Active Directory Sync

A Docker Compose application that synchronizes users, departments and groups from Bitrix24 to Microsoft Active Directory. It includes scheduled full/delta sync jobs, a web administration panel, and an optional Telegram bot.

> **Important:** this software can create, modify, disable and eventually delete AD accounts. Review the code and configuration before use. Do not point it at production AD until you have tested in a disposable test domain and reviewed all privilege-assignment rules. There is no dry-run guarantee in the current implementation.

## Components

- **Sync worker** — Python scripts for full and incremental synchronization.
- **Web UI** — Flask-based panel with run history, audit log and manual sync controls.
- **Telegram bot** — optional restricted administrative workflows.
- **SQLite** — local UI/audit state persisted under `webui/data/`.
- **Supercronic** — runs scheduled sync jobs inside the worker container.

## Requirements

- Docker Engine and Docker Compose v2
- Network connectivity from the host to Bitrix24 and an LDAPS-enabled AD domain controller
- A dedicated AD service account with only the permissions required by your chosen features
- Bitrix24 webhook credentials with the required API scopes
- A trusted LDAPS certificate whose SAN matches the hostname used in `AD_SERVER`

## Configure

1. Clone this repository.
2. Create a private environment file from the template:
   ```sh
   cp .env.example .env
   chmod 600 .env
   ```
3. Set every required value in `.env`. Never commit `.env`, webhook URLs, passwords, session secrets, OIDC secrets, Telegram tokens, or encryption keys.
4. Configure the AD host and certificate. Use a DNS name matching the LDAPS certificate; for an internal CA, mount its CA bundle into the relevant containers and set `AD_TLS_CA_CERT` to that in-container path. Certificate validation is enabled by default. Do not disable it in production.
5. Review the configured base DN, OUs, retention policy, group/administrator rules, Bitrix24 permissions, and all environment-specific values in `ad_common.py`, `full_sync.py`, and `delta_sync.py`.
6. **Before starting the worker**, be aware that its entrypoint automatically runs `full_sync.py` when `./logs/.initialized` does not exist. This can create accounts and apply role/group rules. Back up AD and test first.

The Compose file uses `AD_SERVER_HOST` and `AD_SERVER_IP` for optional host mapping. The default IP is from the documentation-only TEST-NET range; replace it if you rely on this mapping.

## Start

Only after completing the safety review and configuring a test environment:

```sh
docker compose config
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=200 ad-sync webui
```

The Telegram bot is optional and is disabled unless the `telegram` Compose profile is enabled. After configuring its token and administrator IDs, start it with `docker compose --profile telegram up -d tgbot` and inspect it with `docker compose logs --tail=200 tgbot`.

The web panel is bound to `127.0.0.1:8088` on the host by default. Put it behind a properly configured reverse proxy with HTTPS and access controls if remote access is needed. Do not expose the application directly to the internet.

The panel supports OIDC/Keycloak when configured. Set `WEB_ADMIN_USERS` to a comma-separated allowlist of exact OIDC usernames/emails; login is denied if the list is empty or the user is not listed. Keep the local fallback login disabled unless you have deliberately configured and secured it. Set a strong persistent `SESSION_SECRET`; configure secure cookies when served over HTTPS.

## Scheduled jobs

The current `crontab` runs delta syncs on a schedule and a full sync on the first Sunday of each month. Review and adjust these times for your environment before enabling the worker.

## Security and operational notes

- LDAPS certificate validation is on by default. If your AD uses a private CA, trust that CA; do not work around certificate errors by turning validation off.
- Use a dedicated least-privilege AD account. Privileged group assignment is disabled by default; do not enable `ENABLE_ADMIN_GROUP_ASSIGNMENT` unless you have reviewed the department keyword rules and the exact target group. Never grant Domain Admins merely because a department name matches a keyword.
- The delta sync includes account deactivation and deletion after a configurable retention period. Validate the behavior and source-of-truth assumptions with test accounts first.
- Store secrets in a secret manager or protected deployment environment where possible. The `.env` file is ignored by Git, but remains plaintext on disk.
- Back up the AD and the SQLite data before upgrades. Keep logs access-controlled; they may contain account-related operational information.
- The web UI can start full/delta sync jobs. Restrict access to trusted administrators and use SSO, strong secrets, HTTPS and reverse-proxy protections.
- Do not use production data or credentials in CI. CI only performs static syntax/configuration checks; it does not connect to AD or Bitrix24.

## Validation

GitHub Actions checks Python syntax and parses the YAML configuration files. These checks do not prove that the application is safe for your AD topology or that a synchronization run will succeed.

## Project status

This repository is published for review and development. Validate it in an isolated test environment before any operational deployment. No license is specified yet; ask the repository owner before redistributing or reusing it.
