from unittest.mock import AsyncMock, Mock

import pytest

from slsk_reborn.app import SlskApp
from slsk_reborn.config import Config


@pytest.mark.parametrize("failing_step", ["player", "config"])
async def test_quit_attempts_every_cleanup_step(tmp_path, monkeypatch, failing_step):
    app = SlskApp(Config(path=tmp_path / "config.toml"), demo=False)
    app._quitting = False  # normally set by on_mount
    app.player.set_volume(0.25)
    close = Mock(side_effect=OSError("device closed") if failing_step == "player" else None)
    save = Mock(side_effect=OSError("disk full") if failing_step == "config" else None)
    stop = AsyncMock()
    monkeypatch.setattr(app.player, "close", close)
    monkeypatch.setattr(app.cfg, "save", save)
    monkeypatch.setattr(app.engine, "stop", stop)
    monkeypatch.setattr(app, "query_one", Mock())
    monkeypatch.setattr(app, "notify", Mock())
    monkeypatch.setattr(app, "exit", Mock())

    await app.action_quit()

    close.assert_called_once()
    save.assert_called_once()
    stop.assert_awaited_once()
    app.exit.assert_called_once()
