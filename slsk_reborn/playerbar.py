"""Now-playing bar: one line above the footer, visible while something plays."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from .player import Player


def clock(sec: float) -> str:
    sec = int(max(sec, 0))
    h, rem = divmod(sec, 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60}:{rem % 60:02d}"


class PlayerBar(Static):
    def on_mount(self) -> None:
        self.display = False
        self._shown_error = ""
        self.set_interval(0.25, self.tick)

    @property
    def player(self) -> Player:
        return self.app.player

    def tick(self) -> None:
        p = self.player
        p.poll()
        if p.error and p.error != self._shown_error:
            self._shown_error = p.error
            self.app.notify(p.error, title="Player", severity="warning", timeout=8)
        self.display = p.track is not None and p.state != "stopped"
        if self.display:
            self.update(self.bar_text(self.size.width or 100))

    def bar_text(self, width: int) -> Text:
        p = self.player
        tr = p.track
        icon, color = {"playing": ("▶", "#39ff88"), "paused": ("❚❚", "#ffd23f")}.get(p.state, ("■", "#ff4d6d"))
        head = Text()
        head.append(f" {icon} ", f"bold black on {color}")
        head.append(" ")
        if tr.artist:
            head.append(tr.artist, "bold #ff2bd6")
            head.append(" — ", "dim")
        head.append(tr.title, "bold")
        if tr.album:
            head.append(f"  {tr.album}", "dim italic")

        pos, dur = p.position, tr.duration
        tail = Text()
        tail.append(f"  {clock(pos)}", "bold #00e5ff")
        if dur:
            tail.append(f" / {clock(dur)}", "dim")
        vol = int(round(p.volume * 10))
        tail.append("   vol ", "dim")
        tail.append("▮" * vol, "#ff2bd6")
        tail.append("▯" * (10 - vol), "dim")
        if len(p.queue) > 1:
            tail.append(f"   {p.index + 1}/{len(p.queue)}", "#b388ff")
        if not p.native:
            tail.append("   ext", "dim")
        tail.append(" ")

        # the progress bar gets what's left, the title gives way first
        bar_w = max(12, min(48, width - tail.cell_len - 34))
        head.truncate(max(10, width - tail.cell_len - bar_w - 2), overflow="ellipsis")
        line = Text()
        line.append_text(head)
        line.append(" " * max(1, width - head.cell_len - bar_w - tail.cell_len - 1))
        frac = min(pos / dur, 1.0) if dur else 0.0
        filled = int(frac * (bar_w - 1))
        line.append("━" * filled, color)
        line.append("●", f"bold {color}")
        line.append("─" * (bar_w - 1 - filled), "dim")
        line.append_text(tail)
        return line
