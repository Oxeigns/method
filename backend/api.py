import atexit,base64,hashlib,logging,re,secrets,time
from datetime import timedelta
from pathlib import Path
from flask import Flask,jsonify,request,session,send_from_directory
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from .bridge import Bridge
from .security import admin_required
from .models import Login,ServiceCreate,ServicePatch,EntryCreate,EntryPatch,Publish,Broadcast,Ban,Decision
from .logging import configure

class Conflict(Exception):pass
class Missing(Exception):pass

def create_app(cfg=None,bridge=None):
    cfg=cfg or Config.load('web');bridge=bridge or Bridge(cfg)
    app=Flask(__name__,static_folder=None)
    app.extensions['bridge']=bridge
    app.config.update(SECRET_KEY=cfg.secret_key,MAX_CONTENT_LENGTH=150000,SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SECURE=cfg.production,SESSION_COOKIE_SAMESITE='Strict',
                      SESSION_COOKIE_NAME='method_session',PERMANENT_SESSION_LIFETIME=timedelta(hours=2))
    if cfg.trust_proxy:app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1)
    atexit.register(bridge.close)
    root=Path(__file__).parents[1]/'frontend'/'out'
    hashes=[]
    if (root/'index.html').exists():
        for body in re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>',(root/'index.html').read_text(),re.S):
            if body:hashes.append("'sha256-"+base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()+"'")

    def parse(model):return model.model_validate(request.get_json())
    def run(coro):return bridge.run(coro)
    def pagination():
        page=int(request.args.get('page','0'));size=int(request.args.get('size','20'))
        if not 0<=page<=100000 or not 1<=size<=50:raise ValueError('Invalid pagination')
        return page,size
    def page_response(items,page,size):
        return jsonify(items=items[:size],page=page,size=size,has_next=len(items)>size)

    @app.before_request
    def before():
        request.started=time.monotonic();request.trace=secrets.token_hex(8)
        if request.path.startswith('/api/') and request.method not in {'GET','HEAD','OPTIONS'}:
            if request.headers.get('Origin')!=cfg.origin:return jsonify(error='Origin rejected'),403
            if not request.is_json:return jsonify(error='JSON required'),415

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff';response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' "+' '.join(hashes)+"; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers['X-Request-ID']=getattr(request,'trace','')
        if cfg.production:response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
        if request.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
        # Route pattern, never user data or request URLs/query strings.
        logging.getLogger('analytics').info('request route=%s status=%s duration_ms=%s',str(request.url_rule),response.status_code,round((time.monotonic()-getattr(request,'started',time.monotonic()))*1000))
        return response

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc,Conflict):return jsonify(error='Changed elsewhere. Reload before saving.'),409
        if isinstance(exc,Missing):return jsonify(error='Not found'),404
        if isinstance(exc,(ValidationError,ValueError)):return jsonify(error='Invalid request fields'),400
        if isinstance(exc,HTTPException):return jsonify(error=exc.name),exc.code
        logging.error('api_failure type=%s',type(exc).__name__)
        return jsonify(error='Request failed',request_id=getattr(request,'trace','')),503

    @app.get('/health')
    def health():
        run(bridge.db.fetchval('SELECT 1'))
        return jsonify(status='ok')

    @app.post('/api/login')
    def login():
        data=parse(Login);bucket=hashlib.sha256((request.remote_addr or 'unknown').encode()).hexdigest()
        async def attempt():
            async with bridge.db.acquire() as c,c.transaction():
                return await c.fetchval('''INSERT INTO login_limits(bucket,attempts,reset_at) VALUES($1,1,now()+300)
                ON CONFLICT(bucket) DO UPDATE SET attempts=CASE WHEN login_limits.reset_at<now() THEN 1 ELSE login_limits.attempts+1 END,
                reset_at=CASE WHEN login_limits.reset_at<now() THEN now()+300 ELSE login_limits.reset_at END RETURNING attempts''',bucket)
        if run(attempt())>8:return jsonify(error='Try again in five minutes'),429
        if not check_password_hash(cfg.password_hash,data.password):return jsonify(error='Invalid credentials'),401
        session.clear();session.permanent=True;session['admin_id']=cfg.admin_id
        session['sid']=secrets.token_urlsafe(32);session['csrf']=secrets.token_urlsafe(32)
        run(bridge.db.execute('INSERT INTO web_sessions(session_id,expires_at) VALUES($1,now()+7200)',session['sid']))
        return jsonify(csrf=session['csrf'],admin_id=cfg.admin_id)

    @app.get('/api/session')
    @admin_required
    def who():return jsonify(csrf=session['csrf'],admin_id=cfg.admin_id)

    @app.post('/api/logout')
    @admin_required
    def logout():
        run(bridge.db.execute('DELETE FROM web_sessions WHERE session_id=$1',session['sid']));session.clear()
        return jsonify(ok=True)

    @app.get('/api/analytics')
    @admin_required
    def analytics():
        async def query():
            return dict(users=await bridge.db.fetchval('SELECT count(*) FROM users'),
                        services=await bridge.db.fetchval('SELECT count(*) FROM services'),
                        entries=await bridge.db.fetchval('SELECT count(*) FROM vault_data'),
                        pending=await bridge.db.fetchval("SELECT count(*) FROM transactions WHERE status='Pending' AND screenshot_file_id IS NOT NULL"),
                        revenue=await bridge.db.fetch("SELECT currency,sum(amount) AS total FROM transactions WHERE status='Approved' GROUP BY currency"),
                        failed_deliveries=await bridge.db.fetchval("SELECT count(*) FROM delivery_jobs WHERE status='blocked' OR attempts>5"))
        return jsonify(run(query()))

    @app.get('/api/services')
    @admin_required
    def services():
        page,size=pagination()
        return page_response(run(bridge.db.fetch('SELECT * FROM services ORDER BY service_id LIMIT $1 OFFSET $2',size+1,page*size)),page,size)

    @app.post('/api/services')
    @admin_required
    def create_service():
        d=parse(ServiceCreate).model_dump()
        async def query():
            async with bridge.db.acquire() as c,c.transaction():
                sid=await c.fetchval('INSERT INTO services(service_name,description,price,stars_price,validity_days,delete_after_seconds,is_active) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING service_id',*d.values())
                await c.execute('INSERT INTO audit_log(actor_id,action,target) VALUES($1,$2,$3)',cfg.admin_id,'web_service_create',str(sid))
                return await c.fetchrow('SELECT * FROM services WHERE service_id=$1',sid)
        return jsonify(run(query())),201

    @app.patch('/api/services/<int:sid>')
    @admin_required
    def edit_service(sid):
        d=parse(ServicePatch).model_dump(exclude_unset=True);revision=d.pop('revision')
        if not d:raise ValueError('Empty patch')
        if any(v is None and k!='stars_price' for k,v in d.items()):raise ValueError('Null field')
        async def query():
            # Field names originate only from the Pydantic allowlist.
            fields=','.join(f'{k}=${i}' for i,k in enumerate(d,3))
            r=await bridge.db.fetchrow(f'UPDATE services SET {fields},revision=revision+1 WHERE service_id=$1 AND revision=$2 RETURNING *',sid,revision,*d.values())
            if not r:raise Conflict()
            await bridge.store.audit(cfg.admin_id,'web_service_edit',sid)
            return r
        return jsonify(run(query()))

    @app.get('/api/services/<int:sid>/entries')
    @admin_required
    def entries(sid):
        page,size=pagination()
        rows=run(bridge.db.fetch('SELECT data_id,service_id,title,is_published,revision,created_at FROM vault_data WHERE service_id=$1 ORDER BY data_id LIMIT $2 OFFSET $3',sid,size+1,page*size))
        return page_response(rows,page,size)

    @app.post('/api/services/<int:sid>/entries')
    @admin_required
    def add_entry(sid):
        d=parse(EntryCreate)
        async def query():
            if not await bridge.db.fetchval('SELECT EXISTS(SELECT 1 FROM services WHERE service_id=$1)',sid):raise Missing()
            token=bridge.cipher.encrypt(sid,d.text)
            did=await bridge.db.fetchval('INSERT INTO vault_data(service_id,title,encrypted_payload) VALUES($1,$2,$3) RETURNING data_id',sid,d.title,token)
            await bridge.store.audit(cfg.admin_id,'web_entry_create',did)
            return dict(data_id=did,revision=1,is_published=0)
        return jsonify(run(query())),201

    @app.get('/api/entries/<int:did>')
    @admin_required
    def entry(did):
        async def query():
            r=await bridge.db.fetchrow('SELECT * FROM vault_data WHERE data_id=$1',did)
            if not r:raise Missing()
            text=bridge.cipher.decrypt(r['service_id'],r.pop('encrypted_payload'))
            r['text']=text;await bridge.store.audit(cfg.admin_id,'web_entry_read',did)
            return r
        return jsonify(run(query()))

    @app.patch('/api/entries/<int:did>')
    @admin_required
    def edit_entry(did):
        d=parse(EntryPatch)
        async def query():
            r=await bridge.db.fetchrow('SELECT service_id FROM vault_data WHERE data_id=$1',did)
            if not r:raise Missing()
            token=bridge.cipher.encrypt(r['service_id'],d.text)
            updated=await bridge.db.fetchrow('UPDATE vault_data SET title=$3,encrypted_payload=$4,is_published=0,revision=revision+1 WHERE data_id=$1 AND revision=$2 RETURNING data_id,revision,is_published',did,d.revision,d.title,token)
            if not updated:raise Conflict()
            await bridge.store.audit(cfg.admin_id,'web_entry_edit',did)
            return updated
        return jsonify(run(query()))

    @app.post('/api/entries/<int:did>/publish')
    @admin_required
    def publish(did):
        d=parse(Publish)
        r=run(bridge.db.fetchrow('UPDATE vault_data SET is_published=$3,revision=revision+1 WHERE data_id=$1 AND revision=$2 RETURNING revision,is_published',did,d.revision,int(d.published)))
        if not r:raise Conflict()
        run(bridge.store.audit(cfg.admin_id,'web_publish' if d.published else 'web_unpublish',did))
        return jsonify(r)

    @app.delete('/api/entries/<int:did>')
    @admin_required
    def delete_entry(did):
        revision=request.get_json().get('revision')
        if type(revision) is not int:raise ValueError('Revision required')
        r=run(bridge.db.fetchval('DELETE FROM vault_data WHERE data_id=$1 AND revision=$2 RETURNING data_id',did,revision))
        if r is None:raise Conflict()
        run(bridge.store.audit(cfg.admin_id,'web_entry_delete',did));return jsonify(ok=True)

    @app.get('/api/users')
    @admin_required
    def users():
        page,size=pagination()
        return page_response(run(bridge.db.fetch('SELECT * FROM users ORDER BY user_id LIMIT $1 OFFSET $2',size+1,page*size)),page,size)

    @app.patch('/api/users/<int:uid>')
    @admin_required
    def user_ban(uid):
        d=parse(Ban)
        if uid==cfg.admin_id:raise ValueError('Cannot ban owner')
        r=run(bridge.db.fetchval('UPDATE users SET is_banned=$2 WHERE user_id=$1 RETURNING user_id',uid,int(d.is_banned)))
        if r is None:raise Missing()
        run(bridge.store.audit(cfg.admin_id,'web_user_ban',uid));return jsonify(ok=True)

    @app.get('/api/transactions')
    @admin_required
    def transactions():
        page,size=pagination()
        return page_response(run(bridge.db.fetch('SELECT txn_id,user_id,service_id,amount,currency,status,timestamp,screenshot_file_id FROM transactions ORDER BY timestamp DESC LIMIT $1 OFFSET $2',size+1,page*size)),page,size)

    @app.post('/api/transactions/<tid>/review')
    @admin_required
    def review(tid):
        import uuid
        d=parse(Decision);r=run(bridge.store.review(uuid.UUID(tid),d.approve,cfg.admin_id))
        if not r:raise Conflict()
        return jsonify(ok=True)

    @app.get('/api/broadcasts')
    @admin_required
    def broadcasts():
        page,size=pagination()
        rows=run(bridge.db.fetch('''SELECT b.broadcast_id,b.created_at,b.done,
        (SELECT count(*) FROM broadcast_targets t WHERE t.broadcast_id=b.broadcast_id) AS recipients,
        (SELECT count(*) FROM broadcast_targets t WHERE t.broadcast_id=b.broadcast_id AND t.status='sent') AS sent,
        (SELECT count(*) FROM broadcast_targets t WHERE t.broadcast_id=b.broadcast_id AND t.status='failed') AS failed
        FROM broadcasts b ORDER BY broadcast_id DESC LIMIT $1 OFFSET $2''',size+1,page*size))
        return page_response(rows,page,size)

    @app.post('/api/broadcasts')
    @admin_required
    def broadcast():
        d=parse(Broadcast)
        bid=run(bridge.db.fetchval('INSERT INTO broadcasts(encrypted_text) VALUES($1) RETURNING broadcast_id',bridge.cipher.encrypt(0,d.text)))
        run(bridge.store.audit(cfg.admin_id,'web_broadcast',bid));return jsonify(broadcast_id=bid),202

    @app.get('/')
    def index():
        if not (root/'index.html').exists():return 'Dashboard not built. Run npm ci && npm run build.',503
        return send_from_directory(root,'index.html')
    @app.get('/<path:path>')
    def static(path):
        if path.startswith('api/'):return jsonify(error='Not found'),404
        return send_from_directory(root,path)
    return app
