"""Owner routes. The outer Guard authenticates every callback and every FSM reply."""
import re
import uuid
from html import escape
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from .states import Owner
from .ui import ADMIN, CANCEL, keyboard

router = Router()

@router.message(Command('adminpanel'))
async def panel(m: Message,state: FSMContext):
    await state.clear()
    await m.answer('<b>👑 Owner Control Center</b>',reply_markup=ADMIN)

@router.callback_query(F.data.startswith('admin:'))
async def action(q: CallbackQuery,state: FSMContext,store,cipher,bot,config):
    action = q.data.split(':')[1]
    await q.answer()
    await state.clear()
    if action=='analytics':
        users = await store.pool.fetchval('SELECT count(*) FROM users')
        revenues = await store.pool.fetch("SELECT currency,coalesce(sum(amount),0) total FROM transactions WHERE status='Approved' GROUP BY currency")
        pending = await store.pool.fetchval("SELECT count(*) FROM transactions WHERE status='Pending' AND screenshot_file_id IS NOT NULL")
        await q.message.answer(f'<b>📊 Business Analytics</b>\nUsers: {users}\nPending screenshots: {pending}\n'+ '\n'.join(f"Approved revenue: {r['total']} {r['currency']}" for r in revenues),reply_markup=ADMIN)
    elif action=='queue':
        rows = await store.pool.fetch("SELECT * FROM transactions WHERE status='Pending' AND screenshot_file_id IS NOT NULL ORDER BY timestamp LIMIT 10")
        for t in rows:
            await send_verification(bot,config.admin_id,t)
        await q.message.answer(f'{len(rows)} pending requests shown. Review these, then reopen for the next batch.',reply_markup=ADMIN)
    elif action=='settings':
        await state.set_state(Owner.setting)
        await q.message.answer('Send: <code>key value</code>\nKeys: upi_id, support_username, terms\nExample: <code>support_username @YourSupport</code>',reply_markup=CANCEL)
    elif action=='services':
        rows = await store.pool.fetch('SELECT * FROM services ORDER BY service_id')
        for start in range(0,len(rows),15):
            await q.message.answer('\n'.join(f"{s['service_id']}: {escape(s['service_name'])} | ₹{s['price']} | Stars {s['stars_price']} | days {s['validity_days']} | active {s['is_active']}" for s in rows[start:start+15]))
        await state.set_state(Owner.service)
        await q.message.answer('Send: <code>service_id field value</code>\nFields: price, stars_price, validity_days, delete_after_seconds, is_active, description, service_name\nAdd a separately priced reporting method: <code>new Name of method</code> (₹1500; configure Stars and upload research next).',reply_markup=CANCEL)
    elif action=='vault':
        from .content import show_services
        await show_services(q.message,store)
    elif action=='users':
        await state.set_state(Owner.users)
        await q.message.answer('Send one command:\n<code>ban USER_ID</code>\n<code>unban USER_ID</code>\n<code>revoke USER_ID SERVICE_ID</code>\n<code>extend USER_ID SERVICE_ID DAYS</code>\nUse DAYS=0 for lifetime. User must have started the bot.',reply_markup=CANCEL)
    elif action=='broadcast':
        await state.set_state(Owner.broadcast)
        await q.message.answer('Send broadcast text (up to 3000 characters). A protected preview and confirmation follow.',reply_markup=CANCEL)
    elif action=='refund':
        await state.set_state(Owner.refund)
        await q.message.answer('Send a Stars transaction UUID to refund. This revokes all access to that service for the user; restore other entitlements manually if needed.',reply_markup=CANCEL)

async def send_verification(bot,admin_id,t):
    await bot.send_photo(admin_id,t['screenshot_file_id'],caption=f"💳 Payment verification\nUser: {t['user_id']}\nService: {t['service_id']}\nAmount: {t['amount']} INR\nTxn: {t['txn_id']}\nVerify receipt in your bank; a screenshot alone is not proof.",protect_content=True,
                         reply_markup=keyboard([('✅ Approve',f"review:yes:{t['txn_id']}"),('❌ Reject',f"review:no:{t['txn_id']}")]))

