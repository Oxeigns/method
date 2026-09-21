import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import pytest
from cryptography.fernet import Fernet,InvalidToken
from aiogram.types import CallbackQuery,Message,User,Chat
from datetime import datetime,timezone
from bot.crypto import VaultCipher
from bot.middleware import Guard
from bot.workers import chunks,deliver_one
from bot.user import precheckout

@pytest.fixture
def cipher():
    return VaultCipher([Fernet.generate_key().decode()])

def test_cipher_roundtrip_random_iv_and_context(cipher):
    text='Private research <>& 🔐 हिंदी'
    a,b=cipher.encrypt(1,text),cipher.encrypt(1,text)
    assert a!=b and text not in a
    assert cipher.decrypt(1,a)==text
    with pytest.raises(InvalidToken):
        cipher.decrypt(2,a)

def test_cipher_rejects_tamper_wrong_key(cipher):
    token=cipher.encrypt(1,'secret')
    corrupted=token[:50]+('A' if token[50]!='A' else 'B')+token[51:]
    with pytest.raises(InvalidToken):
        cipher.decrypt(1,corrupted)
    with pytest.raises(InvalidToken):
        VaultCipher([Fernet.generate_key().decode()]).decrypt(1,token)

def test_key_rotation():
    old,new=Fernet.generate_key().decode(),Fernet.generate_key().decode()
    token=VaultCipher([old]).encrypt(1,'retained')
    assert VaultCipher([new,old]).decrypt(1,token)=='retained'

@pytest.mark.parametrize('text',['a'*10000,'<>&"'*2000,'😀हिंदी'*1000])
def test_chunks_preserve_text_and_bound_size(text):
    from html import escape
    parts=list(chunks(text))
    assert ''.join(parts)==text
    assert all(len(escape(p))<=3000 and len(p.encode('utf-16-le'))//2<=3000 for p in parts)

def event(uid=42,chat_type='private',data='admin:analytics'):
    user=User(id=uid,is_bot=False,first_name='Test')
    message=Message(message_id=1,date=datetime.now(timezone.utc),chat=Chat(id=uid,type=chat_type),from_user=user,text='x')
    return CallbackQuery(id='x',from_user=user,chat_instance='x',message=message,data=data)

@pytest.mark.asyncio
@pytest.mark.parametrize('callback',['admin:analytics','admin:vault','review:yes:'+str(uuid.uuid4())])
async def test_non_owner_cannot_call_admin(callback,monkeypatch):
    answer=AsyncMock()
    monkeypatch.setattr(CallbackQuery,'answer',answer)
    store=SimpleNamespace(user=AsyncMock(return_value={'is_banned':False}))
    redis=SimpleNamespace(incr=AsyncMock(return_value=1),expire=AsyncMock())
    state=SimpleNamespace(get_state=AsyncMock(return_value=None),clear=AsyncMock())
    handler=AsyncMock()
    await Guard(store,SimpleNamespace(admin_id=99),redis)(handler,event(data=callback),{'state':state})
    handler.assert_not_awaited()
    store.user.assert_not_awaited()
    answer.assert_awaited_once()

@pytest.mark.asyncio
async def test_forged_owner_state_denied(monkeypatch):
    monkeypatch.setattr(CallbackQuery,'answer',AsyncMock())
    state=SimpleNamespace(get_state=AsyncMock(return_value='Owner:vault_text'),clear=AsyncMock())
    handler=AsyncMock()
    await Guard(MagicMock(),SimpleNamespace(admin_id=99),MagicMock())(handler,event(data='catalog'),{'state':state})
    handler.assert_not_awaited()
    state.clear.assert_awaited_once()

@pytest.mark.asyncio
async def test_group_requests_denied(monkeypatch):
    monkeypatch.setattr(CallbackQuery,'answer',AsyncMock())
    handler=AsyncMock()
    await Guard(MagicMock(),SimpleNamespace(admin_id=42),MagicMock())(handler,event(chat_type='group'),{})
    handler.assert_not_awaited()

@pytest.mark.asyncio
async def test_banned_user_denied(monkeypatch):
    monkeypatch.setattr(CallbackQuery,'answer',AsyncMock())
    store=SimpleNamespace(user=AsyncMock(return_value={'is_banned':True}))
    handler=AsyncMock()
    await Guard(store,SimpleNamespace(admin_id=99),MagicMock())(handler,event(data='open:1'),{})
    handler.assert_not_awaited()

@pytest.mark.asyncio
async def test_delivery_checks_access_before_decrypt(cipher):
    cipher.decrypt=MagicMock()
    pool=SimpleNamespace(execute=AsyncMock())
    store=SimpleNamespace(allowed=AsyncMock(return_value=False),pool=pool)
    bot=SimpleNamespace(send_message=AsyncMock())
    await deliver_one(bot,store,cipher,{'user_id':1,'service_id':1,'job_id':1})
    cipher.decrypt.assert_not_called()
    bot.send_message.assert_not_awaited()

class Context:
    def __init__(self,value):self.value=value
    async def __aenter__(self):return self.value
    async def __aexit__(self,*args):return False

@pytest.mark.asyncio
async def test_delivery_is_protected_escaped_and_schedules_deletion(cipher):
    conn=MagicMock()
    conn.execute=AsyncMock()
    conn.transaction.return_value=Context(None)
    pool=MagicMock()
    pool.acquire.return_value=Context(conn)
    pool.fetch=AsyncMock(return_value=[{'data_id':1,'encrypted_payload':cipher.encrypt(1,'<b>secret</b>')}])
    pool.fetchval=AsyncMock(return_value=86400)
    pool.execute=AsyncMock()
    store=SimpleNamespace(pool=pool,allowed=AsyncMock(return_value=True))
    bot=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=123)))
    await deliver_one(bot,store,cipher,{'user_id':42,'service_id':1,'job_id':1,'data_cursor':0,'chunk_cursor':0})
    args,kwargs=bot.send_message.call_args
    assert args[0]==42 and '&lt;b&gt;secret&lt;/b&gt;' in args[1]
    assert kwargs['protect_content'] is True
    assert 'deletion_jobs' in conn.execute.call_args_list[0].args[0]
    assert conn.execute.call_args_list[0].args[1:]==(42,123,86400.0)

