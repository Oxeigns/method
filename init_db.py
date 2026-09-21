"""Compatibility entry point for local and PostgreSQL schema initialization."""
import asyncio
from backend.migrate import main
if __name__=='__main__':asyncio.run(main())
