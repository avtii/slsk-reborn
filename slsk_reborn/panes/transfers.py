"""Transfers tab: downloads and uploads with live progress bars."""
from __future__ import annotations

import os
import subprocess
import sys

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from ..engine import Xfer
from ..util import bar, basename, eta, human_size, human_speed, short_dir, user_color

STATE_STYLE = {
    "transferring": ("▶", "bold #00e5ff"), "queued": ("…", "#b388ff"), "waiting": ("◷", "#ffd23f"),
    "done": ("✔", "bold #39ff88"), "failed": ("✖", "bold #ff4d6d"), "aborted": ("■", "#ff8c42"),
    "paused": ("❚❚", "#ffd23f"), "incomplete": ("↻", "#ff8c42"),
}


def open_path(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class TransferTable(DataTable):
    BINDINGS = [
        Binding("enter", "play", "Play"),
        Binding("p", "pause", "Pause"),
        Binding("r", "resume", "Resume/retry"),
        Binding("x", "abort", "Abort"),
        Binding("delete", "remove", "Remove"),
        Binding("c", "clear_done", "Clear finished"),
        Binding("o", "open", "Open folder"),
        Binding("b", "browse", "Browse user", show=False),
        Binding("i", "info", "User info", show=False),
    ]

    def __init__(self, upload: bool, **kw):
        super().__init__(cursor_type="row", zebra_stripes=True, **kw)
        self.upload = upload
        self.items: dict[str, Xfer] = {}
        self.file_width = 60

    def on_mount(self) -> None:
        self.add_column(" ", key="st", width=2)
        self.add_column("User", key="user", width=16)
        self.add_column("File", key="file", width=self.file_width)
        self.add_column("Progress", key="prog", width=26)
        self.add_column("Size", key="size", width=8)
        self.add_column("Speed", key="speed", width=9)
        self.add_column("Info", key="info", width=24)

    def on_resize(self) -> None:
        # File column takes whatever the fixed columns leave over
        fixed = 2 + 16 + 26 + 8 + 9 + 24 + 7 * 2 + 4
        w = max(20, self.size.width - fixed)
        if w != self.file_width:
            self.file_width = w
            from textual.widgets.data_table import ColumnKey
            col = self.columns.get(ColumnKey("file"))
            if col is not None:
                col.width = w
                col.auto_width = False
            for k, x in list(self.items.items()):
                self.update_cell(k, "file", self._cells(x)["file"])
            self.refresh()

    @staticmethod
    def _k(x: Xfer) -> str:
        return "\x1f".join(map(str, x.key))

    def _cells(self, x: Xfer) -> dict:
        icon, style = STATE_STYLE.get(x.state, ("?", ""))
        color = {"done": "#39ff88", "failed": "#ff4d6d", "paused": "#ffd23f"}.get(x.state, "#ff2bd6")
        if x.state == "transferring":
            left = eta(x.size - x.done, x.speed)
            info = Text(f"ETA {left}" if left else "starting…", "#7ab8ff")
        elif x.state in ("queued", "waiting"):
            info = Text(f"queued, place {x.place}" if x.place is not None else x.state, "#b388ff")
        elif x.reason:
            info = Text(x.reason, "#ff8c42")
        else:
            info = Text(x.state, style)
        f = Text(basename(x.path), "bold")
        f.append("  " + short_dir(x.path, 1), "dim")
        f.truncate(self.file_width, overflow="ellipsis")
        return {"st": Text(icon, style), "user": Text(x.user, user_color(x.user)), "file": f,
                "prog": bar(x.fraction, 16, color), "size": human_size(x.size or None),
                "speed": Text(human_speed(x.speed), "#00e5ff") if x.speed else Text("—", "dim"), "info": info}

    def sync(self, xfers: list[Xfer]) -> None:
        seen = set()
        for x in xfers:
            k = self._k(x)
            seen.add(k)
            cells = self._cells(x)
            if k in self.items:
                old = self.items[k]
                if (old.state, old.done, old.speed, old.place, old.size) != (x.state, x.done, x.speed, x.place, x.size):
                    for col, v in cells.items():
                        self.update_cell(k, col, v)
            else:
                self.add_row(*cells.values(), key=k)
            self.items[k] = x
        for k in list(self.items):
            if k not in seen:
                self.remove_row(k)
                del self.items[k]

    def current(self) -> Xfer | None:
        if not self.row_count:
            return None
        return self.items.get(self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value)

    @work
    async def _do(self, op: str, xs: list[Xfer]) -> None:
        for x in xs:
            try:
                await getattr(self.app.engine, op)(x.key)
            except Exception as e:
                self.notify(f"{op} failed: {e}", severity="warning")

    def action_pause(self):
        if (x := self.current()):
            self._do("pause", [x])

    def action_resume(self):
        if (x := self.current()):
            self._do("resume", [x])

    def action_abort(self):
        if (x := self.current()):
            self._do("abort", [x])

    def action_remove(self):
        if (x := self.current()):
            self._do("remove", [x])

    def action_clear_done(self):
        done = [x for x in self.items.values() if x.state in ("done", "aborted", "failed")]
        self._do("remove", done)
        self.notify(f"Cleared {len(done)} finished transfers")

    def action_play(self):
        x = self.current()
        if x is None:
            return
        if x.local_path and os.path.isfile(x.local_path) and (x.upload or x.state == "done"):
            self.app.play_file(x.local_path)
        elif not x.upload and x.state != "done":
            self.app.notify("Not downloaded yet", severity="warning")
        else:
            self.app.notify("File not found on disk", severity="warning")

    def action_open(self):
        x = self.current()
        path = os.path.dirname(x.local_path) if x and x.local_path else self.app.cfg.download_dir
        try:
            open_path(path)
        except Exception as e:
            self.notify(f"Can't open {path}: {e}", severity="warning")

    def action_browse(self):
        if (x := self.current()):
            self.app.browse_user(x.user, focus_path=x.path)

    def action_info(self):
        if (x := self.current()):
            self.app.show_user(x.user)


class TransfersPane(Vertical):
    def compose(self) -> ComposeResult:
        yield Static(id="dl-title", classes="section-title")
        yield TransferTable(False, id="downloads")
        yield Static(id="ul-title", classes="section-title")
        yield TransferTable(True, id="uploads")

    def on_mount(self) -> None:
        self._states: dict[tuple, str] | None = None  # None until the first refresh
        self._finished_batch = 0
        self.set_interval(0.5, self.refresh_data)
        self.refresh_data()

    def refresh_data(self) -> None:
        xs = self.app.engine.transfers()
        downs = [x for x in xs if not x.upload]
        self._announce(downs)
        ups = [x for x in xs if x.upload]
        self.query_one("#downloads", TransferTable).sync(downs)
        self.query_one("#uploads", TransferTable).sync(ups)
        d, u = self.app.engine.speeds()
        self.query_one("#dl-title", Static).update(self._title("▼ Downloads", downs, d, "#00e5ff"))
        self.query_one("#ul-title", Static).update(self._title("▲ Uploads", ups, u, "#ff2bd6"))

    def _announce(self, downs: list[Xfer]) -> None:
        """Toast finished/failed downloads; ring the bell once when the queue empties."""
        states = {x.key: x.state for x in downs}
        prev, self._states = self._states, states
        if prev is None or not self.app.cfg.notify_downloads:
            return  # don't announce transfers restored from the last session
        done = [x for x in downs if x.state == "done" and prev.get(x.key) != "done"]
        failed = [x for x in downs if x.state == "failed" and prev.get(x.key) != "failed"]
        self._finished_batch += len(done)
        if len(done) == 1:
            self.app.notify(basename(done[0].path), title="✔ Downloaded", timeout=4)
        elif done:
            self.app.notify(f"{len(done)} files", title="✔ Downloaded", timeout=4)
        for x in failed[:3]:
            self.app.notify(f"{basename(x.path)}: {x.reason or 'failed'}", title="✖ Download failed",
                            severity="warning", timeout=6)
        if self._finished_batch and not any(x.active for x in downs):
            n, self._finished_batch = self._finished_batch, 0
            self.app.bell()
            self.app.notify(f"{n} file{'s' if n != 1 else ''} in {short_dir(self.app.cfg.download_dir)}",
                            title="All downloads finished", timeout=8)

    @staticmethod
    def _title(name: str, xs: list[Xfer], speed: float, color: str) -> Text:
        t = Text()
        t.append(f" {name} ", f"bold black on {color}")
        act = sum(x.state == "transferring" for x in xs)
        q = sum(x.state in ("queued", "waiting") for x in xs)
        done = sum(x.state == "done" for x in xs)
        bad = sum(x.state in ("failed", "aborted") for x in xs)
        t.append(f"  {act} active", "bold")
        t.append(f" · {q} queued", "#b388ff")
        t.append(f" · {done} done", "#39ff88")
        if bad:
            t.append(f" · {bad} failed", "#ff4d6d")
        t.append(f"   {human_speed(speed)}", f"bold {color}")
        return t
