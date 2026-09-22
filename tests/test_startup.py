"""Exercise the real worker entry point with a temporary DB and mocked Telegram I/O."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from cryptography.fernet import Fernet
from config import Config

@pytest.mark.asyncio
async def test_core_polling_survives_optional_telethon_failure(monkeypatch,tmp_path):
    import main
    import backend.telethon_client
    cfg=Config(token='123:synthetic',admin_id=99,data_dir=tmp_path,
               keys=(Fernet.generate_key().decode(),),payment_mode='stars',support='',telethon_enabled=True)
    monkeypatch.setattr(main.Config,'load',lambda:cfg)
    bot=SimpleNamespace(delete_webhook=AsyncMock(),session=SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(main,'Bot',lambda *a,**k:bot)
    monkeypatch.setattr(backend.telethon_client,'start',AsyncMock(side_effect=ConnectionError('Synthetic MTProto outage')))
    async def idle(*args):await asyncio.Event().wait()
    for name in ['delivery_loop','deletion_loop','notify_loop','broadcast_engine','receipt_loop','snapshot_loop']:
        monkeypatch.setattr(main,name,idle)
    polling=AsyncMock()
    monkeypatch.setattr(main,'poll',polling)
    await main.main()
    polling.assert_awaited_once()
    bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=False)
    bot.session.close.assert_awaited_once()
