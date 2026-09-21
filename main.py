"""Entrypoint: python main.py. Secrets and research never enter application logs."""
import asyncio
import logging
import signal
import fcntl
from aiogram import Bot,Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import SimpleEventIsolation
from backend.database import open_database
from backend.broadcast import loop as broadcast_engine
from backend.http import TelegramTransport
from backend.logging import configure
import aiohttp
from bot.storage import SQLiteStorage
from bot.rate import RateLimiter
from aiogram.types import ErrorEvent
from bot.config import Config
from bot.crypto import VaultCipher
from bot.db import Store
from bot.middleware import Guard
from bot import admin,user,content
from bot.workers import delivery_loop,deletion_loop,notify_loop,receipt_loop
from bot.polling import poll
from bot.system_backup import snapshot_loop

async def main():
    cfg=Config.load()
    cipher=VaultCipher(cfg.keys)
    pool=await open_database(cfg)
    lockfile=None;lockconn=None
    if cfg.database_url:
        lockconn=await pool.pool.acquire()
        if not await lockconn.fetchval('SELECT pg_try_advisory_lock(73190481923)'):
            raise RuntimeError('Another bot worker holds the database lock.')
    else:
        lockfile=open(cfg.data_dir/'process.lock','a')
        try:fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another bot is running against this data directory.')
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
    http=aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35),connector=aiohttp.TCPConnector(limit=30))
    transport=TelegramTransport(cfg.token,http)
    telethon=None;sender=transport
    async def watch_lock():
        while True:
            if lockconn:await lockconn.fetchval('SELECT 1')
            await asyncio.sleep(10)
    try:
        if cfg.telethon_enabled:
            from backend.telethon_client import start
            telethon,sender=await start(cfg,store,cipher,transport)
        # Preserve pending receipts; never use drop_pending_updates=True.
        await bot.delete_webhook(drop_pending_updates=False)
        tasks=[asyncio.create_task(fn) for fn in (
            delivery_loop(bot,store,cipher), deletion_loop(bot,store),
            notify_loop(bot,store,cfg),broadcast_engine(store,cipher,sender,cfg.broadcast_rate),
            watch_lock(),receipt_loop(bot,store,cfg),poll(bot,dp,store,cfg,cipher),stop.wait())]
        if not cfg.database_url:tasks.append(asyncio.create_task(snapshot_loop(store,cipher,cfg)))
        if telethon:tasks.append(asyncio.create_task(telethon.run_until_disconnected()))
        done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await storage.close()
        await bot.session.close()
        if telethon:await telethon.disconnect()
        await http.close()
        if lockconn:await pool.pool.release(lockconn)
        await pool.close()
        if lockfile:lockfile.close()

if __name__=='__main__':
    configure()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