@pytest.mark.asyncio
async def test_resume_skips_delivered_chunks(cipher):
    conn=MagicMock();conn.execute=AsyncMock();conn.transaction.return_value=Context(None)
    pool=MagicMock();pool.acquire.return_value=Context(conn)
    pool.fetch=AsyncMock(return_value=[{'data_id':1,'encrypted_payload':cipher.encrypt(1,'a'*3000+'remaining')}])
    pool.fetchval=AsyncMock(return_value=86400);pool.execute=AsyncMock()
    store=SimpleNamespace(pool=pool,allowed=AsyncMock(return_value=True))
    bot=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)))
    await deliver_one(bot,store,cipher,{'user_id':42,'service_id':1,'job_id':1,'data_cursor':1,'chunk_cursor':1})
    bot.send_message.assert_awaited_once()
    assert bot.send_message.call_args.args[1].endswith('remaining')

@pytest.mark.asyncio
async def test_precheckout_rejects_unrecognized_order():
    q=SimpleNamespace(currency='XTR',from_user=SimpleNamespace(id=1),invoice_payload=str(uuid.uuid4()),total_amount=20,answer=AsyncMock())
    store=SimpleNamespace(precheckout=AsyncMock(return_value=False))
    await precheckout(q,store)
    assert q.answer.call_args.kwargs['ok'] is False

@pytest.mark.asyncio
async def test_precheckout_malformed_uuid():
    q=SimpleNamespace(currency='XTR',from_user=SimpleNamespace(id=1),invoice_payload='tampered',total_amount=20,answer=AsyncMock())
    store=SimpleNamespace(precheckout=AsyncMock())
    await precheckout(q,store)
    store.precheckout.assert_not_awaited()
    assert q.answer.call_args.kwargs['ok'] is False

