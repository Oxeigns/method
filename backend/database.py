"""Async connection pools with per-task transactions; Flask uses one persistent loop."""
import asyncio
import re
import ssl
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from bot.sqlite import SQLite,params,row

# All application queries are parameterized. Only these known dialect expressions differ.
def postgres_sql(sql):
    return sql.replace('max(now(),','greatest(now(),').replace('now()','extract(epoch from clock_timestamp())')

class Postgres:
    dialect='postgres'
    def __init__(self,pool,connection=None):self.pool,self.connection=pool,connection
    @classmethod
    async def open(cls,cfg):
        import asyncpg
        async def init(c):
            await c.set_type_codec('numeric',encoder=str,decoder=float,schema='pg_catalog',format='text')
        tls=ssl.create_default_context() if cfg.production else 'prefer'
        pool=await asyncpg.create_pool(cfg.database_url,min_size=1,max_size=cfg.pool_max,ssl=tls,
                                      command_timeout=20,statement_cache_size=0,
                                      server_settings={'search_path':'method,pg_catalog'},init=init)
        return cls(pool)
    @asynccontextmanager
    async def acquire(self):
        if self.connection:
            yield self;return
        async with self.pool.acquire() as c:yield Postgres(self.pool,c)
    @asynccontextmanager
    async def transaction(self):
        async with self.acquire() as c:
            async with c.connection.transaction():yield c
    def values(self,args):
        return [int(v) if isinstance(v,bool) else v for v in params(args).values()]
    async def execute(self,sql,*args):
        async with self.acquire() as c:return await c.connection.execute(postgres_sql(sql),*self.values(args))
    async def fetch(self,sql,*args):
        async with self.acquire() as c:return [row(r) for r in await c.connection.fetch(postgres_sql(sql),*self.values(args))]
    async def fetchrow(self,sql,*args):
        async with self.acquire() as c:return row(await c.connection.fetchrow(postgres_sql(sql),*self.values(args)))
    async def fetchval(self,sql,*args):
        result=await self.fetchrow(sql,*args)
        return next(iter(result.values())) if result else None
    async def close(self):await self.pool.close()

async def open_database(cfg):
    if cfg.database_url:return await Postgres.open(cfg)
    return await SQLite.open(cfg.data_dir/'research.sqlite3')
