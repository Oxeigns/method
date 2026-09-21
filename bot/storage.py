"""Persistent FSM: metadata and ciphertext only, never incoming raw research."""
import json
from dataclasses import asdict
from aiogram.fsm.storage.base import BaseStorage

class SQLiteStorage(BaseStorage):
    def __init__(self,pool):self.pool=pool
    def key(self,key):return json.dumps(asdict(key),sort_keys=True)
    async def set_state(self,key,state=None):
        value=state.state if hasattr(state,'state') else state
        await self.pool.execute('INSERT INTO fsm(storage_key,state) VALUES($1,$2) ON CONFLICT(storage_key) DO UPDATE SET state=excluded.state,updated_at=now()',self.key(key),value)
    async def get_state(self,key):
        return await self.pool.fetchval('SELECT state FROM fsm WHERE storage_key=$1 AND updated_at>now()-3600',self.key(key))
    async def set_data(self,key,data):
        await self.pool.execute('INSERT INTO fsm(storage_key,data) VALUES($1,$2) ON CONFLICT(storage_key) DO UPDATE SET data=excluded.data,updated_at=now()',self.key(key),json.dumps(data))
    async def get_data(self,key):
        value=await self.pool.fetchval('SELECT data FROM fsm WHERE storage_key=$1 AND updated_at>now()-3600',self.key(key))
        return json.loads(value) if value else {}
    async def close(self):pass
