"""User configuration stored as TOML in ~/.slsk-reborn/config.toml."""
from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

HOME = Path(os.environ.get("SLSK_REBORN_HOME", Path.home() / ".slsk-reborn"))


@dataclass
class Config:
    username: str = ""
    password: str = ""
    listen_port: int = 61000
    upnp: bool = True
    download_dir: str = str(Path.home() / "Music" / "slsk-reborn")
    incomplete_suffix: str = ""
    shared_dirs: list[str] = field(default_factory=list)
    share_downloads: bool = True
    upload_slots: int = 3
    upload_limit_kbps: int = 0
    download_limit_kbps: int = 0
    description: str = "slsk-reborn :: terminal Soulseek client"
    auto_join_rooms: list[str] = field(default_factory=list)
    search_timeout: int = 0
    min_bitrate: int = 0
    theme: str = "slsk-neon"
    welcomed: bool = False  # first-run sharing/ports notes were shown
    notify_downloads: bool = True  # toast per finished file, bell when the queue empties
    friends: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    wishlist: list[str] = field(default_factory=list)

    path: Path = field(default=HOME / "config.toml", repr=False, compare=False)

    @property
    def data_dir(self) -> Path:
        return self.path.parent

    @property
    def has_credentials(self) -> bool:
        return bool(self.username and self.password)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = Path(path) if path else HOME / "config.toml"
        cfg = cls(path=path)
        if path.exists():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            names = {f.name for f in fields(cls)} - {"path"}
            for k, v in data.items():
                if k in names:
                    setattr(cfg, k, v)
        return cfg

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data.pop("path", None)
        lines = ["# slsk-reborn configuration", ""]
        for k, v in data.items():
            lines.append(f"{k} = {_toml(v)}")
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


def _toml(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{s}"'
