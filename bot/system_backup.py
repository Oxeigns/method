"""Daily encrypted local snapshots. External copies still required for disk loss."""
import asyncio
import logging
import os
import tempfile
import time
from datetime import datetime,timezone
from pathlib import Path

async def snapshot(store,cipher,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        raw=Path(tmp)/'snapshot.sqlite3'
        await store.pool.snapshot(raw)
        # Metadata and research ciphertext both get an outer encryption layer.
        blob=await asyncio.to_thread(cipher.cipher.encrypt,raw.read_bytes())
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        target=folder/f'system-{stamp}.backup'
        pending=target.with_suffix('.pending')
        pending.write_bytes(blob)
        os.replace(pending,target)
    for old in sorted(folder.glob('system-*.backup'))[:-7]:old.unlink()
    return target

async def snapshot_loop(store,cipher,config):
    folder=config.data_dir/'backups'
    while True:
        try:
            copies=list(folder.glob('system-*.backup')) if folder.exists() else []
            newest=max((p.stat().st_mtime for p in copies),default=0)
            if time.time()-newest>=86400:
                await snapshot(store,cipher,folder)
        except Exception as exc:
            logging.error('Local backup failed type=%s',type(exc).__name__)
        await asyncio.sleep(3600)
