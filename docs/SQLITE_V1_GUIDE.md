# Method — encrypted Telegram research bot

**DB URL nahi chahiye. Redis bhi nahi chahiye.** Set your Telegram bot token and owner ID, then start the bot. It creates its database and encryption key automatically.

All data stays in a local SQLite database under `DATA_DIR`. Docker Compose uses a persistent named volume. Prices, research drafts, published content, users, purchases, admin settings, queues and unfinished input flows survive normal restarts and container rebuilds.

> Persistent does not mean indestructible: deleting the volume, losing the host disk, or using an ephemeral hosting filesystem can lose data. Download content backups and keep an independent copy of the full database backup **and its original master.key**. No paid hosting or cloud database has been provisioned by this repository.

## Start in 3 steps

```bash
git clone https://github.com/Oxeigns/method.git
cd method
cp .env.example .env
```

Edit `.env` locally:

```dotenv
BOT_TOKEN=your_new_botfather_token
ADMIN_ID=your_numeric_telegram_user_id
```

Then:

```bash
docker compose up --build -d
```

Open your bot, press Start, then send `/adminpanel`. The owner must press Start before the bot can send verification notifications. Never put your token, password, backup, real research or `data/` in GitHub.

Without Docker, use Linux and Python 3.12:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Keep this process running under a supervisor. The default storage path is `./data`; use an absolute `DATA_DIR` path for a supervised service. Run **one bot replica** against a local disk, not an NFS/share. The process uses an OS file lock to refuse another instance sharing the same storage path.

## Manage everything from your bot

| Need | Owner action |
|---|---|
| Add a service/method | `/adminpanel` → Service Settings → `new Your service name` |
| Add reference data | Manage Content → service → Add → title → text or UTF-8 `.txt` file |
| Edit existing content | Manage Content → entry → Edit text |
| Preview safely | Entry → Preview (protected message; deletion queued for one hour) |
| Publish to buyers | Entry → Publish; service must also be active |
| Remove from sale | Entry → Unpublish, or set service `is_active false` |
| Delete content | Entry → Delete → Confirm delete |
| Change title | Entry → Rename |
| Change INR reference price | Service Settings → `1 price 1500` |
| Change live Stars price | Service Settings → `1 stars_price 100` |
| Change access duration | Service Settings → `1 validity_days 30` (`0` = lifetime while service operates) |
| Change content deletion time | Service Settings → `1 delete_after_seconds 86400` (60–86400 seconds) |
| Rename service | Service Settings → `1 service_name New name` |
| Change description | Service Settings → `1 description Your description` |
| Activate/archive service | Service Settings → `1 is_active true` / `1 is_active false` |
| Set support | Payment / Support → `support_username @YourUsername` |
| Change purchase terms | Payment / Support → `terms Your purchase and refund terms` |
| Ban/unban, revoke, extend | User Management shows the required input format |
| Analytics / payment review | Analytics / Verification Queue |
| Announcement | Broadcast → preview → confirm |
| Refund Stars | Stars Refund → transaction UUID |
| Download private content | `/backup` or Content Backup |
| Restore private content | `/restore` or Restore / Import |
| Import your own JSON data | `/import` or Restore / Import → Import reference JSON |

Use the actual service number shown by the bot instead of `1`. After changing one setting, reopen Service Settings to change another. `/cancel` ends any input flow.

Editing text returns an entry to **draft**, so unfinished edits are not accidentally delivered to buyers. Imports also create drafts. Draft content cannot be purchased or delivered. Publishing is the owner's editorial decision; it does not establish that an allegation, email address, policy or legal statement is verified. The bot does not send reports to Telegram, institutes or third parties.

Service archival is intentional: transaction and purchase history must not be destroyed by deleting a sold service. Draft entries can be permanently deleted individually. Previously delivered messages are not recalled by editing, unpublishing or deleting an entry; their existing deletion schedule continues.

## Your supplied reference drafts

The repository contains **no real supplied complaint text, evidence links, private research, passwords or verified contact claims**. `docs/content-import.example.json` contains placeholder data only. Your private `.vault` reference file, if supplied separately, can be uploaded through `/restore` with its separate password. It imports as new disabled reference services and unpublished entries; review it before publishing.

