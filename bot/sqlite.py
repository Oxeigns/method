"""SQLite persistence with real transactions and per-task connection ownership."""
import asyncio
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import aiosqlite

TIME_COLUMNS={'join_date','timestamp','expires_at','created_at','reviewed_at','next_attempt','due_at'}

def params(values):
    def adapt(v):
        if isinstance(v,uuid.UUID):return str(v)
        if isinstance(v,Decimal):return str(v)
        if isinstance(v,datetime):return v.timestamp()
        return v
    return {str(i):adapt(v) for i,v in enumerate(values,1)}

def row(record):
    if record is None:return None
    result=dict(record)
    for key in TIME_COLUMNS & result.keys():
        if result[key] is not None:result[key]=datetime.fromtimestamp(result[key],timezone.utc)
    return result

class SQLite:
    def __init__(self,conn,path):
        self.conn,self.path=conn,Path(path)
        self.lock=asyncio.Lock()
        self.owner=None

    @classmethod
    async def open(cls,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        c=await aiosqlite.connect(path,isolation_level=None)
        c.row_factory=sqlite3.Row
        await c.execute('PRAGMA journal_mode=WAL')
        await c.execute('PRAGMA synchronous=FULL')
        await c.execute('PRAGMA foreign_keys=ON')
        await c.execute('PRAGMA busy_timeout=5000')
        await c.create_function('now',0,time.time)
        await c.executescript(Path(__file__).parents[1].joinpath('schema.sql').read_text())
        return cls(c,path)

    @asynccontextmanager
    async def acquire(self):
        if self.owner is asyncio.current_task():
            yield self
            return
        async with self.lock:
            self.owner=asyncio.current_task()
            try:yield self
            finally:self.owner=None

    @asynccontextmanager
    async def transaction(self):
        async with self.acquire():
            await self.conn.execute('BEGIN IMMEDIATE')
            try:
                yield self
                await self.conn.commit()
            except BaseException:
                await self.conn.rollback()
                raise

    async def execute(self,sql,*values):
        async with self.acquire():
            async with self.conn.execute(sql,params(values)) as cursor:
                return f'{sql.lstrip().split()[0].upper()} {cursor.rowcount}'

    async def fetch(self,sql,*values):
        async with self.acquire():
            async with self.conn.execute(sql,params(values)) as cursor:
                return [row(r) for r in await cursor.fetchall()]

    async def fetchrow(self,sql,*values):
        async with self.acquire():
            async with self.conn.execute(sql,params(values)) as cursor:
                return row(await cursor.fetchone())

    async def fetchval(self,sql,*values):
        result=await self.fetchrow(sql,*values)
        return next(iter(result.values())) if result else None

    async def snapshot(self,path):
        # Use SQLite's backup API, not a raw copy of a database with a WAL file.
        async with self.acquire():
            async with aiosqlite.connect(path) as target:
                await self.conn.backup(target)

    async def close(self):
        await self.conn.close()
