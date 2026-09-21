"""Real SQLite integration tests: no server, credentials, or skipped database tests."""
import asyncio
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from bot.sqlite import SQLite
from bot.db import Store
from bot.crypto import VaultCipher
from bot.backup import export_content,import_content,seal,unseal

@pytest_asyncio.fixture
async def db(tmp_path):
    pool=await SQLite.open(tmp_path/'research.sqlite3')
    store=Store(pool)
    cipher=VaultCipher([Fernet.generate_key().decode()])
    await store.user(SimpleNamespace(id=42,username='tester',full_name='Test'))
    await pool.execute('UPDATE services SET stars_price=100 WHERE service_id=1')
    await pool.execute('INSERT INTO vault_data(service_id,title,encrypted_payload,is_published) VALUES(1,$1,$2,1)','Reference',cipher.encrypt(1,'SECRET-REFERENCE'))
    yield store,cipher
    await pool.close()

@pytest.mark.asyncio
async def test_simultaneous_manual_approval_and_idempotency(db):
    store,cipher=db
    tid,_,_=await store.order(42,1,'INR','1')
    assert await store.screenshot(42,tid,'photo')
    result=await asyncio.gather(store.review(tid,True,99),store.review(tid,True,99))
    assert sum(r is not None for r in result)==1
    assert await store.allowed(42,1)
    assert await store.pool.fetchval('SELECT count(*) FROM delivery_jobs WHERE txn_id=$1',tid)==1

@pytest.mark.asyncio
async def test_receipt_mismatch_replay_and_late_success(db):
    store,_=db
    tid,_,_=await store.order(42,1,'XTR','1')
    assert await store.precheckout(42,tid,'XTR',100)
    assert not await store.precheckout(42,tid,'XTR',99)
    assert not await store.precheckout(43,tid,'XTR',100)
    with pytest.raises(ValueError):await store.paid(42,tid,'XTR',99,'charge')
    await store.cancel(42)
    assert await store.paid(42,tid,'XTR',100,'charge')
    assert not await store.paid(42,tid,'XTR',100,'charge')
    assert await store.pool.fetchval('SELECT count(*) FROM delivery_jobs WHERE txn_id=$1',tid)==1

@pytest.mark.asyncio
async def test_ban_expiry_revocation_and_renewal(db):
    store,_=db
    await store.pool.execute('UPDATE services SET validity_days=30 WHERE service_id=1')
    tid,_,_=await store.order(42,1,'XTR','1')
    await store.paid(42,tid,'XTR',100,'charge1')
    expiry=await store.pool.fetchval('SELECT expires_at FROM entitlements WHERE user_id=42')
    assert expiry>datetime.now(timezone.utc)+timedelta(days=29)
    tid,_,_=await store.order(42,1,'XTR','1')
    await store.paid(42,tid,'XTR',100,'charge2')
    assert await store.pool.fetchval('SELECT expires_at FROM entitlements WHERE user_id=42')==expiry+timedelta(days=30)
    await store.pool.execute('UPDATE users SET is_banned=1 WHERE user_id=42')
    assert not await store.allowed(42,1)
    await store.pool.execute('UPDATE users SET is_banned=0 WHERE user_id=42')
    await store.pool.execute('UPDATE entitlements SET revoked=1 WHERE user_id=42')
    assert not await store.allowed(42,1)
    await store.pool.execute('UPDATE entitlements SET revoked=0,expires_at=now()-1 WHERE user_id=42')
    assert not await store.allowed(42,1)

@pytest.mark.asyncio
async def test_screenshot_cancel_expire_duplicate(db):
    store,_=db
    tid,_,_=await store.order(42,1,'INR','1')
    await store.cancel(42)
    assert not await store.screenshot(42,tid,'photo')
    tid,_,_=await store.order(42,1,'INR','1')
    await store.pool.execute('UPDATE transactions SET expires_at=now()-1 WHERE txn_id=$1',tid)
    assert not await store.screenshot(42,tid,'photo')
    tid,_,_=await store.order(42,1,'INR','1')
    assert await store.screenshot(42,tid,'photo')
    assert not await store.screenshot(42,tid,'photo2')

