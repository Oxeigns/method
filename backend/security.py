"""Owner sessions, database-backed revocation and CSRF on every mutation."""
import hmac
from functools import wraps
from flask import request,session,jsonify,current_app

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args,**kwargs):
        bridge=current_app.extensions['bridge'];cfg=bridge.cfg
        sid=session.get('sid')
        if session.get('admin_id')!=cfg.admin_id or not sid or not bridge.run(bridge.db.fetchval('SELECT EXISTS(SELECT 1 FROM web_sessions WHERE session_id=$1 AND expires_at>now())',sid)):
            session.clear();return jsonify(error='Authentication required'),401
        if request.method not in {'GET','HEAD','OPTIONS'}:
            if not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session.get('csrf','missing')):
                return jsonify(error='Invalid CSRF token'),403
        return fn(*args,**kwargs)
    return wrapped

def owner_command(cfg):
    """Telethon event decorator; authentication is repeated for every command."""
    def decorate(fn):
        @wraps(fn)
        async def wrapped(event,*args,**kwargs):
            if not event.is_private or event.sender_id!=cfg.admin_id:return
            return await fn(event,*args,**kwargs)
        return wrapped
    return decorate
