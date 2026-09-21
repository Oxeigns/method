"""Optional: initialize local storage. main.py does this automatically."""
import asyncio
from bot.config import Config
from bot.sqlite import SQLite
async def main():
    cfg=Config.load()
    db=await SQLite.open(cfg.data_dir/'research.sqlite3')
    await db.close()
    print('Local storage initialized.')
if __name__=='__main__':asyncio.run(main())
