import asyncio,json,time
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import pytest_asyncio
from bot.sqlite import SQLite
from bot.db import Store

@pytest_asyncio.fixture
async def db(tmp_path):
    pool=await SQLite.open(tmp_path/"test.sqlite3")
    yield Store(pool),None
    await pool.close()

from cryptography.fernet import Fernet
from config import Config
from backend.owner_login import issue,consume
from bot.admin import dashboard

@pytest.mark.asyncio
async def test_codes_are_one_use_expiring_and_replace_old_codes(db):
    store,_=db
    old=await issue(store);code=await issue(store)
    assert code not in await store.setting('dashboard_login')
    assert not await consume(store.pool,old)
    results=await asyncio.gather(consume(store.pool,code),consume(store.pool,code))
    assert sorted(results)==[False,True]
    code=await issue(store)
    data=json.loads(await store.setting('dashboard_login'));data['expires']=time.time()-1
    await store.set_setting('dashboard_login',json.dumps(data))
    assert not await consume(store.pool,code)

@pytest.mark.asyncio
async def test_only_private_owner_receives_protected_code(db):
    store,_=db;state=AsyncMock();cfg=SimpleNamespace(admin_id=99,origin='')
    m=SimpleNamespace(chat=SimpleNamespace(type='private'),from_user=SimpleNamespace(id=98),answer=AsyncMock())
    await dashboard(m,state,store,cfg);m.answer.assert_not_called()
    m.from_user.id=99;m.chat.type='group'
    await dashboard(m,state,store,cfg);m.answer.assert_not_called()
    m.chat.type='private';await dashboard(m,state,store,cfg)
    assert m.answer.call_args.kwargs['protect_content'] is True

def test_generated_seed_stable_and_explicit_keys_preserved(monkeypatch,tmp_path):
    for key in ['MASTER_ENCRYPTION_KEYS','PUBLIC_ORIGIN','DASHBOARD_PASSWORD_HASH','DYNO']:
        monkeypatch.delenv(key,raising=False)
    values={'APP_ENV':'production','BOT_TOKEN':'123:test','ADMIN_ID':'99','DATABASE_URL':'postgresql://localhost/test',
            'DATA_DIR':str(tmp_path),'MASTER_KEY_SEED':'a'*64,'SECRET_KEY':'b'*64,'TELETHON_ENABLED':'false'}
    for key,value in values.items():monkeypatch.setenv(key,value)
    a=Config.load('web');b=Config.load('web')
    assert a.keys==b.keys and a.origin=='' and a.password_hash==''
    Fernet(a.keys[0].encode())
    original=Fernet.generate_key().decode();monkeypatch.setenv('MASTER_ENCRYPTION_KEYS',original)
    assert Config.load('web').keys==(original,)