This separates your supplied data from publicly readable source code. No hardcoded “methods” or promises of bans/unbans are shipped.

## Services and payment choices

Default INR reference prices are preserved:

| ID | Service | INR reference price |
|---|---|---:|
| 1 | Specific Reporting Method | ₹1,500 |
| 2 | Account Limit Removal Guide | ₹300 |
| 3 | Channel Unban Procedure/Format | ₹1,500 |
| 4 | Group Ban Procedure/Format | ₹2,000 |
| 5 | Local Laws & Compliance Frameworks | ₹15,000 |

**Stars is the default live checkout.** Telegram requires Stars for digital goods sold in Telegram apps. Set each `stars_price` yourself; no INR-to-Stars conversion is assumed. Empty/draft-only services and services without a Stars price cannot be purchased.

Source: https://core.telegram.org/bots/payments-stars

The requested UPI screenshot implementation remains optional and disabled:

```dotenv
PAYMENT_MODE=upi
ACKNOWLEDGE_UPI_PLATFORM_RESTRICTION=true
```

This acknowledgement is **not an exemption** from Telegram's rules. Keep Stars for this digital-research deployment. If reviewing that optional implementation, set `upi_id yourname@bank` from Payment / Support. Screenshots enter the owner's queue, and actual bank settlement must be verified before approving. Screenshots alone do not prove payment; no bank/UTR API is integrated.

Purchases are one-time grants with configurable validity, not automatically recurring subscriptions. Renewals extend finite access. Stars payment receipts are persisted before Telegram's update offset advances; charge IDs deduplicate replays. Approval, entitlement and delivery queue updates commit in a single SQLite transaction.

## Backups and restore

### Content backup from the bot — portable across hosts

1. Send `/backup`.
2. Choose a backup password with 16–256 characters. Keep it separately in a password manager.
3. The bot returns a password-encrypted `research-content.vault` document. **Download it somewhere independent of this server.**
4. To import it into this or another installation, use `/restore`, upload the file and provide its password. Review the counts, then confirm.

A content backup includes service names, descriptions, prices, durations and all draft/published entry text. It excludes users, purchases, credentials and the master key. Restore is **additive**: it creates disabled services with draft entries and never overwrites existing content, entitlements or payments. Exact duplicate imports are rejected. Review, set/confirm prices, publish entries, then activate each new service.

Passwords are used in memory and are not saved in FSM/database logs. Incoming password/content messages are deleted where Telegram permits. Telegram bot chats are not end-to-end encrypted; do not use chat-based entry if your threat model excludes Telegram itself. Export encryption uses a random salt, scrypt and authenticated Fernet encryption.

### Full system snapshots — local automatic recovery

The bot takes an encrypted snapshot at startup if no recent copy exists, then approximately daily, keeping the newest seven in `data/backups/system-*.backup`. SQLite's online backup API includes committed WAL data; copying only the live `.sqlite3` file is not a safe substitute.

These full backups contain users, payments, research ciphertext and settings. They are encrypted with `data/master.key`. **They cannot be restored without that original key.** Keep backups and key in separate secure external storage. Daily copies on the same disk protect against some corruption/operator mistakes; they do not protect against loss of that disk.

For disaster recovery, stop the bot and restore into a new directory:

```bash
python restore_system.py \
  --backup /safe/system-YYYYMMDD.backup \
  --key-file /safe/original-master.key \
  --data-dir /srv/method-recovered
```

Set `DATA_DIR=/srv/method-recovered` and restart only after reconciling payments newer than the snapshot. The restore tool validates database integrity and vault decryption. It refuses to overwrite an existing database/key. Old input states are cleared, pending deliveries are blocked and old broadcasts are marked complete to avoid unsolicited replays; buyers can request content again. Restore does not recreate transactions that occurred after the snapshot.

For Docker, copy backups/key securely from the named volume or perform restore in a maintenance container while the bot is stopped. Never run `docker compose down -v` unless you intentionally want to delete all stored data. Normal `docker compose down` keeps the volume.

