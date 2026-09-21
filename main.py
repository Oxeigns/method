"""Entrypoint: python main.py. Secrets and research never enter application logs."""
import asyncio
import logging
import signal
import fcntl
from aiogram import Bot,Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import SimpleEventIsolation
from bot.sqlite import SQLite
from bot.storage import SQLiteStorage
from bot.rate import RateLimiter
from aiogram.types import ErrorEvent
from bot.config import Config
from bot.crypto import VaultCipher
from bot.db import Store
from bot.middleware import Guard
from bot import admin,user,content
from bot.workers import delivery_loop,deletion_loop,notify_loop,broadcast_loop,receipt_loop
from bot.polling import poll
from bot.system_backup import snapshot_loop

async def main():
    cfg=Config.load()
    cipher=VaultCipher(cfg.keys)
    lockfile=open(cfg.data_dir/'process.lock','a')
    try:fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Another bot is running against this data directory.')
    pool=await SQLite.open(cfg.data_dir/'research.sqlite3')
    storage=SQLiteStorage(pool)
    dp=Dispatcher(storage=storage,events_isolation=SimpleEventIsolation())
    bot=Bot(cfg.token,default=DefaultBotProperties(parse_mode='HTML',protect_content=True))
    store=Store(pool)
    guard=Guard(store,cfg,RateLimiter())
    for observer in (dp.message,dp.callback_query,dp.pre_checkout_query):
        observer.outer_middleware(guard)
    dp.include_routers(admin.confirm_router,user.router,content.router,admin.router)

    @dp.errors()
    async def error(event: ErrorEvent):
        # Avoid exception strings/traces: upstream errors can include message content.
        logging.error('Update failed type=%s update_id=%s',type(event.exception).__name__,event.update.update_id)
        try:
            if event.update.callback_query:
                await event.update.callback_query.answer('Action failed. Retry or contact /support.',show_alert=True)
            elif event.update.message:
                await event.update.message.answer('Action failed. Retry or contact /support. Existing payments remain recorded.')
        except Exception:
            pass
        return True

    stop=asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM,stop.set)
    tasks=[]
    try:
        # Preserve pending receipts; never use drop_pending_updates=True.
        await bot.delete_webhook(drop_pending_updates=False)
        tasks=[asyncio.create_task(fn) for fn in (
            delivery_loop(bot,store,cipher), deletion_loop(bot,store),
            notify_loop(bot,store,cfg),broadcast_loop(bot,store,cipher),
            snapshot_loop(store,cipher,cfg),receipt_loop(bot,store,cfg),poll(bot,dp,store,cfg,cipher),stop.wait())]
        done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await storage.close()
        await bot.session.close()
        await pool.close()
        lockfile.close()

if __name__=='__main__':
    logging.basicConfig(level=logging.WARNING,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
