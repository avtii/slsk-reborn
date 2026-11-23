"""Command line entry point: `slsk-reborn`."""
from __future__ import annotations

import argparse
import logging
import tempfile
from pathlib import Path

from . import __version__
from .config import HOME, Config


def port_number(text: str) -> int:
    """Listening port; the next port up (port+1) is used for obfuscated connections."""
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not 1 <= n <= 65534:
        raise argparse.ArgumentTypeError("port must be 1-65534 (port+1 is used too)")
    return n


def build_config(argv: list[str] | None = None) -> tuple[argparse.Namespace, Config]:
    p = argparse.ArgumentParser(prog="slsk-reborn", description="Terminal Soulseek client.")
    p.add_argument("--config", type=Path, help=f"config file (default {HOME / 'config.toml'})")
    p.add_argument("--demo", action="store_true", help="offline demo network, nothing is sent anywhere")
    p.add_argument("-p", "--port", type=port_number, metavar="N",
                   help="listening port for peer connections, overrides the config for this run "
                        "(default 61000; N+1 is used for obfuscated connections)")
    p.add_argument("--theme", choices=["slsk-neon", "slsk-amber", "slsk-matrix"])
    p.add_argument("--debug", action="store_true", help="verbose log in the data folder")
    p.add_argument("--version", action="version", version=f"slsk-reborn {__version__}")
    p.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    a = p.parse_args(argv)

    if a.demo or a.self_test:
        cfg = Config(path=Path(tempfile.gettempdir()) / "slsk-reborn-demo" / "config.toml",
                     username="you", password="demo")
    else:
        cfg = Config.load(a.config)
    if a.theme:
        cfg.theme = a.theme
    if a.port:
        cfg.listen_port = a.port
    return a, cfg


def main(argv: list[str] | None = None) -> None:
    a, cfg = build_config(argv)

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=cfg.data_dir / "slsk-reborn.log", encoding="utf-8",
                        level=logging.DEBUG if a.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not a.debug:
        logging.getLogger("aioslsk").setLevel(logging.WARNING)

    if a.self_test:
        raise SystemExit(self_test(cfg))

    from .app import SlskApp
    SlskApp(cfg, demo=a.demo).run()


def self_test(cfg: Config) -> int:
    """Headless smoke test for packaged builds: real-engine imports and settings
    (no network), then a demo login, search and results."""
    import asyncio
    import importlib

    from .app import SlskApp
    from .engine import Bus, SlskEngine
    from .panes.search import ResultsView

    for mod in ("aioslsk.client", "aioslsk.events", "aioslsk.naming", "aioslsk.shares.cache",
                "aioslsk.transfer.cache", "aioslsk.transfer.model", "aioslsk.commands", "aioslsk.protocol.primitives"):
        importlib.import_module(mod)
    SlskEngine(cfg, Bus())._settings()

    async def run() -> int:
        app = SlskApp(cfg, demo=True)
        async with app.run_test(size=(140, 40)) as pilot:
            for _ in range(100):
                if app.engine.connected:
                    break
                await pilot.pause(0.05)
            app.query_one("#search-input").value = "burial"
            await pilot.press("enter")
            for _ in range(100):
                views = app.query(ResultsView)
                if views and views.first().table.row_count:
                    break
                await pilot.pause(0.05)
            n = app.query_one(ResultsView).table.row_count if app.query(ResultsView) else 0
            await app.engine.stop()
        print(f"slsk-reborn {__version__} self-test: {n} results", "OK" if n else "FAILED")
        return 0 if n else 1

    return asyncio.run(run())


if __name__ == "__main__":
    main()
