import uuid
from html import escape
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery, LabeledPrice
from aiogram.fsm.context import FSMContext
from .states import Checkout
from .ui import MAIN, CANCEL, keyboard

router = Router()

@router.message(CommandStart())
async def start(m: Message, state: FSMContext, store):
    await state.clear()
    await store.cancel(m.from_user.id)
    await m.answer('<b>🔐 Research & Compliance Vault</b>\nOwner-curated digital safety, legal frameworks and reporting \n<blockquote>Research does not guarantee an account restoration or enforcement outcome.</blockquote>',reply_markup=MAIN)

@router.message(Command('cancel'))
async def cancel_command(m: Message,state: FSMContext,store):
    await store.cancel(m.from_user.id)
    await state.clear()
    await m.answer('Cancelled. Submitted payments remain in the verification queue.',reply_markup=MAIN)

@router.callback_query(F.data=='cancel')
async def cancel(q: CallbackQuery,state: FSMContext,store):
    await store.cancel(q.from_user.id)
    await state.clear()
    await q.answer('Cancelled')
    await q.message.answer('Main menu',reply_markup=MAIN)

@router.message(Command('support','paysupport','help'))
async def support(m: Message,store,config):
    name = await store.setting('support_username') or config.support
    await m.answer(f'<b>📞 Support</b>\n{escape(name or "Contact the bot owner.")}\nFor payment issues include your transaction ID. Never send passwords or banking credentials. Telegram support cannot resolve purchases from this bot.')

@router.callback_query(F.data=='support')
async def support_button(q: CallbackQuery,store,config):
    await q.answer()
    await support(q.message,store,config)

@router.message(Command('terms'))
async def terms(m: Message,store):
    await m.answer('<b>Purchase terms</b>\n'+escape(await store.setting('terms')))

@router.callback_query((F.data=='catalog')|F.data.startswith('catalog:'))
async def catalog(q: CallbackQuery,state: FSMContext,store,config):
    from backend.menus import catalog as page_data
    await state.clear();await store.cancel(q.from_user.id)
    page=int(q.data.split(':')[1]) if ':' in q.data else 0
    data=await page_data(store,page)
    buttons=[]
    for item in data['items']:
        amount=item['price']['XTR'] if config.payment_mode=='stars' else item['price']['INR']
        label=str(amount)+' ⭐' if config.payment_mode=='stars' else '₹'+str(amount)
        buttons.append([(item['label']+' — '+label,item['action'])])
    nav=[]
    if page>0:nav.append(('⬅️ Previous',f'catalog:{page-1}'))
    if data['has_next']:nav.append(('Next ➡️',f'catalog:{page+1}'))
    if nav:buttons.append(nav)
    await q.answer()
    await q.message.answer(f"<b>🛒 Research services • Page {page+1}</b>",reply_markup=keyboard(*buttons))

@router.callback_query(F.data.startswith('service:'))
async def service(q: CallbackQuery,store,config):
    sid = int(q.data.split(':')[1])
    s = await store.pool.fetchrow('SELECT * FROM services WHERE service_id=$1 AND is_active=1',sid)
    if not s:
        return await q.answer('Service unavailable.',show_alert=True)
    duration = f"{s['validity_days']} days" if s['validity_days'] else 'Lifetime access while this service operates'
    price = f"{s['stars_price']} Stars" if config.payment_mode=='stars' else f"₹{s['price']:,.2f}"
    if config.payment_mode=='stars' and not s['stars_price']:
        price = 'Stars price not configured; checkout unavailable'
    ver = await store.setting('terms_version')
    text = f"<b>{escape(s['service_name'])}</b>\n{escape(s['description'])}\n\nPrice: {price}\nAccess: {duration}\n\n<b>Terms</b>\n{escape(await store.setting('terms'))}"
    await q.answer()
    await q.message.answer(text,reply_markup=keyboard([('✅ Agree & Buy',f'buy:{sid}:{ver}')],[('🔓 Open purchased research',f'open:{sid}')]))

