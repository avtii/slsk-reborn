"""Render README screenshots from the offline demo: python docs/make_screenshots.py"""
import asyncio
import tempfile
from pathlib import Path

from slsk_reborn.app import SlskApp
from slsk_reborn.config import Config
from slsk_reborn.panes.search import ResultsView

OUT = Path(__file__).parent


async def main():
    tmp = Path(tempfile.mkdtemp())
    cfg = Config(path=tmp / "c.toml", username="avt", password="x", download_dir=r"D:\Music\slsk-reborn")
    app = SlskApp(cfg, demo=True)
    async with app.run_test(size=(150, 42)) as pilot:
        while not app.engine.connected:
            await pilot.pause(0.1)
        for q in ("boards of canada", "burial"):
            app.query_one("#search-input").focus()
            app.query_one("#search-input").value = q
            await pilot.press("enter")
            await pilot.pause(0.3)
        await pilot.pause(3)
        view = app.query(ResultsView).last()
        view.sort = "quality"
        view.rebuild()
        view.query_one("DataTable").focus()
        await pilot.press("down", "down", "down")
        await pilot.pause(0.5)
        app.save_screenshot("search.svg", str(OUT))

        await pilot.press("f")
        await pilot.press("down", "down", "down", "down", "down", "down", "down", "down", "d")
        await pilot.press("down", "down", "d", "down", "d")
        await pilot.pause(6)
        await pilot.press("2")
        await pilot.pause(1)
        app.save_screenshot("transfers.svg", str(OUT))

        app.browse_user("vinylhoarder")
        await pilot.pause(1.5)
        await pilot.pause(0.3)
        app.save_screenshot("browse.svg", str(OUT))

        await pilot.press("4")
        app.query_one("ChatPane").join("electronic")
        await pilot.pause(0.5)
        app.query_one("ChatPane").switch("pm", "flac_monk")
        app.query_one("ChatPane").deliver("pm", "flac_monk", "hey! thanks for sharing that Untrue rip")
        app.query_one("ChatPane").switch("room", "electronic")
        await pilot.pause(9)
        app.save_screenshot("chat.svg", str(OUT))

        await pilot.press("f6")
        await pilot.pause(0.5)
        app.save_screenshot("shares.svg", str(OUT))
        app.action_help()
        await pilot.pause(0.5)
        app.save_screenshot("help.svg", str(OUT))
        await app.engine.stop()

    # first start: login screen
    app = SlskApp(Config(path=tmp / "new.toml"), demo=False)
    async with app.run_test(size=(150, 42)) as pilot:
        await pilot.pause(0.5)
        app.save_screenshot("login.svg", str(OUT))


asyncio.run(main())
