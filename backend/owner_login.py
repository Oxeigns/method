"""Short-lived owner login codes. Only a digest is stored, consumed exactly once."""
import hashlib
import hmac
import json
import secrets
import time

async def issue(store):
    code=secrets.token_urlsafe(24)
    await store.set_setting('dashboard_login',json.dumps({'digest':hashlib.sha256(code.encode()).hexdigest(),'expires':time.time()+300}))
    return code

async def consume(db,code):
    async with db.acquire() as c,c.transaction():
        suffix=' FOR UPDATE' if getattr(c,'dialect','sqlite')=='postgres' else ''
        raw=await c.fetchval("SELECT setting_value FROM admin_settings WHERE setting_key='dashboard_login'"+suffix)
        if not raw:return False
        data=json.loads(raw)
        if data['expires']<=time.time() or not hmac.compare_digest(data['digest'],hashlib.sha256(code.encode()).hexdigest()):return False
        await c.execute("DELETE FROM admin_settings WHERE setting_key='dashboard_login'")
        return True