@router.callback_query(F.data.startswith('buy:'))
async def buy(q: CallbackQuery,state: FSMContext,store,config,bot):
    _, sid, ver = q.data.split(':')
    upi = await store.setting('upi_id')
    if config.payment_mode=='upi' and not upi:
        return await q.answer('Payment details not configured.',show_alert=True)
    tid,s,amount = await store.order(q.from_user.id,int(sid),'XTR' if config.payment_mode=='stars' else 'INR',ver)
    await state.clear()
    await q.answer()
    if config.payment_mode=='stars':
        await bot.send_invoice(q.from_user.id,title=s['service_name'][:32],description=s['description'][:255],
                               payload=str(tid),currency='XTR',prices=[LabeledPrice(label='Research access',amount=int(amount))],
                               provider_token='',start_parameter='research')
    else:
        await state.set_state(Checkout.waiting_for_screenshot)
        await state.update_data(txn_id=str(tid))
        await q.message.answer(f'Pay <b>₹{amount:,.2f}</b> to <code>{escape(upi)}</code> (tap to copy).\nSend the payment screenshot as a photo here within 30 minutes.\nOrder: <code>{tid}</code>',reply_markup=CANCEL)

@router.message(Checkout.waiting_for_screenshot,F.photo)
async def screenshot(m: Message,state: FSMContext,store):
    tid = uuid.UUID((await state.get_data())['txn_id'])
    ok = await store.screenshot(m.from_user.id,tid,m.photo[-1].file_id)
    await state.clear()
    if not ok:
        return await m.answer('Order expired or already submitted. Open your purchases or create a new order.',reply_markup=MAIN)
    await m.answer('✅ Screenshot received. Waiting for Admin verification.',reply_markup=MAIN)

@router.message(Checkout.waiting_for_screenshot,~F.successful_payment)
async def need_photo(m: Message):
    await m.answer('Please upload a photo screenshot, or /cancel.',reply_markup=CANCEL)

@router.pre_checkout_query()
async def precheckout(q: PreCheckoutQuery,store):
    try:
        ok = q.currency=='XTR' and await store.precheckout(q.from_user.id,uuid.UUID(q.invoice_payload),q.currency,q.total_amount)
    except (ValueError,TypeError):
        ok = False
    await q.answer(ok=bool(ok),error_message=None if ok else 'Order expired or unavailable. Open the catalog and try again.')

@router.message(F.successful_payment)
async def successful(m: Message,store):
    p = m.successful_payment
    # Polling persists every receipt before acknowledging Telegram's update offset.
    # The receipt worker validates it, grants access and queues delivery atomically.
    await m.answer('✅ Payment receipt recorded. Access is being verified and your research will be delivered automatically. Use /paysupport for assistance.',reply_markup=MAIN)

@router.callback_query(F.data=='profile')
async def profile(q: CallbackQuery,store):
    entries = await store.pool.fetch('''SELECT e.*,s.service_name FROM entitlements e JOIN services s USING(service_id) WHERE user_id=$1 ORDER BY service_id LIMIT 20''',q.from_user.id)
    txns = await store.pool.fetch('SELECT txn_id,status,amount,currency FROM transactions WHERE user_id=$1 ORDER BY timestamp DESC LIMIT 5',q.from_user.id)
    lines = [f'<b>👤 Profile (first 20 services; full access via catalog)</b>\nID: <code>{q.from_user.id}</code>']
    for e in entries:
        expiry = e['expires_at'].strftime('%Y-%m-%d %H:%M UTC') if e['expires_at'] else 'Lifetime'
        lines.append(f"{escape(e['service_name'])}: {'Revoked' if e['revoked'] else expiry}")
    lines.append('\n<b>Recent transactions</b>')
    lines.extend(f"<code>{t['txn_id']}</code>\n{t['status']} • {t['amount']} {t['currency']}" for t in txns)
    await q.answer()
    await q.message.answer('\n'.join(lines),reply_markup=keyboard(*[[(f"🔓 {e['service_name']}",f"open:{e['service_id']}")] for e in entries]))

@router.callback_query(F.data.startswith('open:'))
async def open_research(q: CallbackQuery,store):
    sid = int(q.data.split(':')[1])
    if not await store.allowed(q.from_user.id,sid):
        return await q.answer('No active access. Purchase this service or contact support.',show_alert=True)
    await store.request_delivery(q.from_user.id,sid)
    await q.answer('Research queued for protected delivery.')
