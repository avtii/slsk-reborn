"""Themes and the gradient logo."""
from __future__ import annotations

from rich.text import Text
from textual.theme import Theme

NEON = Theme(
    name="slsk-neon",
    primary="#ff2bd6",
    secondary="#00e5ff",
    accent="#39ff88",
    warning="#ffd23f",
    error="#ff4d6d",
    success="#39ff88",
    foreground="#e8e3ff",
    background="#0d0a17",
    surface="#151024",
    panel="#1d1530",
    boost="#2a1f45",
    dark=True,
    variables={"block-cursor-background": "#ff2bd6", "footer-key-foreground": "#00e5ff"},
)

AMBER = Theme(
    name="slsk-amber",
    primary="#ffb000",
    secondary="#ff7a00",
    accent="#ffd966",
    warning="#ffd966",
    error="#ff5544",
    success="#c6ff00",
    foreground="#ffcc66",
    background="#120c02",
    surface="#1a1205",
    panel="#251a08",
    dark=True,
)

MATRIX = Theme(
    name="slsk-matrix",
    primary="#00ff66",
    secondary="#00b347",
    accent="#b3ffcc",
    warning="#e6ff00",
    error="#ff3355",
    success="#00ff66",
    foreground="#b3ffcc",
    background="#020a04",
    surface="#06140a",
    panel="#0a1f10",
    dark=True,
)

THEMES = [NEON, AMBER, MATRIX]

_GLYPHS = {
    "s": ("█▀▀", "▀▀█", "▀▀▀"), "l": ("█░░", "█░░", "▀▀▀"), "k": ("█░█", "█▀▄", "▀░▀"),
    "r": ("█▀▄", "█▀▄", "▀░▀"), "e": ("█▀▀", "█▀▀", "▀▀▀"), "b": ("█▀▄", "█▀▄", "▀▀░"),
    "o": ("█▀█", "█░█", "▀▀▀"), "n": ("█▀█", "█░█", "▀░▀"), " ": ("░", "░", "░"),
}

GRADIENT = ["#ff2bd6", "#e040fb", "#b388ff", "#7c8cff", "#40c4ff", "#00e5ff", "#39ff88"]


def logo(word: str = "slsk reborn", colors: list[str] | None = None) -> Text:
    colors = colors or GRADIENT
    rows = ["░", "░", "░"]
    for ch in word:
        g = _GLYPHS[ch]
        for i in range(3):
            rows[i] += g[i] + "░"
    width = len(rows[0])
    out = Text()
    for r, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == "░":
                out.append(ch, style="#2a1f45")
            else:
                out.append(ch, style=f"bold {colors[min(len(colors) - 1, x * len(colors) // width)]}")
        if r < 2:
            out.append("\n")
    return out


def mini_logo() -> Text:
    t = Text()
    for ch, c in zip("◢◤ slsk·reborn", ["#ff2bd6", "#00e5ff", ""] + GRADIENT + GRADIENT[::-1]):
        t.append(ch, style=f"bold {c}" if c else "")
    return t
