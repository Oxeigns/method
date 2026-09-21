import asyncio
import os
from pathlib import Path
from config import Config
from backend.database import open_database

async def main():
    cfg=Config.load('migration')
    if cfg.database_url:
        import asyncpg,ssl
        c=await asyncpg.connect(os.getenv('MIGRATION_DATABASE_URL') or cfg.database_url,
                                ssl=ssl.create_default_context() if cfg.production else 'prefer')
        try:
            await c.execute('SELECT pg_advisory_lock(83172916)')
            await c.execute(Path('migrations/001_postgres.sql').read_text())
        finally:await c.close()
    else:
        db=await open_database(cfg);await db.close()
if __name__=='__main__':asyncio.run(main())
