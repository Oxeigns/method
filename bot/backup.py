"""Portable password-encrypted content backups. No users, receipts or keys exported."""
import base64
import hashlib
import json
import os
from cryptography.fernet import Fernet,InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAX_BYTES=5_000_000

def password_cipher(password,salt):
    if not 16<=len(password)<=256:raise ValueError('Use a backup password of 16–256 characters.')
    key=Scrypt(salt=salt,length=32,n=2**15,r=8,p=1).derive(password.encode())
    return Fernet(base64.urlsafe_b64encode(key))

def seal(bundle,password):
    salt=os.urandom(16)
    raw=json.dumps(validate(bundle),ensure_ascii=False).encode()
    return b'RVB1'+salt+password_cipher(password,salt).encrypt(raw)

def unseal(blob,password):
    if len(blob)>MAX_BYTES or not blob.startswith(b'RVB1') or len(blob)<100:
        raise ValueError('Invalid or oversized .vault backup.')
    try:return validate(json.loads(password_cipher(password,blob[4:20]).decrypt(blob[20:])))
    except (InvalidToken,UnicodeError,json.JSONDecodeError) as exc:
        raise ValueError('Wrong backup password or damaged file.') from exc

def validate(bundle):
    if not isinstance(bundle,dict) or bundle.get('format')!='research-content-v1':
        raise ValueError('Unsupported content file. Use research-content-v1.')
    services=bundle.get('services')
    if not isinstance(services,list) or not 1<=len(services)<=100:
        raise ValueError('Include 1–100 services.')
    clean=[];entries_total=0
    for s in services:
        if not isinstance(s,dict):raise ValueError('Invalid service.')
        def text(key,limit,default=''):
            value=s.get(key,default)
            if not isinstance(value,str) or not 1<=len(value)<=limit:raise ValueError(f'Invalid {key}.')
            return value
        name=text('service_name',80)
        description=text('description',500,'Imported reference data. Owner review required.')
        price=s.get('price',1500)
        if isinstance(price,bool) or not isinstance(price,(int,float)) or not 0<price<10**10 or round(price,2)!=price:
            raise ValueError('Invalid INR reference price.')
        stars=s.get('stars_price')
        if stars is not None and (type(stars) is not int or not 1<=stars<=100000):raise ValueError('Invalid Stars price.')
        days=s.get('validity_days',0);ttl=s.get('delete_after_seconds',86400)
        if type(days) is not int or not 0<=days<=3650:raise ValueError('Invalid validity.')
        if type(ttl) is not int or not 60<=ttl<=86400:raise ValueError('Invalid deletion timer.')
        entries=s.get('entries')
        if not isinstance(entries,list) or len(entries)>1000:raise ValueError('Invalid entries.')
        rows=[]
        for e in entries:
            if not isinstance(e,dict) or not isinstance(e.get('title'),str) or not 1<=len(e['title'])<=80:
                raise ValueError('Invalid entry title.')
            if not isinstance(e.get('text'),str) or not 1<=len(e['text'].encode())<=100000:
                raise ValueError('Invalid entry text.')
            rows.append({'title':e['title'],'text':e['text']})
        entries_total+=len(rows)
        clean.append(dict(service_name=name,description=description,price=price,stars_price=stars,
                          validity_days=days,delete_after_seconds=ttl,entries=rows))
    if entries_total>1000:raise ValueError('Maximum 1000 entries per import.')
    result={'format':'research-content-v1','services':clean}
    if len(json.dumps(result,ensure_ascii=False).encode())>2_000_000:raise ValueError('Content exceeds 2 MB.')
    return result

async def export_content(store,cipher):
    services=await store.pool.fetch('SELECT * FROM services ORDER BY service_id')
    result=[]
    for s in services:
        rows=await store.pool.fetch('SELECT * FROM vault_data WHERE service_id=$1 ORDER BY data_id',s['service_id'])
        result.append(dict(service_name=s['service_name'],description=s['description'],price=s['price'],stars_price=s['stars_price'],
                           validity_days=s['validity_days'],delete_after_seconds=s['delete_after_seconds'],
                           entries=[{'title':r['title'],'text':cipher.decrypt(s['service_id'],r['encrypted_payload'])} for r in rows]))
    return validate({'format':'research-content-v1','services':result})

async def import_content(store,cipher,bundle,actor):
    bundle=validate(bundle)
    digest=hashlib.sha256(json.dumps(bundle,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    ids=[]
    # Additive import: never overwrite sold services, users, payment records, or keys.
    async with store.pool.acquire() as c,c.transaction():
        if await c.fetchval('SELECT EXISTS(SELECT 1 FROM content_imports WHERE digest=$1)',digest):
            raise ValueError('This exact content was already imported.')
        for s in bundle['services']:
            sid=await c.fetchval('''INSERT INTO services(service_name,description,price,stars_price,validity_days,delete_after_seconds,is_active)
            VALUES($1,$2,$3,$4,$5,$6,0) RETURNING service_id''',s['service_name'],s['description'],s['price'],s['stars_price'],s['validity_days'],s['delete_after_seconds'])
            ids.append(sid)
            for e in s['entries']:
                await c.execute('INSERT INTO vault_data(service_id,title,encrypted_payload,is_published) VALUES($1,$2,$3,0)',sid,e['title'],cipher.encrypt(sid,e['text']))
        await c.execute('INSERT INTO content_imports(digest) VALUES($1)',digest)
        await c.execute('INSERT INTO audit_log(actor_id,action,target) VALUES($1,$2,$3)',actor,'content_import',digest)
    return ids
