# Method · private research workspace

A paid Telegram research bot with a responsive **Next.js + React + Tailwind dashboard**, **Flask REST API**, native **Telethon** owner commands and broadcast delivery, **aiohttp** transport, and **Supabase/PostgreSQL** production storage. Local SQLite mode remains available without a DB URL.

This is a deployable implementation, not a guarantee of flawless operation or a 60-second deployment. Real Telegram credentials, a database, hosting configuration and live payment acceptance tests are still required. No host or Supabase project is created automatically.

## Choose your setup

| Mode | Required services | Run |
|---|---|---|
| Local bot only / Termux | Python, bot token, owner ID | `python main.py` |
| Local full stack | Python + Node to build UI, token/owner ID, dashboard secrets | Flask web + bot worker; shared persistent SQLite directory |
| Production / Heroku | Supabase PostgreSQL, Telegram API ID/hash and bot token, web secrets | Separate `web` and `worker` process types |

Production refuses SQLite on ephemeral Heroku storage. A SQLite volume survives normal restarts, not disk loss/deletion. Backups and original encryption keys must be kept separately and outside the host.

## Local bot: no database URL

```bash
git clone https://github.com/Oxeigns/method.git
cd method
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-local.txt
cp .env.example .env
```

Set `BOT_TOKEN` and numeric `ADMIN_ID` in `.env`. Leave `DATABASE_URL` empty and `TELETHON_ENABLED=false`, then run `python main.py`. The database and key are generated once in `DATA_DIR`.

For native Telethon features, set `TELETHON_ENABLED=true`, `API_ID` and `API_HASH` from your own Telegram application at https://my.telegram.org. These application credentials are different from the bot token. Owner-only `/systemstatus` uses Telethon; `/dashboard` works through the Bot API even without Telethon. Paid checkout/receipt ingestion and existing content-management flows remain on aiogram's aiohttp-backed Bot API transport; they have not been discarded during the architecture rebuild.

For Termux, read and run `bash scripts/termux.sh`. Android may suspend background processes; it is not a guarantee of 24/7 hosting. The optional web dashboard can be built on a desktop and copied over if a Next.js build is unavailable on Android.

## Full local dashboard

1. Complete local setup and install `requirements.txt`.
2. Run `python scripts/generate_secrets.py` to generate a web `SECRET_KEY` and a Fernet key. **Existing SQLite deployments: keep your existing data/master.key. Do not replace it with a new key.** The generated Fernet key is for new PostgreSQL deployments; existing local installs may leave `MASTER_ENCRYPTION_KEYS` empty.
3. Send `/dashboard` privately to your bot from the configured owner account. Paste the one-use code into the dashboard within five minutes. An optional `DASHBOARD_PASSWORD_HASH` remains supported for existing installations.
4. Set `PUBLIC_ORIGIN=http://localhost:8000` and your generated `SECRET_KEY`.
5. Build and start:

```bash
npm ci
npm run build
python -m gunicorn wsgi:app --bind 127.0.0.1:8000 --workers 1 --threads 4
```

Run `python main.py` in another terminal using the same `.env` and `DATA_DIR`. Open http://localhost:8000. Flask serves the static Next.js export and `/api` on the same origin; no Node server or cross-origin browser credentials are required after building. `npm run dev` is a frontend development server only; use the Flask-served build for integrated login testing.

Alternatively, `docker compose up --build -d` runs both processes with a shared named volume. Complete the dashboard environment settings first. The dashboard binds to localhost by default. Do not use `docker compose down -v` unless you intend to erase data.

## Supabase / PostgreSQL

