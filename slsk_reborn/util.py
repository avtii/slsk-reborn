"""Formatting helpers shared by the panes."""
from __future__ import annotations

import re
import time

from rich.text import Text

LOSSLESS = {"flac", "wav", "aiff", "aif", "alac", "ape", "wv"}
AUDIO = LOSSLESS | {"mp3", "m4a", "aac", "ogg", "opus", "wma", "mpc"}

BAR_CHARS = " ▏▎▍▌▋▊▉█"


def human_size(n: int | float | None) -> str:
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if abs(n) < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit in ("B", "K") else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def human_speed(bps: float | None) -> str:
    if not bps:
        return "—"
    return human_size(bps) + "/s"


def human_duration(sec: int | float | None) -> str:
    if not sec:
        return ""
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def eta(remaining: int, speed: float) -> str:
    if speed <= 0 or remaining <= 0:
        return ""
    return human_duration(remaining / speed)


def split_path(path: str) -> list[str]:
    return [p for p in re.split(r"[\\/]", path) if p]


def basename(path: str) -> str:
    parts = split_path(path)
    return parts[-1] if parts else path


def dirname(path: str) -> str:
    i = max(path.rfind("\\"), path.rfind("/"))
    return path[:i] if i > 0 else ""


def short_dir(path: str, depth: int = 2) -> str:
    parts = split_path(dirname(path))
    return "/".join(parts[-depth:]) if parts else ""


def ext_of(path: str) -> str:
    name = basename(path)
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def quality_text(ext: str, bitrate: int | None) -> Text:
    """Colored quality badge: lossless glows, low bitrate fades."""
    ext = (ext or "?").lower()
    if ext in LOSSLESS:
        return Text(f" {ext.upper()} ", style="bold black on #39ff88")
    if bitrate:
        if bitrate >= 310:
            style = "bold #00e5ff"
        elif bitrate >= 250:
            style = "#7ab8ff"
        elif bitrate >= 192:
            style = "#c0c0c0"
        else:
            style = "dim #ff6b6b"
        return Text(f"{ext} {bitrate}", style=style)
    return Text(ext, style="dim")


def bar(fraction: float, width: int = 18, color: str = "#ff2bd6") -> Text:
    fraction = max(0.0, min(1.0, fraction))
    full = fraction * width
    whole = int(full)
    rem = int((full - whole) * (len(BAR_CHARS) - 1))
    s = "█" * whole
    if whole < width:
        s += BAR_CHARS[rem]
        s += " " * (width - whole - 1)
    t = Text(s, style=color)
    t.stylize("on #1d1530")
    t.append(f" {fraction * 100:5.1f}%", style="bold")
    return t


def clock(ts: float | None = None) -> str:
    return time.strftime("%H:%M", time.localtime(ts or time.time()))


def user_color(name: str) -> str:
    palette = ["#ff2bd6", "#00e5ff", "#39ff88", "#ffd23f", "#b388ff", "#ff8c42", "#4dd0e1", "#f06292"]
    return palette[sum(map(ord, name)) % len(palette)]
