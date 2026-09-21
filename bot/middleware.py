"""Every update is private-chat scoped; owner authentication covers callbacks and FSM."""
import logging
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery

class Guard(BaseMiddleware):
    def __init__(self, store, config, limiter):
        self.store, self.config, self.redis = store, config, limiter

    async def __call__(self, handler, event, data):
        u = getattr(event,'from_user',None)
        if not u:
            return
        chat = event.message.chat if isinstance(event,CallbackQuery) and event.message else getattr(event,'chat',None)
        if chat and chat.type != 'private':
            if isinstance(event,CallbackQuery):
                await event.answer('Use this bot in a private chat.',show_alert=True)
            return
        is_owner = u.id == self.config.admin_id
        state = data.get('state')
        state_name = await state.get_state() if state else ''
        owner_route = (isinstance(event,CallbackQuery) and (event.data or '').startswith(('admin:','review:','content:'))) or (isinstance(event,Message) and (event.text or '').split('@')[0].split()[0:1] in [['/adminpanel'],['/backup'],['/restore'],['/import']]) or (state_name or '').startswith('Owner:')
        if owner_route and not is_owner:
            if state:
                await state.clear()
            await event.answer('Owner access only.', **({'show_alert':True} if isinstance(event,CallbackQuery) else {}))
            return
        user = await self.store.user(u)
        # Never drop real payment receipts because a user was banned after checkout.
        receipt = isinstance(event,Message) and bool(event.successful_payment)
        if user['is_banned'] and not is_owner and not receipt:
            if isinstance(event,PreCheckoutQuery):
                await event.answer(ok=False,error_message='Access is suspended. Contact support.')
            else:
                await event.answer('Access is suspended. Contact the owner for billing assistance.', **({'show_alert':True} if isinstance(event,CallbackQuery) else {}))
            return
        if not receipt and not isinstance(event,PreCheckoutQuery):
            count = await self.limiter.incr(f'rate:{u.id}')
            if count == 1:
                await self.limiter.expire(f'rate:{u.id}',3)
            if count > 12:
                if isinstance(event,CallbackQuery):
                    await event.answer('Please slow down.')
                return
        try:
            return await handler(event,data)
        except ValueError as exc:
            # Only explicit validation errors should be shown; do not include raw provider errors.
            logging.warning('Validation rejected (%s)',type(exc).__name__)
            await event.answer('Invalid input or unavailable action. Check the requested format and try again.', **({'show_alert':True} if isinstance(event,CallbackQuery) else {}))
