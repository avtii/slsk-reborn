from unittest.mock import AsyncMock

from aioslsk.client import SoulSeekClient
from aioslsk.events import ServerReconnectedEvent

from slsk_reborn.config import Config
from slsk_reborn.engine import Bus, SlskEngine


async def test_one_login_per_reconnect(tmp_path, monkeypatch):
    cfg = Config(username="tester", password="test", path=tmp_path / "config.toml",
                 download_dir=str(tmp_path / "downloads"))
    engine = SlskEngine(cfg, Bus())
    monkeypatch.setattr(SoulSeekClient, "start", AsyncMock())
    login = AsyncMock()
    monkeypatch.setattr(SoulSeekClient, "login", login)

    await engine.start()
    login.assert_awaited_once()
    login.reset_mock()

    await engine.client.events.emit(ServerReconnectedEvent())
    login.assert_awaited_once()
