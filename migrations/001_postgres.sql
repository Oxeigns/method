BEGIN;
CREATE SCHEMA IF NOT EXISTS method;
REVOKE ALL ON SCHEMA method FROM PUBLIC;
SET search_path=method,pg_catalog;
CREATE TABLE IF NOT EXISTS users (
 user_id BIGINT PRIMARY KEY, username TEXT, full_name TEXT NOT NULL,
 join_date DOUBLE PRECISION NOT NULL DEFAULT (extract(epoch from now())), is_banned BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS services (
 service_id BIGSERIAL PRIMARY KEY, service_name TEXT NOT NULL,
 price NUMERIC(12,2) NOT NULL CHECK(price>0), stars_price BIGINT CHECK(stars_price BETWEEN 1 AND 100000),
 description TEXT NOT NULL, is_active BIGINT NOT NULL DEFAULT 1,
 validity_days BIGINT NOT NULL DEFAULT 0 CHECK(validity_days BETWEEN 0 AND 3650),
 delete_after_seconds BIGINT NOT NULL DEFAULT 86400 CHECK(delete_after_seconds BETWEEN 60 AND 86400)
);
CREATE TABLE IF NOT EXISTS transactions (
 txn_id TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users,
 service_id BIGINT NOT NULL REFERENCES services, amount NUMERIC(12,2) NOT NULL CHECK(amount>0),
 currency TEXT NOT NULL CHECK(currency IN ('INR','XTR')),
 status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Approved','Rejected','Cancelled','Refunding','Refunded')),
 screenshot_file_id TEXT, timestamp DOUBLE PRECISION NOT NULL DEFAULT (extract(epoch from now())),
 expires_at DOUBLE PRECISION NOT NULL DEFAULT (extract(epoch from now())+1800), validity_days BIGINT NOT NULL CHECK(validity_days BETWEEN 0 AND 3650),
 terms_version TEXT NOT NULL, reviewed_by BIGINT, reviewed_at DOUBLE PRECISION,
 telegram_charge_id TEXT UNIQUE, admin_notified BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS txn_queue ON transactions(timestamp) WHERE status='Pending';
CREATE INDEX IF NOT EXISTS txn_user ON transactions(user_id,timestamp DESC);
CREATE TABLE IF NOT EXISTS vault_data (
 data_id BIGSERIAL PRIMARY KEY, service_id BIGINT NOT NULL REFERENCES services,
 title TEXT NOT NULL DEFAULT 'Untitled reference', encrypted_payload TEXT NOT NULL,
 is_published BIGINT NOT NULL DEFAULT 0,
 encryption_iv TEXT CHECK(encryption_iv IS NULL), created_at DOUBLE PRECISION NOT NULL DEFAULT (extract(epoch from now()))
);
CREATE INDEX IF NOT EXISTS vault_service ON vault_data(service_id,data_id);
CREATE TABLE IF NOT EXISTS admin_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entitlements (
 user_id BIGINT NOT NULL REFERENCES users, service_id BIGINT NOT NULL REFERENCES services,
 expires_at DOUBLE PRECISION, revoked BIGINT NOT NULL DEFAULT 0, PRIMARY KEY(user_id,service_id)
);
CREATE TABLE IF NOT EXISTS delivery_jobs (
 job_id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users,
 service_id BIGINT NOT NULL REFERENCES services, txn_id TEXT UNIQUE REFERENCES transactions,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done','blocked')),
 next_attempt DOUBLE PRECISION NOT NULL DEFAULT (extract(epoch from now())), attempts BIGINT NOT NULL DEFAULT 0,
 data_cursor BIGINT NOT NULL DEFAULT 0, chunk_cursor BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS delivery_due ON delivery_jobs(next_attempt) WHERE status='pending';
CREATE TABLE IF NOT EXISTS deletion_jobs (
 chat_id BIGINT NOT NULL, message_id BIGINT NOT NULL, due_at DOUBLE PRECISION NOT NULL,
 attempts BIGINT NOT NULL DEFAULT 0, PRIMARY KEY(chat_id,message_id)
);
CREATE TABLE IF NOT EXISTS payment_receipts (
 charge_id TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users,
 invoice_payload TEXT NOT NULL, currency TEXT NOT NULL, amount BIGINT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processed','reconcile')),
 created_at DOUBLE PRECISION NOT NULL DEFAULT (extract(epoch from now()))
);
CREATE TABLE IF NOT EXISTS audit_log (
 id BIGSERIAL PRIMARY KEY, actor_id BIGINT NOT NULL,
 action TEXT NOT NULL, target TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL DEFAULT (extract(epoch from now()))
);
CREATE TABLE IF NOT EXISTS broadcasts (
 broadcast_id BIGSERIAL PRIMARY KEY, encrypted_text TEXT NOT NULL,
 cursor_user_id BIGINT NOT NULL DEFAULT 0, done BIGINT NOT NULL DEFAULT 0,
 created_at DOUBLE PRECISION NOT NULL DEFAULT (extract(epoch from now()))
);
CREATE TABLE IF NOT EXISTS fsm (
 storage_key TEXT PRIMARY KEY,state TEXT,data TEXT NOT NULL DEFAULT '{}',
 updated_at DOUBLE PRECISION NOT NULL DEFAULT (extract(epoch from now()))
);
INSERT INTO services(service_id,service_name,price,description) VALUES
 (1,'Specific Reporting Method',1500,'One selected reporting reference and its evidence checklist.'),
 (2,'Account Limit Removal Guide',300,'Legitimate account-limit review and appeal references.'),
 (3,'Channel Unban Procedure/Format',1500,'Channel appeal procedures and correspondence references.'),
 (4,'Group Ban Procedure/Format',2000,'Evidence-based reporting references for policy-violating groups.'),
 (5,'Local Laws & Compliance Frameworks',15000,'Owner-provided legal and intermediary compliance research.') ON CONFLICT DO NOTHING;
INSERT INTO admin_settings VALUES
 ('upi_id',''),('support_username',''),('terms_version','1'),
 ('terms','Personal access to owner-provided research. No guaranteed enforcement or appeal outcome. No redistribution. Contact support for billing or access issues. Access duration is shown before purchase.') ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS content_imports (digest TEXT PRIMARY KEY, imported_at DOUBLE PRECISION NOT NULL DEFAULT (extract(epoch from now())));
CREATE TABLE IF NOT EXISTS login_limits (bucket TEXT PRIMARY KEY, attempts BIGINT NOT NULL, reset_at DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS web_sessions (session_id TEXT PRIMARY KEY, expires_at DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS broadcast_targets (
 target_id BIGSERIAL PRIMARY KEY,broadcast_id BIGINT NOT NULL REFERENCES broadcasts,
 user_id BIGINT NOT NULL REFERENCES users,status TEXT NOT NULL DEFAULT 'queued',
 available_at DOUBLE PRECISION NOT NULL DEFAULT (extract(epoch from now())),lease_until DOUBLE PRECISION,lease_token TEXT,
 attempts BIGINT NOT NULL DEFAULT 0,last_error TEXT,
 UNIQUE(broadcast_id,user_id)
);
CREATE INDEX IF NOT EXISTS target_due ON broadcast_targets(status,available_at);

ALTER TABLE services ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1;
ALTER TABLE vault_data ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1;
SELECT setval(pg_get_serial_sequence('method.services','service_id'),(SELECT max(service_id) FROM services));
DO $$ DECLARE t RECORD; BEGIN
FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='method' LOOP
EXECUTE format('ALTER TABLE method.%I ENABLE ROW LEVEL SECURITY',t.tablename);
END LOOP; END $$;
ALTER TABLE broadcasts ADD COLUMN IF NOT EXISTS prepared BIGINT NOT NULL DEFAULT 0;
COMMIT;
