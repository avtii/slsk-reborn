"""Command line entry point: `slsk-reborn`."""
from __future__ import annotations

import argparse
import logging
import tempfile
from pathlib import Path

from . import __version__
from .config import HOME, Config


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="slsk-reborn", description="Terminal Soulseek client.")
    p.add_argument("--config", type=Path, help=f"config file (default {HOME / 'config.toml'})")
    p.add_argument("--demo", action="store_true", help="offline demo network, nothing is sent anywhere")
    p.add_argument("--theme", choices=["slsk-neon", "slsk-amber", "slsk-matrix"])
    p.add_argument("--debug", action="store_true", help="verbose log in the data folder")
    p.add_argument("--version", action="version", version=f"slsk-reborn {__version__}")
    a = p.parse_args(argv)

    if a.demo:
        cfg = Config(path=Path(tempfile.gettempdir()) / "slsk-reborn-demo" / "config.toml",
                     username="you", password="demo")
    else:
        cfg = Config.load(a.config)
    if a.theme:
        cfg.theme = a.theme

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=cfg.data_dir / "slsk-reborn.log", encoding="utf-8",
                        level=logging.DEBUG if a.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not a.debug:
        logging.getLogger("aioslsk").setLevel(logging.WARNING)

    from .app import SlskApp
    SlskApp(cfg, demo=a.demo).run()


if __name__ == "__main__":
    main()
