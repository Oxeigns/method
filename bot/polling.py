"""Persist payment receipts before confirming update offsets to Telegram."""
import asyncio
import logging
from aiogram.exceptions import TelegramNetworkError,TelegramRetryAfter

async def poll(bot,dispatcher,store,config,cipher):
    offset=None
    while True:
        try:
            updates=await bot.get_updates(offset=offset,timeout=25,allowed_updates=dispatcher.resolve_used_update_types())
        except (TelegramNetworkError,TelegramRetryAfter) as exc:
            await asyncio.sleep(getattr(exc,'retry_after',3))
            continue
        for update in updates:
            message=update.message
            if message and message.successful_payment:
                p=message.successful_payment
                # If DB is down, hold the offset and retry. A crash causes Telegram
                # to replay the receipt; the charge ID deduplicates that replay.
                while True:
                    try:
                        await store.user(message.from_user)
                        await store.pool.execute('''INSERT INTO payment_receipts(charge_id,user_id,invoice_payload,currency,amount)
                        VALUES($1,$2,$3,$4,$5) ON CONFLICT(charge_id) DO NOTHING''',p.telegram_payment_charge_id,message.from_user.id,p.invoice_payload,p.currency,p.total_amount)
                        break
                    except Exception as exc:
                        logging.error('Receipt persistence retry type=%s',type(exc).__name__)
                        await asyncio.sleep(3)
            await dispatcher.feed_update(bot,update,store=store,config=config,cipher=cipher)
            offset=update.update_id+1
