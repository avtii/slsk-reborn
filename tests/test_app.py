"""Drive the whole UI against the offline demo engine."""
import asyncio
from pathlib import Path

import pytest

from slsk_reborn.app import SlskApp
from slsk_reborn.config import Config
from slsk_reborn.panes.search import ResultsView, matches
from slsk_reborn.engine import Hit


@pytest.fixture
def cfg(tmp_path):
    return Config(path=tmp_path / "config.toml", username="tester", password="x",
                  download_dir=str(tmp_path / "dl"))


async def _wait(pilot, cond, timeout=8.0):
    t = 0.0
    while not cond():
        await pilot.pause(0.1)
        t += 0.1
        if t > timeout:
            raise AssertionError("condition not met in time")


async def test_search_download_flow(cfg):
    app = SlskApp(cfg, demo=True)
    async with app.run_test(size=(160, 45)) as pilot:
        await _wait(pilot, lambda: app.engine.connected)
        await pilot.press(*"aphex", "enter")
        await _wait(pilot, lambda: app.query(ResultsView) and app.query_one(ResultsView).hits)
        view = app.query_one(ResultsView)
        await _wait(pilot, lambda: view.query_one("DataTable").row_count > 0)
        view.query_one("DataTable").focus()
        await pilot.press("d")
        await _wait(pilot, lambda: app.engine.transfers())
        await pilot.press("f")  # whole folder
        await _wait(pilot, lambda: len(app.engine.transfers()) > 3)
        await pilot.press("2")
        await pilot.pause(1.0)
        assert app.query_one("#downloads").row_count >= 4
        await pilot.press("s")  # sort works without crashing
        await pilot.press("1")
        view.query_one(".flt").value = "flac"
        await pilot.pause(0.3)


async def test_browse_chat_shares(cfg):
    app = SlskApp(cfg, demo=True)
    async with app.run_test(size=(160, 45)) as pilot:
        await _wait(pilot, lambda: app.engine.connected)
        app.browse_user("flac_monk")
        await _wait(pilot, lambda: app.query_one("BrowsePane").folders)
        app.query_one("#browse-tree").focus()
        await pilot.press("d")
        await _wait(pilot, lambda: len(app.engine.transfers()) >= 5)

        await pilot.press("4")
        app.query_one("ChatPane").join("electronic")
        await _wait(pilot, lambda: app.query_one("ChatPane").active)
        inp = app.query_one("#chat-input")
        inp.focus()
        await pilot.press(*"hello", "enter")
        await pilot.press(*"/msg kassette hi", "enter")
        await pilot.pause(0.5)
        assert len(app.query_one("ChatPane").convs) == 2

        await pilot.press("escape")
        app.query_one("#main").active = "shares"
        await pilot.pause(0.2)
        app.query_one("#set-slots").value = "5"
        app.query_one("#set-save").press()
        await pilot.pause(0.3)
        assert Config.load(cfg.path).upload_slots == 5


async def test_modals(cfg):
    app = SlskApp(cfg, demo=True)
    async with app.run_test(size=(160, 45)) as pilot:
        await _wait(pilot, lambda: app.engine.connected)
        app.show_user("lowpass")
        await pilot.pause(1.0)
        await pilot.press("escape")
        app.action_help()
        await pilot.pause(0.2)
        await pilot.press("escape")
        app.pick_room()
        await pilot.pause(0.5)
        await pilot.press("enter")
        await _wait(pilot, lambda: app.query_one("ChatPane").active)
        app.action_cycle_theme()


async def test_login_prompt(tmp_path):
    cfg = Config(path=tmp_path / "c.toml")
    app = SlskApp(cfg, demo=False)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        assert app.screen.__class__.__name__ == "LoginScreen"
        await pilot.press("escape")


def test_filter():
    h = Hit("u", r"Music\Burial\Untrue\01 - Archangel.flac", 10, "flac", 1000)
    assert matches(h, "archangel flac")
    assert not matches(h, "archangel -burial")
    assert matches(h, ">320")
    assert not matches(h, "mp3")


def test_config_roundtrip(tmp_path):
    c = Config(path=tmp_path / "c.toml", username='we"ird', shared_dirs=[r"C:\a b", "/x"])
    c.save()
    d = Config.load(tmp_path / "c.toml")
    assert d.username == 'we"ird' and d.shared_dirs == [r"C:\a b", "/x"]