@pytest.mark.asyncio
async def test_real_transaction_rolls_back_and_serializes(db):
    store,_=db
    with pytest.raises(RuntimeError):
        async with store.pool.acquire() as c,c.transaction():
            await c.execute('UPDATE services SET price=1 WHERE service_id=1')
            raise RuntimeError('rollback')
    assert await store.pool.fetchval('SELECT price FROM services WHERE service_id=1')==1500
    async def increment():
        async with store.pool.acquire() as c,c.transaction():
            price=await c.fetchval('SELECT price FROM services WHERE service_id=1')
            await asyncio.sleep(0.001)
            await c.execute('UPDATE services SET price=$1 WHERE service_id=1',price+1)
    await asyncio.gather(*[increment() for _ in range(10)])
    assert await store.pool.fetchval('SELECT price FROM services WHERE service_id=1')==1510

@pytest.mark.asyncio
async def test_backup_roundtrip_into_drafts_preserves_prices_and_existing_data(db):
    store,cipher=db
    bundle=await export_content(store,cipher)
    blob=seal(bundle,'long-private-password-123')
    assert b'SECRET-REFERENCE' not in blob
    with pytest.raises(ValueError):unseal(blob,'wrong-private-password-123')
    restored=unseal(blob,'long-private-password-123')
    ids=await import_content(store,cipher,restored,99)
    assert len(ids)==5
    assert await store.pool.fetchval('SELECT price FROM services WHERE service_id=$1',ids[0])==1500
    assert await store.pool.fetchval('SELECT is_active FROM services WHERE service_id=$1',ids[0])==0
    row=await store.pool.fetchrow('SELECT * FROM vault_data WHERE service_id=$1',ids[0])
    assert not row['is_published']
    assert cipher.decrypt(ids[0],row['encrypted_payload'])=='SECRET-REFERENCE'
    assert await store.pool.fetchval('SELECT count(*) FROM vault_data WHERE service_id=1')==1
    with pytest.raises(ValueError):await import_content(store,cipher,restored,99)

@pytest.mark.asyncio
async def test_draft_only_services_cannot_sell(db):
    store,_=db
    await store.pool.execute('UPDATE vault_data SET is_published=0')
    with pytest.raises(ValueError):await store.order(42,1,'XTR','1')

@pytest.mark.asyncio
async def test_reopen_database_retains_price_content_and_fsm(tmp_path):
    from aiogram.fsm.storage.base import StorageKey
    from bot.storage import SQLiteStorage
    from bot.states import Owner
    path=tmp_path/'restart.sqlite3'
    pool=await SQLite.open(path)
    await pool.execute('UPDATE services SET price=987 WHERE service_id=1')
    fs=SQLiteStorage(pool);key=StorageKey(bot_id=1,chat_id=99,user_id=99)
    await fs.set_state(key,Owner.content_text);await fs.set_data(key,{'sid':1,'title':'A'})
    await pool.close()
    pool=await SQLite.open(path);fs=SQLiteStorage(pool)
    assert await pool.fetchval('SELECT price FROM services WHERE service_id=1')==987
    assert await fs.get_state(key)==Owner.content_text.state
    assert await fs.get_data(key)=={'sid':1,'title':'A'}
    await pool.close()

@pytest.mark.asyncio
async def test_snapshot_contains_committed_wal_data(db,tmp_path):
    import sqlite3
    store,_=db
    await store.pool.execute('UPDATE services SET price=4321 WHERE service_id=1')
    target=tmp_path/'snapshot.sqlite3'
    await store.pool.snapshot(target)
    with sqlite3.connect(target) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT price FROM services WHERE service_id=1').fetchone()[0]==4321

@pytest.mark.asyncio
async def test_parameter_order_and_foreign_keys(db):
    store,_=db
    assert await store.pool.fetchval('SELECT $2 || $1','A','B')=='BA'
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        await store.pool.execute('INSERT INTO vault_data(service_id,encrypted_payload) VALUES(99999,$1)','x')