## Security boundaries

- SQLite stores each research body as authenticated Fernet ciphertext bound to its service ID. Prices, titles and transaction metadata are not individually encrypted. Full backup files are encrypted as a whole.
- The master key is generated once in `data/master.key` with restrictive permissions. If a database exists but its key is missing, startup refuses to invent a replacement. Preserve the entire data volume.
- Owner authorization covers `/adminpanel`, `/backup`, `/restore`, `/import`, every admin/content callback, and every owner FSM reply. Group chats are refused.
- Research previews and paid deliveries explicitly use `protect_content=True`. Encrypted downloadable backups deliberately use `False`, because the file is protected by its password and must be savable.
- Content is decrypted only for a checked entitlement or an authenticated owner's preview/export. Python cannot guarantee secure memory erasure. Disable debug request logging and core dumps on the host.
- Telegram content protection is not absolute anti-piracy. External cameras, transcription and some capture techniques cannot be prevented.
- Deletion jobs survive restarts, but Telegram/API outages and deletion time limits can prevent deletion. Monitor overdue jobs. A crash between Telegram accepting a send and the database recording its message ID can still produce a duplicate or untracked message; no cross-system transaction exists.
- Backup/restore supports up to 100 services, 1,000 entries and 2 MB of content per export/import. A single entry supports 100 KB through `.txt`. Manage larger collections in smaller groups or extend limits after memory/load testing.
- Protect the host: a stolen database plus its master key exposes the vault. Restrict disk/backups, protect the owner account with two-step verification and never share bot credentials.

## Operations

- One polling instance; no webhook URL, DB URL or Redis server required.
- `data/research.sqlite3` stores durable FSM, users, entitlements and jobs. SQLite runs in WAL mode with `synchronous=FULL`, foreign keys, and serialized `BEGIN IMMEDIATE` write transactions.
- Review `payment_receipts.status='reconcile'` for unmatched money; it never automatically grants access.
- Failed refunds remain `Refunding` and can be retried. Refund revokes all access to that service for the payer; restore other valid grants manually when needed. Off-bot refunds/chargebacks require reconciliation.
- Failed content sends retry with backoff. Blocked users/jobs stay inspectable. Rejected payment notifications may fail if the buyer blocked the bot; their profile still shows status.
- Content and manual UPI input states expire after an hour; order payment deadlines are 30 minutes. Restarting does not clear these states immediately.
- Keep polling downtime short; Telegram does not retain pending updates indefinitely.
- The initial uploaded `encrypted_research_bot.zip` is retained as a legacy archive. **Run the root source files in this repository**, which now use SQLite; the archive contains the older PostgreSQL version.
- There is no automatic migration from a previously deployed PostgreSQL database. Export/validate that deployment before adopting a fresh SQLite install.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The suite runs real temporary SQLite databases; no database service or secret is required. It verifies restart persistence, transactions/concurrent approvals, expiry/revocation, receipt replay, draft exclusion, editing/publishing/deletion, backup encryption/tampering/import, full snapshots/recovery, owner guards, FSM persistence and protected delivery. GitHub Actions runs it on pushes and pull requests.

Live Telegram payments and Docker/host deployment require your real credentials/environment and were not exercised by the offline suite. The repository is configured and tested locally; it is not a running hosted bot until you deploy it.

## Project map

- `main.py`: lifecycle, owner guard, process lock and workers.
- `bot/sqlite.py`, `schema.sql`, `bot/storage.py`: local database, atomic transactions and persistent FSM.
- `bot/content.py`, `bot/backup.py`, `bot/system_backup.py`: content editor and encrypted backups.
- `bot/admin.py`, `bot/user.py`: admin/user purchase workflows.
- `bot/crypto.py`, `bot/db.py`, `bot/polling.py`, `bot/workers.py`: encryption, grants, receipt persistence, durable delivery/deletion.
- `restore_system.py`: offline full-system restore.
- `.env.example`, `Dockerfile`, `compose.yaml`: startup configuration.

Technical references: https://www.sqlite.org/backup.html and https://docs.aiogram.dev/en/latest/dispatcher/finite_state_machine/storages.html