@router.callback_query(F.data.startswith('review:'))
async def review(q: CallbackQuery,store,bot):
    _, decision, tid = q.data.split(':')
    if decision not in {'yes','no'}:
        raise ValueError('Invalid decision')
    t = await store.review(uuid.UUID(tid),decision=='yes',q.from_user.id)
    await q.answer('Decision saved.' if t else 'Already reviewed or unavailable.',show_alert=True)
    if t:
        await q.message.edit_reply_markup(reply_markup=None)
        if decision=='no':
            from aiogram.exceptions import TelegramAPIError
            try:
                await bot.send_message(t['user_id'],'❌ Payment Invalid. Your submission was rejected. Use /support for assistance or create a new order.')
            except TelegramAPIError:
                await q.message.answer('Decision saved; user notification failed. It remains visible in their profile.')

@router.message(Owner.setting,F.text)
async def setting(m: Message,state: FSMContext,store):
    key,value = m.text.split(maxsplit=1)
    if key not in {'upi_id','support_username','terms'} or len(value)>1500:
        raise ValueError('Unknown setting or too long')
    if key=='upi_id' and not re.fullmatch(r'[\w.\-]{2,256}@[a-zA-Z0-9.\-]{2,64}',value):
        raise ValueError('Invalid UPI ID')
    if key=='support_username' and not re.fullmatch(r'@[A-Za-z0-9_]{5,32}',value):
        raise ValueError('Use @username')
    async with store.pool.acquire() as c,c.transaction():
        await c.execute('UPDATE admin_settings SET setting_value=$2 WHERE setting_key=$1',key,value)
        if key=='terms':
            await c.execute("UPDATE admin_settings SET setting_value=CAST(CAST(setting_value AS INTEGER)+1 AS TEXT) WHERE setting_key='terms_version'")
    await store.audit(m.from_user.id,'setting',key)
    await state.clear()
    await m.answer('✅ Setting updated.',reply_markup=ADMIN)

@router.message(Owner.service,F.text)
async def service(m: Message,state: FSMContext,store):
    from decimal import Decimal
    if m.text.startswith('new '):
        name=m.text[4:].strip()
        if not 1<=len(name)<=80:
            raise ValueError('Name length')
        sid=await store.pool.fetchval("INSERT INTO services(service_name,price,description) VALUES($1,1500,'Owner-curated reporting ') RETURNING service_id",name)
    else:
        raw_sid,field,raw=m.text.split(maxsplit=2)
        sid=int(raw_sid)
        fields={'price','stars_price','validity_days','delete_after_seconds','is_active','description','service_name'}
        if field not in fields:
            raise ValueError('Unknown field')
        if field=='price':
            value=Decimal(raw)
            if not value.is_finite() or not 0<value<10**10 or value.as_tuple().exponent < -2:
                raise ValueError('Invalid price')
        elif field in {'stars_price','validity_days','delete_after_seconds'}:
            value=int(raw)
            lo,hi={'stars_price':(1,100000),'validity_days':(0,3650),'delete_after_seconds':(60,86400)}[field]
            if not lo<=value<=hi:
                raise ValueError('Out of range')
        elif field=='is_active':
            if raw.lower() not in {'true','false'}:
                raise ValueError('Use true/false')
            value=raw.lower()=='true'
        else:
            value=raw
            if not 1<=len(value)<=(80 if field=='service_name' else 500):
                raise ValueError('Text length')
        # field is strictly allowlisted, all values use SQL parameters.
        result=await store.pool.execute(f'UPDATE services SET revision=revision+1,{field}=$2 WHERE service_id=$1',sid,value)
        if result=='UPDATE 0':
            raise ValueError('No such service')
    await store.audit(m.from_user.id,'service_update',sid)
    await state.clear()
    await m.answer(f'✅ Service {sid} saved.',reply_markup=ADMIN)