@pytest.mark.asyncio
async def test_receipt_persisted_before_update_dispatch():
    from bot.polling import poll
    from aiogram.types import Update,SuccessfulPayment
    from unittest.mock import call
    u=User(id=42,is_bot=False,first_name='Test')
    m=Message(message_id=1,date=datetime.now(timezone.utc),chat=Chat(id=42,type='private'),from_user=u,
              successful_payment=SuccessfulPayment(currency='XTR',total_amount=100,invoice_payload=str(uuid.uuid4()),telegram_payment_charge_id='charge',provider_payment_charge_id=''))
    update=Update(update_id=1,message=m)
    order=[]
    async def persist(*args):order.append('persist')
    async def feed(*args,**kwargs):
        order.append('dispatch')
        raise asyncio.CancelledError()
    import asyncio
    store=SimpleNamespace(user=AsyncMock(),pool=SimpleNamespace(execute=AsyncMock(side_effect=persist)))
    bot=SimpleNamespace(get_updates=AsyncMock(return_value=[update]))
    dp=SimpleNamespace(resolve_used_update_types=lambda:['message'],feed_update=AsyncMock(side_effect=feed))
    with pytest.raises(asyncio.CancelledError):
        await poll(bot,dp,store,None,None)
    assert order==['persist','dispatch']

@pytest.mark.asyncio
async def test_duplicate_approved_receipt_does_not_grant_again():
    from bot.db import Store
    conn=MagicMock();conn.transaction.return_value=Context(None)
    conn.fetchrow=AsyncMock(return_value={'user_id':42,'currency':'XTR','amount':100,'telegram_charge_id':'charge'})
    conn.execute=AsyncMock()
    pool=MagicMock();pool.acquire.return_value=Context(conn)
    store=Store(pool)
    store._grant=AsyncMock()
    assert not await store.paid(42,uuid.uuid4(),'XTR',100,'charge')
    store._grant.assert_not_awaited()
    conn.execute.assert_not_awaited()

@pytest.mark.asyncio
@pytest.mark.parametrize('uid,currency,amount',[(43,'XTR',100),(42,'INR',100),(42,'XTR',1)])
async def test_receipt_mismatch_never_grants(uid,currency,amount):
    from bot.db import Store
    conn=MagicMock();conn.transaction.return_value=Context(None)
    conn.fetchrow=AsyncMock(return_value={'user_id':42,'currency':'XTR','amount':100,'telegram_charge_id':None})
    conn.execute=AsyncMock()
    pool=MagicMock();pool.acquire.return_value=Context(conn)
    store=Store(pool);store._grant=AsyncMock()
    with pytest.raises(ValueError):
        await store.paid(uid,uuid.uuid4(),currency,amount,'charge')
    store._grant.assert_not_awaited()
    conn.execute.assert_not_awaited()

@pytest.mark.asyncio
@pytest.mark.parametrize('callback',['content:backup','content:publish:1','content:delete_confirm:1','content:import_confirm'])
async def test_content_admin_callbacks_reject_non_owner(callback,monkeypatch):
    monkeypatch.setattr(CallbackQuery,'answer',AsyncMock())
    state=SimpleNamespace(get_state=AsyncMock(return_value=None),clear=AsyncMock())
    handler=AsyncMock()
    await Guard(MagicMock(),SimpleNamespace(admin_id=99),MagicMock())(handler,event(data=callback),{'state':state})
    handler.assert_not_awaited()

def test_config_creates_stable_key_and_refuses_missing_key(tmp_path,monkeypatch):
    from bot.config import Config
    monkeypatch.setenv('BOT_TOKEN','123:placeholder')
    monkeypatch.setenv('ADMIN_ID','99')
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    a=Config.load();b=Config.load()
    assert a.keys==b.keys
    assert (tmp_path/'master.key').stat().st_mode & 0o777 == 0o600
    (tmp_path/'research.sqlite3').write_bytes(b'placeholder')
    (tmp_path/'master.key').unlink()
    with pytest.raises(ValueError):Config.load()

def test_restore_rejects_malformed_or_tampered_bundles():
    from bot.backup import validate,seal,unseal
    with pytest.raises(ValueError):validate({'format':'research-content-v1','services':[{'service_name':'A','price':-1}]})
    bundle={'format':'research-content-v1','services':[{'service_name':'A','entries':[{'title':'Ref','text':'private'}]}]}
    blob=seal(bundle,'long-private-password')
    with pytest.raises(ValueError):unseal(blob[:-20]+b'X'*20,'long-private-password')