- Use a direct connection or **session pooler**, not transaction pooling: the bot holds a session advisory lock. Use your Supabase project's provider-issued PostgreSQL URL.
- Set a stable `MASTER_ENCRYPTION_KEYS` Fernet key or `MASTER_KEY_SEED` shared by every process. PostgreSQL mode will not generate an ephemeral key. Preserve old keys during rotation.
- Apply `migrations/001_postgres.sql` using the migration owner. It creates a private `method` schema, parameterized-query tables, indexes, RLS and seeds.
- For least privilege, create the `method_app` login yourself, run `migrations/provision_role.sql`, and use that role in `DATABASE_URL`. Do not expose `method` in the Supabase Data API or grant access to `anon`/`authenticated`.
- `MIGRATION_DATABASE_URL` may hold an owner connection for the release migration when the runtime role cannot apply DDL. Prefer externally managed migrations if you do not want owner credentials in the app environment.
- Production uses certificate-verifying TLS. Install the provider CA when needed; do not disable certificate checks.
- Every web process has an asyncpg pool, default maximum five connections; the bot has another pool and reserves one connection for its lock. The default two web workers plus bot can use up to 15 database connections. Adjust `DB_POOL_MAX` and web-worker count to your database limit.
- Statement caching is disabled for pooler compatibility. Parameters are bound; request values never become SQL identifiers. Schema/field identifiers are fixed allowlists.

## Heroku

