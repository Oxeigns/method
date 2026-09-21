PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT NOT NULL,
 join_date REAL NOT NULL DEFAULT (unixepoch()), is_banned INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS services (
 service_id INTEGER PRIMARY KEY AUTOINCREMENT, service_name TEXT NOT NULL,
 price NUMERIC NOT NULL CHECK(price>0), stars_price INTEGER CHECK(stars_price BETWEEN 1 AND 100000),
 description TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
 validity_days INTEGER NOT NULL DEFAULT 0 CHECK(validity_days BETWEEN 0 AND 3650),
 delete_after_seconds INTEGER NOT NULL DEFAULT 86400 CHECK(delete_after_seconds BETWEEN 60 AND 86400)
);
CREATE TABLE IF NOT EXISTS transactions (
 txn_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users,
 service_id INTEGER NOT NULL REFERENCES services, amount NUMERIC NOT NULL CHECK(amount>0),
 currency TEXT NOT NULL CHECK(currency IN ('INR','XTR')),
 status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Approved','Rejected','Cancelled','Refunding','Refunded')),
 screenshot_file_id TEXT, timestamp REAL NOT NULL DEFAULT (unixepoch()),
 expires_at REAL NOT NULL DEFAULT (unixepoch()+1800), validity_days INTEGER NOT NULL CHECK(validity_days BETWEEN 0 AND 3650),
 terms_version TEXT NOT NULL, reviewed_by INTEGER, reviewed_at REAL,
 telegram_charge_id TEXT UNIQUE, admin_notified INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS txn_queue ON transactions(timestamp) WHERE status='Pending';
CREATE INDEX IF NOT EXISTS txn_user ON transactions(user_id,timestamp DESC);
CREATE TABLE IF NOT EXISTS vault_data (
 data_id INTEGER PRIMARY KEY AUTOINCREMENT, service_id INTEGER NOT NULL REFERENCES services,
 title TEXT NOT NULL DEFAULT 'Untitled reference', encrypted_payload TEXT NOT NULL,
 is_published INTEGER NOT NULL DEFAULT 0,
 encryption_iv TEXT CHECK(encryption_iv IS NULL), created_at REAL NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS vault_service ON vault_data(service_id,data_id);
CREATE TABLE IF NOT EXISTS admin_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entitlements (
 user_id INTEGER NOT NULL REFERENCES users, service_id INTEGER NOT NULL REFERENCES services,
 expires_at REAL, revoked INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,service_id)
);
CREATE TABLE IF NOT EXISTS delivery_jobs (
 job_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users,
 service_id INTEGER NOT NULL REFERENCES services, txn_id TEXT UNIQUE REFERENCES transactions,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done','blocked')),
 next_attempt REAL NOT NULL DEFAULT (unixepoch()), attempts INTEGER NOT NULL DEFAULT 0,
 data_cursor INTEGER NOT NULL DEFAULT 0, chunk_cursor INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS delivery_due ON delivery_jobs(next_attempt) WHERE status='pending';
CREATE TABLE IF NOT EXISTS deletion_jobs (
 chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, due_at REAL NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(chat_id,message_id)
);
CREATE TABLE IF NOT EXISTS payment_receipts (
 charge_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users,
 invoice_payload TEXT NOT NULL, currency TEXT NOT NULL, amount INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processed','reconcile')),
 created_at REAL NOT NULL DEFAULT (unixepoch())
);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER NOT NULL,
 action TEXT NOT NULL, target TEXT NOT NULL, created_at REAL NOT NULL DEFAULT (unixepoch())
);
CREATE TABLE IF NOT EXISTS broadcasts (
 broadcast_id INTEGER PRIMARY KEY AUTOINCREMENT, encrypted_text TEXT NOT NULL,
 cursor_user_id INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL DEFAULT (unixepoch())
);
CREATE TABLE IF NOT EXISTS fsm (
 storage_key TEXT PRIMARY KEY,state TEXT,data TEXT NOT NULL DEFAULT '{}',
 updated_at REAL NOT NULL DEFAULT (unixepoch())
);
INSERT OR IGNORE INTO services(service_id,service_name,price,description) VALUES
 (1,'Specific Reporting Method',1500,'One selected reporting reference and its evidence checklist.'),
 (2,'Account Limit Removal Guide',300,'Legitimate account-limit review and appeal references.'),
 (3,'Channel Unban Procedure/Format',1500,'Channel appeal procedures and correspondence references.'),
 (4,'Group Ban Procedure/Format',2000,'Evidence-based reporting references for policy-violating groups.'),
 (5,'Local Laws & Compliance Frameworks',15000,'Owner-provided legal and intermediary compliance research.');
INSERT OR IGNORE INTO admin_settings VALUES
 ('upi_id',''),('support_username',''),('terms_version','1'),
 ('terms','Personal access to owner-provided research. No guaranteed enforcement or appeal outcome. No redistribution. Contact support for billing or access issues. Access duration is shown before purchase.');
PRAGMA user_version=1;
CREATE TABLE IF NOT EXISTS content_imports (digest TEXT PRIMARY KEY, imported_at REAL NOT NULL DEFAULT (unixepoch()));
