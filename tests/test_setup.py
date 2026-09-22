from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from backend import setup


def test_setup_only_when_hosted_and_database_missing(monkeypatch):
    monkeypatch.setattr(setup, 'load_dotenv', lambda: None)
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.delenv('DATABASE_URL', raising=False)
    assert setup.pending()
    monkeypatch.setenv('DATABASE_URL', 'postgresql://configured')
    assert not setup.pending()
    monkeypatch.delenv('DATABASE_URL')
    monkeypatch.setenv('APP_ENV', 'local')
    monkeypatch.delenv('DYNO', raising=False)
    assert not setup.pending()


def test_owner_requires_private_chat():
    msg = SimpleNamespace(from_user=SimpleNamespace(id=99), chat=SimpleNamespace(type='private'))
    assert setup.authorized(msg, 99)
    assert not setup.authorized(msg, 98)
    msg.chat.type = 'supergroup'
    assert not setup.authorized(msg, 99)


def test_setup_web_disables_sales():
    client = setup.web_app().test_client()
    assert client.get('/health').json == {'status': 'setup_required', 'payments_enabled': False}
    assert client.post('/api/transactions').status_code == 503
    assert client.get('/').status_code == 200


@pytest.mark.asyncio
async def test_worker_and_release_need_no_database_in_setup(monkeypatch):
    import main
    import backend.migrate
    monkeypatch.setattr(setup, 'pending', lambda: True)
    runner = AsyncMock()
    monkeypatch.setattr(setup, 'run', runner)
    monkeypatch.setattr(main.Config, 'load', lambda *a: pytest.fail('Setup must not open the database'))
    await main.main()
    await backend.migrate.main()
    runner.assert_awaited_once()
