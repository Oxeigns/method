"""Parameterized SQL, SQLite transactions and atomic grants keep payment decisions idempotent."""
import uuid

class Store:
    def __init__(self, pool):
        self.pool = pool

    async def setting(self, key):
        return await self.pool.fetchval('SELECT setting_value FROM admin_settings WHERE setting_key=$1', key) or ''

    async def set_setting(self, key, value):
        await self.pool.execute('INSERT INTO admin_settings VALUES($1,$2) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value', key, value)

    async def user(self, u):
        await self.pool.execute('''INSERT INTO users(user_id,username,full_name) VALUES($1,$2,$3)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,full_name=excluded.full_name''', u.id, u.username, u.full_name)
        return await self.pool.fetchrow('SELECT * FROM users WHERE user_id=$1', u.id)

    async def audit(self, actor, action, target):
        await self.pool.execute('INSERT INTO audit_log(actor_id,action,target) VALUES($1,$2,$3)', actor, action, str(target))

    async def allowed(self, uid, sid):
        return await self.pool.fetchval('''SELECT EXISTS(SELECT 1 FROM entitlements e
        JOIN users u USING(user_id) JOIN services s USING(service_id)
        WHERE e.user_id=$1 AND e.service_id=$2 AND u.is_banned=0 AND e.revoked=0
        AND s.is_active=1 AND (e.expires_at IS NULL OR e.expires_at>now()))''', uid, sid)

    async def order(self, uid, sid, currency, terms_version):
        async with self.pool.acquire() as c, c.transaction():
            # Serialize purchases by a user; cancel only abandoned orders without evidence.
            u = await c.fetchrow('SELECT * FROM users WHERE user_id=$1'+(' FOR UPDATE' if getattr(c,'dialect','sqlite')=='postgres' else ''), uid)
            s = await c.fetchrow('SELECT * FROM services WHERE service_id=$1 AND is_active=1', sid)
            if not u or u['is_banned'] or not s:
                raise ValueError('Service unavailable.')
            if not await c.fetchval('SELECT EXISTS(SELECT 1 FROM vault_data WHERE service_id=$1 AND is_published=1)', sid):
                raise ValueError('This service has no published research yet.')
            current_terms = await c.fetchval("SELECT setting_value FROM admin_settings WHERE setting_key='terms_version'")
            if current_terms != terms_version:
                raise ValueError('Terms changed. Open this service again.')
            amount = s['stars_price'] if currency == 'XTR' else s['price']
            if not amount:
                raise ValueError('The owner has not configured a Stars price yet.')
            await c.execute("UPDATE transactions SET status='Cancelled' WHERE user_id=$1 AND status='Pending' AND screenshot_file_id IS NULL", uid)
            tid = uuid.uuid4()
            await c.execute('''INSERT INTO transactions(txn_id,user_id,service_id,amount,currency,validity_days,terms_version)
            VALUES($1,$2,$3,$4,$5,$6,$7)''', tid,uid,sid,amount,currency,s['validity_days'],terms_version)
            return tid, s, amount

    async def screenshot(self, uid, tid, file_id):
        return await self.pool.fetchval('''UPDATE transactions SET screenshot_file_id=$3
        WHERE txn_id=$1 AND user_id=$2 AND status='Pending' AND currency='INR'
        AND expires_at>now() AND screenshot_file_id IS NULL RETURNING txn_id''', tid,uid,file_id)

    async def cancel(self, uid):
        await self.pool.execute("UPDATE transactions SET status='Cancelled' WHERE user_id=$1 AND status='Pending' AND screenshot_file_id IS NULL",uid)

    async def _grant(self, c, t):
        # Null expiry means lifetime access. Renewal extends the later of now/expiry.
        await c.execute('''INSERT INTO entitlements(user_id,service_id,expires_at)
        VALUES($1,$2,CASE WHEN $3=0 THEN NULL ELSE now()+86400*$3 END)
        ON CONFLICT(user_id,service_id) DO UPDATE SET revoked=0, expires_at=
        CASE WHEN $3=0 OR (entitlements.expires_at IS NULL AND entitlements.revoked=0) THEN NULL
        ELSE max(now(),CASE WHEN entitlements.revoked=1 THEN now() ELSE entitlements.expires_at END)+86400*$3 END''',t['user_id'],t['service_id'],t['validity_days'])
        await c.execute('INSERT INTO delivery_jobs(user_id,service_id,txn_id) VALUES($1,$2,$3) ON CONFLICT(txn_id) DO NOTHING',t['user_id'],t['service_id'],t['txn_id'])

    async def review(self, tid, approve, admin_id):
        async with self.pool.acquire() as c, c.transaction():
            t = await c.fetchrow('SELECT * FROM transactions WHERE txn_id=$1'+(' FOR UPDATE' if getattr(c,'dialect','sqlite')=='postgres' else ''), tid)
            if not t or t['status'] != 'Pending' or t['currency'] != 'INR' or not t['screenshot_file_id']:
                return None
            if approve and await c.fetchval('SELECT is_banned FROM users WHERE user_id=$1',t['user_id']):
                raise ValueError('User is banned. Resolve the payment before approval.')
            if approve and not await c.fetchval('''SELECT EXISTS(SELECT 1 FROM services s JOIN vault_data v USING(service_id) WHERE s.service_id=$1 AND s.is_active=1 AND v.is_published=1)''',t['service_id']):
                raise ValueError('Service is unavailable. Restore it or reject and arrange repayment.')
            await c.execute('UPDATE transactions SET status=$2,reviewed_by=$3,reviewed_at=now() WHERE txn_id=$1',tid,'Approved' if approve else 'Rejected',admin_id)
            if approve:
                await self._grant(c,t)
            await c.execute('INSERT INTO audit_log(actor_id,action,target) VALUES($1,$2,$3)',admin_id,'approve' if approve else 'reject',str(tid))
            return t

    async def precheckout(self, uid, tid, currency, amount):
        return await self.pool.fetchval('''SELECT EXISTS(SELECT 1 FROM transactions t
        JOIN users u USING(user_id) JOIN services s USING(service_id)
        WHERE t.txn_id=$1 AND t.user_id=$2 AND t.currency=$3 AND t.amount=$4
        AND t.status='Pending' AND t.expires_at>now() AND u.is_banned=0 AND s.is_active=1
        AND EXISTS(SELECT 1 FROM vault_data v WHERE v.service_id=t.service_id AND v.is_published=1))''',tid,uid,currency,amount)

    async def paid(self, uid, tid, currency, amount, charge):
        async with self.pool.acquire() as c, c.transaction():
            t = await c.fetchrow('SELECT * FROM transactions WHERE txn_id=$1'+(' FOR UPDATE' if getattr(c,'dialect','sqlite')=='postgres' else ''),tid)
            if not t or t['user_id'] != uid or currency != 'XTR' or t['currency'] != currency or t['amount'] != amount:
                raise ValueError('Payment reconciliation required; contact /paysupport.')
            if t['telegram_charge_id'] == charge:
                return False
            if t['telegram_charge_id']:
                raise ValueError('Duplicate charge requires owner reconciliation.')
            # A late success can arrive after cancellation/expiry; record actual payment.
            await c.execute("UPDATE transactions SET status='Approved',telegram_charge_id=$2,reviewed_at=now() WHERE txn_id=$1",tid,charge)
            await self._grant(c,t)
            return True

    async def request_delivery(self, uid, sid):
        if not await self.allowed(uid,sid):
            raise ValueError('No active access. Purchase the service or contact support.')
        # A write transaction serializes repeated delivery requests.
        async with self.pool.acquire() as c, c.transaction():
            if getattr(c,'dialect','sqlite')=='postgres':
                await c.fetchrow('SELECT user_id FROM users WHERE user_id=$1 FOR UPDATE',uid)
            exists = await c.fetchval("SELECT EXISTS(SELECT 1 FROM delivery_jobs WHERE user_id=$1 AND service_id=$2 AND status='pending')",uid,sid)
            if not exists:
                await c.execute('INSERT INTO delivery_jobs(user_id,service_id) VALUES($1,$2)',uid,sid)
