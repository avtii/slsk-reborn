from unittest.mock import AsyncMock

import pytest
from aioslsk.client import SoulSeekClient

from slsk_reborn.app import SlskApp
from slsk_reborn.config import Config
from slsk_reborn.engine import Bus, SlskEngine


@pytest.mark.parametrize("explicit", [False, True])
async def test_live_download_share(tmp_path, monkeypatch, explicit):
    downloads = tmp_path / "music"
    downloads.mkdir()
    cfg = Config(path=tmp_path / "config.toml", download_dir=str(downloads),
                 shared_dirs=[str(downloads)] if explicit else [])
    engine = SlskEngine(cfg, Bus())

    async def start_offline(client):
        client.shares.load_from_settings()

    monkeypatch.setattr(SoulSeekClient, "start", start_offline)
    monkeypatch.setattr(SoulSeekClient, "login", AsyncMock())
    await engine.start()
    assert engine.client.shares.is_directory_shared(str(downloads))

    cfg.download_dir = str(tmp_path / "next-session")
    cfg.share_downloads = False
    await engine.sync_download_share()
    assert engine.client.shares.is_directory_shared(str(downloads)) == explicit

    cfg.share_downloads = True
    await engine.sync_download_share()
    await engine.sync_download_share()
    assert [path for path, _ in engine.shared_dirs()] == [str(downloads)]


async def test_save_applies_download_share_checkbox(tmp_path):
    cfg = Config(path=tmp_path / "config.toml", download_dir=str(tmp_path / "music"))
    app = SlskApp(cfg, demo=True)
    async with app.run_test(size=(160, 45)) as pilot:
        app.query_one("#main").active = "shares"
        checkbox = app.query_one("#set-sharedl")
        for desired in (False, True):
            checkbox.value = desired
            app.query_one("#set-save").press()
            await pilot.pause()
            assert Config.load(cfg.path).share_downloads == desired
            assert (cfg.download_dir in dict(app.engine.shared_dirs())) == desired