[Deploy to Heroku](https://heroku.com/deploy?template=https://github.com/Oxeigns/method)

`app.json` provides Node then Python buildpacks, explicit configuration requirements, and separate web/worker formations. `Procfile` runs migrations at release, Flask under Gunicorn, and the async bot as a worker. The Next.js static export is built by `heroku-postbuild`.

Fill `BOT_TOKEN`, `ADMIN_ID`, `API_ID`, `API_HASH` and your private `DATABASE_URL`. Heroku generates `MASTER_KEY_SEED` and `SECRET_KEY` automatically; other settings have defaults. No terminal, manual encryption key or password hash is needed for a new Heroku app. The bot issues a five-minute, one-use dashboard login code to the owner through `/dashboard`. Use Heroku's **Open app** button to open the dashboard.

`DATABASE_URL` still must be supplied privately: a Supabase project URL or publishable API key cannot replace a PostgreSQL connection string. Supabase is not provisioned by this button. This repository never includes database passwords. We do not automatically purchase a database add-on. Review Heroku dyno costs before deploying.

Back up `MASTER_KEY_SEED` and keep it unchanged across redeploys/restores. Existing deployments using `MASTER_ENCRYPTION_KEYS` retain priority and must keep their original keys. Do not regenerate a seed for an existing database. The generated seed is converted to a Fernet key using a domain-separated SHA-256 derivation; it is independent of the bot token and session secret.

`PUBLIC_ORIGIN` is optional: when absent, the API compares the browser Origin to its own request origin. HTTPS/proxy handling is enabled on Heroku; arbitrary cross-origin requests remain rejected. An explicit `PUBLIC_ORIGIN` pins a custom domain when desired. `TRUST_PROXY=true` is for Heroku's trusted reverse proxy only. Keep one Telegram polling worker.


`.python-version` selects Python 3.12; `runtime.txt` is retained for the requested legacy blueprint. Heroku now recommends `.python-version` and deprecates `runtime.txt`:
https://devcenter.heroku.com/articles/python-runtimes

For continuous deployment, enable your Heroku app's GitHub integration and select **wait for CI to pass before deploy**. No GitHub deployment credential is embedded. GitHub Actions tests both backends and builds/tests the dashboard; it does not provision or deploy a paid app without your Heroku configuration.

## Owner workflows

The dashboard includes analytics, paginated catalog/pricing, reference creation/editing, publication controls, users/bans, transactions and confirmed broadcasts. Existing bot `/adminpanel` retains support/payment settings, content backup/restore, access extensions/revocation, payment verification and refunds. Content edits made in the bot increment revisions so a stale browser editor cannot overwrite them silently.

- New/edited entries are encrypted drafts. Publishing does not verify the truth of supplied claims, contacts or legal assertions.
- Enter real research privately through the bot or dashboard. Nothing from your previously supplied complaint/appeal drafts is committed to the public source repository.
- `/backup` exports password-encrypted content; `/restore` imports it into new disabled services with draft entries. Prior `.vault` files still work.
- Existing SQLite data is preserved with additive schema changes. PostgreSQL is a separate deployment target, **not an automatic migration of your SQLite users/payments**. Content can move via `/backup` and `/restore`; migrate/reconcile live billing records before changing backends.
- Local encrypted system snapshots remain available. PostgreSQL deployments need provider backups/PITR plus your separately retained encryption key.
- The original ZIP is a legacy upload. Run current root source files, not the old ZIP.

## Payments and content protection

The deployment template and example environment select owner-verified UPI as requested. Telegram requires Stars for digital goods sold inside Telegram apps: https://core.telegram.org/bots/payments-stars. UPI does not meet that requirement for research sales. Set PAYMENT_MODE=stars to use the compliant in-app payment mode. One-time purchases support finite or lifetime access; recurring billing is not implemented.

For an existing Heroku app, set PAYMENT_MODE=upi and ACKNOWLEDGE_UPI_PLATFORM_RESTRICTION=true in Config Vars; updating app.json does not change existing configuration. Bank settlement must be verified manually; screenshots alone are not proof.

UPI owner setup: `/adminpanel` → Payment / Support → `upi_id yourname@bank`. Verification Queue provides Approve/Reject; only approval grants access. Service Settings accepts `1 validity_days 30` (0 = lifetime) and `1 delete_after_seconds 86400` (24 hours). Replace 1 with the service ID. Validity is captured at checkout and starts on approval; renewals extend active finite access. Payment screenshots have a 30-minute submission window; submitted evidence remains reviewable afterwards. Profiles show expiry and remaining days/hours when opened. Message deletion is queued from delivery and may be delayed during outages. Existing purchases keep their validity.

Fernet encrypts research at rest with service binding. Messages use protected delivery and durable deletion jobs. Telegram bot chats are not end-to-end encrypted; web/API previews necessarily reveal plaintext to the authenticated owner. Content protection cannot stop external cameras or all copying. Do not enable request-body/debug logging, core dumps or insecure backups.

## Verification

```bash
pip install -r requirements-dev.txt
python -m pytest -q
npm ci
npm run build
npm run typecheck
```

Real PostgreSQL conformance test (use a disposable database only):

```bash
TEST_DATABASE_URL=postgresql://test:test@localhost/method_test python -m pytest -q
```

Browser integration after building:

```bash
pip install playwright==1.58.0
python -m playwright install chromium
python scripts/browser_smoke.py
```

CI provisions a disposable PostgreSQL service, runs the Python tests, builds/type-checks Next.js, and exercises browser login, service creation, encrypted draft save, publication, mobile width and logout. Tests use synthetic data. Live Telegram/Supabase/Heroku checks still require actual credentials and infrastructure.

See [architecture and contracts](docs/ARCHITECTURE.md) for the five-goal design, JSON menus, REST endpoints, concurrency algorithm and operational limits.


### Deploy first, connect storage later (Heroku)
Leave DATABASE_URL and MIGRATION_DATABASE_URL empty when deploying. The release skips database initialization, the web process displays setup status, and the worker accepts /adminpanel from ADMIN_ID in a private chat. Purchases and research access remain disabled. No temporary customer database is created.

In the owner setup panel choose Connect database in Heroku. Select the app, open Settings → Reveal Config Vars, and save DATABASE_URL there. Heroku restarts both processes with durable configuration. No database credentials or Heroku API authorizations are collected by the bot. Keep the original encryption seed/keys. The owner panel opens Heroku rather than storing credentials in Telegram.


Existing apps: clear stale DATABASE_URL and MIGRATION_DATABASE_URL only to enter setup mode; this does not delete the old database. Reconnect the original database to retain existing purchases and methods. Config updates do not run release commands, so the worker also applies idempotent migrations on startup. Run exactly one worker during setup.