@router.message(Owner.users,F.text)
async def users(m: Message,state: FSMContext,store,config):
    parts=m.text.split()
    cmd=parts[0]
    if cmd not in {'ban','unban','revoke','extend'} or len(parts)!={'ban':2,'unban':2,'revoke':3,'extend':4}[cmd]:
        raise ValueError('Invalid format')
    uid=int(parts[1])
    if uid==config.admin_id:
        raise ValueError('Owner cannot be modified here')
    async with store.pool.acquire() as c,c.transaction():
        if not await c.fetchval('SELECT EXISTS(SELECT 1 FROM users WHERE user_id=$1)',uid):
            raise ValueError('User must start first')
        if cmd in {'ban','unban'}:
            await c.execute('UPDATE users SET is_banned=$2 WHERE user_id=$1',uid,cmd=='ban')
        else:
            sid=int(parts[2])
            if not await c.fetchval('SELECT EXISTS(SELECT 1 FROM services WHERE service_id=$1)',sid):
                raise ValueError('Unknown service')
            if cmd=='revoke':
                await c.execute('UPDATE entitlements SET revoked=1 WHERE user_id=$1 AND service_id=$2',uid,sid)
            else:
                days=int(parts[3])
                if not 0<=days<=3650:
                    raise ValueError('Days out of range')
                await c.execute('''INSERT INTO entitlements(user_id,service_id,expires_at) VALUES($1,$2,CASE WHEN $3=0 THEN NULL ELSE now()+86400*$3 END)
                ON CONFLICT(user_id,service_id) DO UPDATE SET revoked=0,expires_at=CASE
                WHEN $3=0 OR (entitlements.expires_at IS NULL AND entitlements.revoked=0) THEN NULL
                ELSE max(now(),CASE WHEN entitlements.revoked=1 THEN now() ELSE entitlements.expires_at END)+86400*$3 END''',uid,sid,days)
    await store.audit(m.from_user.id,cmd,' '.join(parts[1:]))
    await state.clear()
    await m.answer('✅ User access updated.',reply_markup=ADMIN)

@router.message(Owner.broadcast,F.text)
async def broadcast(m: Message,state: FSMContext,cipher):
    if len(m.text)>3000:
        raise ValueError('Too long')
    # Redis FSM receives ciphertext only, never raw research or broadcast content.
    await state.update_data(broadcast=cipher.encrypt(0,m.text))
    await state.set_state(Owner.broadcast_confirm)
    await m.answer('<b>📢 Preview</b>\n'+escape(m.text),protect_content=True,reply_markup=keyboard([('✅ Send to all users','admin:send_broadcast')],[('✖️ Cancel','cancel')]))

# This handler is registered before the generic admin callback in main.py via a separate router.
confirm_router=Router()
@confirm_router.callback_query(Owner.broadcast_confirm,F.data=='admin:send_broadcast')
async def confirm_broadcast(q: CallbackQuery,state: FSMContext,store):
    token=(await state.get_data())['broadcast']
    bid=await store.pool.fetchval('INSERT INTO broadcasts(encrypted_text) VALUES($1) RETURNING broadcast_id',token)
    await store.audit(q.from_user.id,'broadcast',bid)
    await state.clear()
    await q.answer('Broadcast queued.')
    await q.message.edit_reply_markup(reply_markup=None)

@router.message(Owner.refund,F.text)
async def refund(m: Message,state: FSMContext,store,bot):
    tid=uuid.UUID(m.text.strip())
    async with store.pool.acquire() as c,c.transaction():
        t=await c.fetchrow('SELECT * FROM transactions WHERE txn_id=$1',tid)
        if not t or t['currency']!='XTR' or t['status'] not in {'Approved','Refunding'} or not t['telegram_charge_id']:
            raise ValueError('Not a refundable Stars payment')
        await c.execute("UPDATE transactions SET status='Refunding' WHERE txn_id=$1",tid)
        # Immediately suspend access, including existing queued deliveries.
        await c.execute('UPDATE entitlements SET revoked=1 WHERE user_id=$1 AND service_id=$2',t['user_id'],t['service_id'])
    from aiogram.exceptions import TelegramBadRequest
    try:
        await bot.refund_star_payment(t['user_id'],t['telegram_charge_id'])
    except TelegramBadRequest as exc:
        if 'CHARGE_ALREADY_REFUNDED' not in str(exc):
            raise
    await store.pool.execute("UPDATE transactions SET status='Refunded' WHERE txn_id=$1",tid)
    await store.audit(m.from_user.id,'refund',tid)
    await state.clear()
    await m.answer('✅ Refunded. Service access revoked.',reply_markup=ADMIN)

@confirm_router.message(Command('dashboard'))
async def dashboard(m: Message,state: FSMContext,store,config):
    # Explicit owner check in addition to the global Guard.
    if m.chat.type!='private' or m.from_user.id!=config.admin_id:return
    await state.clear()
    from backend.owner_login import issue
    code=await issue(store)
    location=escape(config.origin) if config.origin else 'Heroku → Open app'
    await m.answer(f'🔐 Owner dashboard: {location}\nLogin code (5 minutes, one use):\n<code>{code}</code>',protect_content=True)
