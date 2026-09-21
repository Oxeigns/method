"""Flask threads submit DB work to one long-lived event loop per web process."""
import asyncio,threading
from concurrent.futures import TimeoutError as FutureTimeout
from bot.db import Store
from bot.crypto import VaultCipher
from .database import open_database
class Bridge:
    def __init__(self,cfg):
        self.cfg=cfg;self.loop=asyncio.new_event_loop()
        self.thread=threading.Thread(target=self.loop.run_forever,daemon=True);self.thread.start()
        self.run(self.start())
    async def start(self):
        self.db=await open_database(self.cfg);self.store=Store(self.db);self.cipher=VaultCipher(self.cfg.keys)
    def run(self,coroutine):
        future=asyncio.run_coroutine_threadsafe(coroutine,self.loop)
        try:return future.result(timeout=25)
        except FutureTimeout:future.cancel();raise TimeoutError('Backend request timeout') from None
    def close(self):
        if self.loop.is_running():
            self.run(self.db.close());self.loop.call_soon_threadsafe(self.loop.stop);self.thread.join(timeout=5)