@pytest.mark.asyncio
async def test_system_snapshot_and_offline_restore(db,tmp_path):
    from bot.system_backup import snapshot
    from restore_system import restore
    store,cipher=db
    # Use a known key for both the vault and full backup in this independent fixture.
    key=Fernet.generate_key().decode();cipher=VaultCipher([key])
    await store.pool.execute('UPDATE vault_data SET encrypted_payload=$1',cipher.encrypt(1,'RECOVERABLE'))
    bid=await store.pool.fetchval('INSERT INTO broadcasts(encrypted_text) VALUES($1) RETURNING broadcast_id',cipher.encrypt(0,'old announcement'))
    await store.pool.execute('INSERT INTO broadcast_targets(broadcast_id,user_id) VALUES($1,42)',bid)
    await store.pool.execute("INSERT INTO web_sessions VALUES('old-session',9999999999)")
    source=await snapshot(store,cipher,tmp_path/'backups')
    assert b'RECOVERABLE' not in source.read_bytes()
    keyfile=tmp_path/'saved.key';keyfile.write_text(key)
    target=tmp_path/'recovered'
    restore(source,keyfile,target)
    pool=await SQLite.open(target/'research.sqlite3')
    token=await pool.fetchval('SELECT encrypted_payload FROM vault_data WHERE service_id=1')
    assert cipher.decrypt(1,token)=='RECOVERABLE'
    assert await pool.fetchval('SELECT status FROM broadcast_targets')=='failed'
    assert await pool.fetchval('SELECT count(*) FROM web_sessions')==0
    await pool.close()
    with pytest.raises(ValueError):restore(source,keyfile,target)

@pytest.mark.asyncio
async def test_delivery_never_includes_draft(db):
    from unittest.mock import AsyncMock
    from bot.workers import deliver_one
    store,cipher=db
    await store.pool.execute('INSERT INTO vault_data(service_id,title,encrypted_payload) VALUES(1,$1,$2)','Unverified',cipher.encrypt(1,'DO-NOT-PUBLISH'))
    tid,_,_=await store.order(42,1,'XTR','1');await store.paid(42,tid,'XTR',100,'charge')
    job=await store.pool.fetchrow('SELECT * FROM delivery_jobs WHERE txn_id=$1',tid)
    bot=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)))
    await deliver_one(bot,store,cipher,job)
    sent=''.join(call.args[1] for call in bot.send_message.call_args_list)
    assert 'SECRET-REFERENCE' in sent and 'DO-NOT-PUBLISH' not in sent
    assert await store.pool.fetchval('SELECT count(*) FROM deletion_jobs')==1

@pytest.mark.asyncio
async def test_edit_handler_encrypts_and_unpublishes(db):
    from bot.content import edit
    from unittest.mock import AsyncMock
    store,cipher=db
    did=await store.pool.fetchval('SELECT data_id FROM vault_data LIMIT 1')
    state=SimpleNamespace(get_data=AsyncMock(return_value={'did':did}),clear=AsyncMock())
    m=SimpleNamespace(text='NEW-PRIVATE-TEXT',from_user=SimpleNamespace(id=99),delete=AsyncMock(),answer=AsyncMock())
    await edit(m,state,store,cipher,None)
    row=await store.pool.fetchrow('SELECT * FROM vault_data WHERE data_id=$1',did)
    assert not row['is_published'] and 'NEW-PRIVATE-TEXT' not in row['encrypted_payload']
    assert cipher.decrypt(1,row['encrypted_payload'])=='NEW-PRIVATE-TEXT'
    m.delete.assert_awaited_once()

@pytest.mark.asyncio
async def test_content_owner_publish_delete_handlers(db):
    from bot.content import action
    from unittest.mock import AsyncMock
    store,cipher=db
    did=await store.pool.fetchval('SELECT data_id FROM vault_data LIMIT 1')
    state=SimpleNamespace(clear=AsyncMock())
    q=SimpleNamespace(data=f'content:unpublish:{did}',answer=AsyncMock(),message=SimpleNamespace(answer=AsyncMock()),from_user=SimpleNamespace(id=99))
    await action(q,state,store,cipher)
    assert not await store.pool.fetchval('SELECT is_published FROM vault_data WHERE data_id=$1',did)
    q.data=f'content:publish:{did}';await action(q,state,store,cipher)
    assert await store.pool.fetchval('SELECT is_published FROM vault_data WHERE data_id=$1',did)
    q.data=f'content:delete_confirm:{did}';await action(q,state,store,cipher)
    assert not await store.pool.fetchrow('SELECT * FROM vault_data WHERE data_id=$1',did)
