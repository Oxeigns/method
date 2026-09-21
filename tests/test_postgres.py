"""CI uses a disposable PostgreSQL service; never point TEST_DATABASE_URL at real data."""
import os,asyncio,uuid
from pathlib import Path
from types import SimpleNamespace
import pytest
from cryptography.fernet import Fernet
from backend.database import Postgres
from bot.db import Store
from bot.crypto import VaultCipher

@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'),reason='PostgreSQL integration runs in CI service')
async def test_postgres_payment_queue_and_api_contract():
    import asyncpg
    url=os.environ['TEST_DATABASE_URL']
    c=await asyncpg.connect(url)
    await c.execute(Path('migrations/001_postgres.sql').read_text());await c.close()
    db=await Postgres.open(SimpleNamespace(database_url=url,production=False,pool_max=5));store=Store(db)
    cipher=VaultCipher([Fernet.generate_key().decode()]);uid=uuid.uuid4().int%10**12
    try:
        await store.user(SimpleNamespace(id=uid,username='ci',full_name='CI User'))
        await db.execute('UPDATE services SET stars_price=100 WHERE service_id=1')
        await db.execute('INSERT INTO vault_data(service_id,title,encrypted_payload,is_published) VALUES(1,$1,$2,1)','CI reference',cipher.encrypt(1,'Synthetic test content'))
        tid,_,_=await store.order(uid,1,'INR','1');await store.screenshot(uid,tid,'photo')
        result=await asyncio.gather(store.review(tid,True,99),store.review(tid,True,99))
        assert sum(r is not None for r in result)==1
        assert await store.allowed(uid,1)
        tid,_,_=await store.order(uid,1,'XTR','1')
        assert await store.precheckout(uid,tid,'XTR',100)
        assert await store.paid(uid,tid,'XTR',100,str(tid))
        assert not await store.paid(uid,tid,'XTR',100,str(tid))
        from backend.broadcast import prepare,claim
        await db.execute('INSERT INTO broadcasts(encrypted_text) VALUES($1)',cipher.encrypt(0,'CI announcement'))
        await prepare(store);assert await claim(store)
    finally:await db.close()
