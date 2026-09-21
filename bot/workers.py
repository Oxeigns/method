"""Durable jobs. Run one polling instance; the DB singleton lock enforces this."""
import asyncio
import logging
from html import escape
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from .admin import send_verification

log=logging.getLogger(__name__)

def chunks(text,limit=3000):
    """Keep escaped HTML and UTF-16 size bounded, including emoji and ampersands."""
    current=[]
    size=0
    for character in text:
        cost=max(len(escape(character)),len(character.encode('utf-16-le'))//2)
        if current and size+cost>limit:
            yield ''.join(current)
            current=[]
            size=0
        current.append(character)
        size+=cost
    if current:
        yield ''.join(current)

async def deliver_one(bot,store,cipher,job):
    uid,sid=job['user_id'],job['service_id']
    if not await store.allowed(uid,sid):
        await store.pool.execute("UPDATE delivery_jobs SET status='blocked' WHERE job_id=$1",job['job_id'])
        return
    rows=await store.pool.fetch('SELECT data_id,encrypted_payload FROM vault_data WHERE service_id=$1 AND is_published=1 AND data_id>=$2 ORDER BY data_id',sid,job['data_cursor'])
    ttl=await store.pool.fetchval('SELECT delete_after_seconds FROM services WHERE service_id=$1',sid)
    for row in rows:
        text=cipher.decrypt(sid,row['encrypted_payload'])
        for index,part in enumerate(chunks(text)):
            if row['data_id']==job['data_cursor'] and index<job['chunk_cursor']:
                continue
            # Recheck entitlement for each block, never trust callbacks or queued jobs.
            if not await store.allowed(uid,sid):
                await store.pool.execute("UPDATE delivery_jobs SET status='blocked' WHERE job_id=$1",job['job_id'])
                return
            if not await store.pool.fetchval('SELECT EXISTS(SELECT 1 FROM vault_data WHERE data_id=$1 AND is_published=1 AND encrypted_payload=$2)',row['data_id'],row['encrypted_payload']):
                break
            msg=await bot.send_message(uid,f'<b>🔐 Private research • User {uid}</b>\n{escape(part)}',protect_content=True)
            async with store.pool.acquire() as c,c.transaction():
                await c.execute('INSERT INTO deletion_jobs(chat_id,message_id,due_at) VALUES($1,$2,now()+$3) ON CONFLICT DO NOTHING',uid,msg.message_id,float(ttl))
                await c.execute('UPDATE delivery_jobs SET data_cursor=$2,chunk_cursor=$3 WHERE job_id=$1',job['job_id'],row['data_id'],index+1)
            await asyncio.sleep(0.1)
        del text
    await store.pool.execute("UPDATE delivery_jobs SET status='done' WHERE job_id=$1",job['job_id'])

async def delivery_loop(bot,store,cipher):
    while True:
        try:
            job=await store.pool.fetchrow("SELECT * FROM delivery_jobs WHERE status='pending' AND next_attempt<=now() ORDER BY job_id LIMIT 1")
            if job:
                try:
                    await deliver_one(bot,store,cipher,job)
                except TelegramForbiddenError:
                    await store.pool.execute("UPDATE delivery_jobs SET status='blocked' WHERE job_id=$1",job['job_id'])
                except Exception as exc:
                    delay=exc.retry_after if isinstance(exc,TelegramRetryAfter) else min(3600,2**min(job['attempts']+2,11))
                    await store.pool.execute('UPDATE delivery_jobs SET attempts=attempts+1,next_attempt=now()+$2 WHERE job_id=$1',job['job_id'],float(delay))
                    log.warning('Delivery failed job=%s type=%s',job['job_id'],type(exc).__name__)
            else:
                await asyncio.sleep(2)
        except Exception as exc:
            log.error('Delivery worker unavailable type=%s',type(exc).__name__)
            await asyncio.sleep(5)

async def deletion_loop(bot,store):
    while True:
        try:
            jobs=await store.pool.fetch('SELECT * FROM deletion_jobs WHERE due_at<=now() ORDER BY due_at LIMIT 50')
            for j in jobs:
                try:
                    await bot.delete_message(j['chat_id'],j['message_id'])
                except TelegramBadRequest as exc:
                    # Already deleted is success. Other failures remain visible/retryable.
                    if 'message to delete not found' not in str(exc).lower():
                        raise
                await store.pool.execute('DELETE FROM deletion_jobs WHERE chat_id=$1 AND message_id=$2',j['chat_id'],j['message_id'])
        except Exception as exc:
            log.warning('Deletion failed type=%s; inspect overdue deletion_jobs',type(exc).__name__)
            if 'j' in locals():
                delay=exc.retry_after if isinstance(exc,TelegramRetryAfter) else 60
                await store.pool.execute('UPDATE deletion_jobs SET attempts=attempts+1,due_at=now()+$3 WHERE chat_id=$1 AND message_id=$2',j['chat_id'],j['message_id'],float(delay))
        await asyncio.sleep(10)

async def notify_loop(bot,store,config):
    while True:
        try:
            rows=await store.pool.fetch("SELECT * FROM transactions WHERE status='Pending' AND screenshot_file_id IS NOT NULL AND admin_notified=0 ORDER BY timestamp LIMIT 10")
            for t in rows:
                await send_verification(bot,config.admin_id,t)
                await store.pool.execute('UPDATE transactions SET admin_notified=1 WHERE txn_id=$1',t['txn_id'])
        except Exception as exc:
            log.warning('Admin notification failed type=%s',type(exc).__name__)
        await asyncio.sleep(2)

async def receipt_loop(bot,store,config):
    import uuid
    while True:
        try:
            rows=await store.pool.fetch("SELECT * FROM payment_receipts WHERE status='pending' ORDER BY created_at LIMIT 20")
            for r in rows:
                try:
                    await store.paid(r['user_id'],uuid.UUID(r['invoice_payload']),r['currency'],r['amount'],r['charge_id'])
                except ValueError:
                    # Keep unmatched money in a durable reconciliation queue, never discard it.
                    await store.pool.execute("UPDATE payment_receipts SET status='reconcile' WHERE charge_id=$1",r['charge_id'])
                    await bot.send_message(config.admin_id,'⚠️ A payment needs reconciliation. Inspect payment_receipts with status=reconcile and contact the payer. No automatic access was granted.')
                else:
                    await store.pool.execute("UPDATE payment_receipts SET status='processed' WHERE charge_id=$1",r['charge_id'])
        except Exception as exc:
            log.error('Receipt processing failed type=%s',type(exc).__name__)
        await asyncio.sleep(1)
