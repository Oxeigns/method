import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from bot.sqlite import SQLite
from bot.db import Store
from bot.crypto import VaultCipher
from backend.broadcast import prepare,claim,process
from backend.http import RateLimited,RecipientUnavailable

@pytest_asyncio.fixture
async def queue(tmp_path):
    db=await SQLite.open(tmp_path/'q.sqlite3');store=Store(db);cipher=VaultCipher([Fernet.generate_key().decode()])
    for uid in range(1,5):await store.user(SimpleNamespace(id=uid,username=None,full_name='Test'))
    await db.execute('UPDATE users SET is_banned=1 WHERE user_id=4')
    await db.execute('INSERT INTO broadcasts(encrypted_text) VALUES($1)',cipher.encrypt(0,'Private announcement'))
    await prepare(store)
    yield store,cipher
    await db.close()

@pytest.mark.asyncio
async def test_concurrent_claims_are_unique_and_skip_banned(queue):
    store,_=queue
    targets=await asyncio.gather(*[claim(store) for _ in range(4)])
    ids=[t['target_id'] for t in targets if t]
    assert len(ids)==3 and len(set(ids))==3

@pytest.mark.asyncio
async def test_success_and_floodwait_persist(queue):
    store,cipher=queue
    sender=SimpleNamespace(send=AsyncMock());pacer=SimpleNamespace(pause=lambda _:None)
    target=await claim(store);await process(store,cipher,sender,pacer,target)
    assert await store.pool.fetchval('SELECT status FROM broadcast_targets WHERE target_id=$1',target['target_id'])=='sent'
    sender.send=AsyncMock(side_effect=RateLimited(60))
    target=await claim(store);await process(store,cipher,sender,pacer,target)
    assert await store.pool.fetchval('SELECT status FROM broadcast_targets WHERE target_id=$1',target['target_id'])=='queued'
    next_target=await claim(store)
    assert next_target['target_id']!=target['target_id']

@pytest.mark.asyncio
async def test_expired_lease_recovered_and_new_ban_respected(queue):
    store,cipher=queue;target=await claim(store)
    await store.pool.execute('UPDATE broadcast_targets SET lease_until=now()-1 WHERE target_id=$1',target['target_id'])
    recovered=await claim(store)
    assert recovered['target_id']==target['target_id'] and recovered['lease_token']!=target['lease_token']
    await store.pool.execute('UPDATE users SET is_banned=1 WHERE user_id=$1',recovered['user_id'])
    sender=SimpleNamespace(send=AsyncMock());pacer=SimpleNamespace(pause=lambda _:None)
    await process(store,cipher,sender,pacer,recovered)
    sender.send.assert_not_awaited()
    assert await store.pool.fetchval('SELECT status FROM broadcast_targets WHERE target_id=$1',recovered['target_id'])=='failed'
