from pathlib import Path
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash
from config import Config
from backend.api import create_app
from backend.bridge import Bridge

PASSWORD='local-test-password-only'
@pytest.fixture
def web(tmp_path):
    cfg=Config(token='123:placeholder',admin_id=99,data_dir=tmp_path,keys=(Fernet.generate_key().decode(),),
               payment_mode='stars',support='',origin='http://localhost:8000',secret_key='s'*48,
               password_hash=generate_password_hash(PASSWORD,method='pbkdf2:sha256:1000'))
    bridge=Bridge(cfg);app=create_app(cfg,bridge);app.testing=True
    client=app.test_client()
    yield client,bridge
    bridge.close()

def auth(client):
    r=client.post('/api/login',json={'password':PASSWORD},headers={'Origin':'http://localhost:8000'})
    assert r.status_code==200
    return {'Origin':'http://localhost:8000','X-CSRF-Token':r.json['csrf']}

def test_auth_origin_csrf_revocation(web):
    client,b=web
    assert client.get('/api/services').status_code==401
    assert client.post('/api/login',json={'password':PASSWORD}).status_code==403
    h=auth(client)
    assert client.get('/api/services').status_code==200
    assert client.post('/api/services',json={},headers={'Origin':h['Origin']}).status_code==403
    assert client.post('/api/logout',json={},headers=h).status_code==200
    assert client.get('/api/services').status_code==401

def test_login_rate_limit(web):
    c,_=web
    for _ in range(8):
        assert c.post('/api/login',json={'password':'wrong'},headers={'Origin':'http://localhost:8000'}).status_code==401
    assert c.post('/api/login',json={'password':PASSWORD},headers={'Origin':'http://localhost:8000'}).status_code==429

def test_validation_pagination_and_security_headers(web):
    c,_=web;h=auth(c)
    assert c.get('/api/services?size=999').status_code==400
    assert c.get('/api/services?page=-1').status_code==400
    assert c.post('/api/services',json={'service_name':'Bad','description':'Bad','price':-1},headers=h).status_code==400
    r=c.get('/api/services?size=2')
    assert len(r.json['items'])==2 and r.json['has_next']
    assert r.headers['Cache-Control']=='no-store'
    assert r.headers['X-Frame-Options']=='DENY'
    assert 'frame-ancestors' in r.headers['Content-Security-Policy']

def test_content_revision_encryption_and_draft_defaults(web):
    c,b=web;h=auth(c)
    r=c.post('/api/services/1/entries',json={'title':'Evidence','text':'PRIVATE-WEB-REFERENCE'},headers=h)
    assert r.status_code==201
    did=r.json['data_id']
    stored=b.run(b.db.fetchrow('SELECT * FROM vault_data WHERE data_id=$1',did))
    assert 'PRIVATE-WEB-REFERENCE' not in stored['encrypted_payload'] and not stored['is_published']
    r=c.get(f'/api/entries/{did}')
    assert r.json['text']=='PRIVATE-WEB-REFERENCE' and 'encrypted_payload' not in r.json
    assert c.post(f'/api/entries/{did}/publish',json={'revision':1,'published':True},headers=h).status_code==200
    assert c.patch(f'/api/entries/{did}',json={'revision':1,'title':'Stale','text':'stale'},headers=h).status_code==409
    r=c.patch(f'/api/entries/{did}',json={'revision':2,'title':'New','text':'Private edit'},headers=h)
    assert r.status_code==200 and not r.json['is_published']
    assert c.delete(f'/api/entries/{did}',json={'revision':2},headers=h).status_code==409
    assert c.delete(f'/api/entries/{did}',json={'revision':3},headers=h).status_code==200

def test_service_update_preserves_unknown_fields_and_conflicts(web):
    c,_=web;h=auth(c)
    new=c.post('/api/services',json={'service_name':'Created','description':'Reference','price':1500,'stars_price':90},headers=h)
    assert new.status_code==201
    sid=new.json['service_id']
    r=c.patch(f'/api/services/{sid}',json={'revision':1,'price':1600},headers=h)
    assert r.status_code==200 and r.json['price']==1600
    assert c.patch(f'/api/services/{sid}',json={'revision':1,'price':1},headers=h).status_code==409
    assert c.patch(f'/api/services/{sid}',json={'revision':2,'drop table':'x'},headers=h).status_code==400

def test_command_database_delivery_dashboard_data_flow(web):
    from backend.menus import catalog
    from bot.workers import deliver_one
    c,b=web;h=auth(c)
    c.patch('/api/services/1',json={'revision':1,'stars_price':100},headers=h)
    r=c.post('/api/services/1/entries',json={'title':'Research','text':'PAID-REFERENCE'},headers=h)
    c.post(f"/api/entries/{r.json['data_id']}/publish",json={'revision':1,'published':True},headers=h)
    async def command_flow():
        await b.store.user(SimpleNamespace(id=42,username='test',full_name='Test User'))
        menu=await catalog(b.store)
        assert menu['items'][0]['price']['XTR']==100
        tid,_,_=await b.store.order(42,1,'XTR','1')
        assert await b.store.precheckout(42,tid,'XTR',100)
        await b.store.paid(42,tid,'XTR',100,'unique-test-charge')
        job=await b.db.fetchrow('SELECT * FROM delivery_jobs WHERE txn_id=$1',tid)
        sender=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=123)))
        await deliver_one(sender,b.store,b.cipher,job)
        assert sender.send_message.call_args.kwargs['protect_content']
        assert 'PAID-REFERENCE' in sender.send_message.call_args.args[1]
    b.run(command_flow())
    metrics=c.get('/api/analytics').json
    assert metrics['users']==1 and metrics['revenue']==[{'currency':'XTR','total':100}]
    assert c.get('/api/transactions').json['items'][0]['status']=='Approved'

def test_confirmed_broadcast_and_owner_cannot_be_banned(web):
    c,b=web;h=auth(c)
    assert c.post('/api/broadcasts',json={'text':'Hello','confirmed':False},headers=h).status_code==400
    assert c.post('/api/broadcasts',json={'text':'Hello','confirmed':True},headers=h).status_code==202
    assert c.patch('/api/users/99',json={'is_banned':True},headers=h).status_code==400
