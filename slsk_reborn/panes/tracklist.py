"""Tracklist import: search every track, queue the best file, follow each download."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from ..engine import Hit
from ..tracklist import GOOD_SCORE, Track, pick, queries_for
from ..util import basename

PARALLEL = 3          # tracks searched at once
SEARCH_WAIT = 10.0    # seconds of results to collect per query
COLS = [("#", "n", 3), ("Track", "track", 30), ("State", "state", 17), ("Picked file", "file", 30),
        ("Quality", "q", 9), ("User", "user", 16)]
STATE_STYLE = {"waiting": "dim", "searching": "#00e5ff", "not found": "bold #ff4d6d", "queued": "#ffd23f",
               "transferring": "#00e5ff", "done": "bold #39ff14", "failed": "bold #ff4d6d",
               "aborted": "#ff4d6d", "paused": "dim", "incomplete": "#ff4d6d", "skipped": "dim"}


@dataclass
class Row:
    track: Track
    state: str = "waiting"
    hit: Optional[Hit] = None
    results: int = 0
    note: str = ""
    task: Optional[asyncio.Task] = field(default=None, repr=False)


def quality(h: Hit) -> str:
    if h.ext in ("flac", "wav", "aiff", "aif", "alac", "ape", "wv"):
        return h.ext.upper()
    return f"{h.ext.upper()} {h.bitrate}" if h.bitrate else h.ext.upper()


class TracklistView(Vertical):
    """One ♫ tab in Search: a row per track."""

    BINDINGS = [
        Binding("enter", "manual", "Search this track"),
        Binding("r", "retry", "Retry track"),
        Binding("x", "stop", "Stop"),
        Binding("ctrl+w", "close", "Close tab"),
    ]

    def __init__(self, tracks: list[Track], prefer_lossless: bool = True, name: str = "tracklist", **kw):
        super().__init__(**kw)
        self.rows = [Row(t) for t in tracks]
        self.prefer_lossless = prefer_lossless
        self.title = name
        self.running = True
        self._sem = asyncio.Semaphore(PARALLEL)

    @property
    def label(self) -> str:
        return "♫ " + self.title

    def compose(self) -> ComposeResult:
        yield Static(id="tl-summary")
        yield DataTable(cursor_type="row", zebra_stripes=True, classes="results")

    def on_mount(self) -> None:
        dt = self.query_one(DataTable)
        for title, key, w in COLS:
            dt.add_column(title, key=key, width=w)
        for r in self.rows:
            dt.add_row(*self._cells(r), key=str(r.track.index))
        self._fit()
        self.set_interval(1.0, self._refresh)
        self._summary()
        for r in self.rows:
            r.task = asyncio.create_task(self._run(r))

    def on_resize(self) -> None:
        self._fit()

    def _fit(self) -> None:
        from textual.widgets.data_table import ColumnKey
        dt = self.query_one(DataTable)
        fixed = sum(w for _, k, w in COLS if k not in ("track", "file")) + 2 * len(COLS) + 2
        free = max(40, self.size.width - fixed)
        for key, w in (("track", free * 2 // 5), ("file", free - free * 2 // 5)):
            col = dt.columns.get(ColumnKey(key))
            if col is not None:
                col.width, col.auto_width = w, False
        dt.refresh()

    # ------------------------------------------------------------------ work
    async def _run(self, r: Row) -> None:
        async with self._sem:
            if not self.running:
                return
            r.state, r.note = "searching", ""
            self._update(r)
            engine, bus = self.app.engine, self.app.bus
            best: Optional[Hit] = None
            for q in queries_for(r.track):
                best_score = float("-inf")
                tk: Optional[int] = None

                def collect(ticket: int, hits: list[Hit]) -> None:
                    nonlocal best, best_score
                    if ticket == tk:
                        r.results += len(hits)
                        candidate, score = pick(hits, r.track, self.prefer_lossless)
                        if candidate is not None and score > best_score:
                            best, best_score = candidate, score

                bus.on("search.hits", collect)
                try:
                    tk = await engine.search(q)
                    for _ in range(int(SEARCH_WAIT / 0.5)):
                        await asyncio.sleep(0.5)
                        if best_score >= GOOD_SCORE:
                            break
                except Exception as e:
                    r.state, r.note = "failed", type(e).__name__
                    self._update(r)
                    self._summary()
                    return
                finally:
                    bus.off("search.hits", collect)
                    if tk is not None:
                        engine.stop_search(tk)
                if best is not None or not self.running:
                    break
            if not self.running:
                r.state = "skipped"
            elif best is None:
                r.state = "not found"
            else:
                r.hit = best
                try:
                    await engine.download(best.user, best.path, best.size)
                    r.state = "queued"
                except Exception as e:
                    r.state, r.note = "failed", f"{type(e).__name__}"
            self._update(r)
            self._summary()

    def _refresh(self) -> None:
        """Follow the queued downloads in Transfers."""
        xfers = {(x.user, x.path): x for x in self.app.engine.transfers() if not x.upload}
        changed = False
        for r in self.rows:
            if r.hit is None or r.state in ("searching", "not found"):
                continue
            x = xfers.get((r.hit.user, r.hit.path))
            if x is None:
                continue
            state = x.state if x.state in STATE_STYLE and x.state != "waiting" else "queued"
            note = f"{x.fraction:.0%}" if state == "transferring" else ""
            if (state, note) != (r.state, r.note):
                r.state, r.note = state, note
                self._update(r)
                changed = True
        if changed:
            self._summary()

    # ------------------------------------------------------------------ display
    def _cells(self, r: Row):
        st = Text(r.state, STATE_STYLE.get(r.state, ""))
        if r.note:
            st.append(f" {r.note}", "dim")
        h = r.hit
        return (Text(str(r.track.index), "dim"), r.track.label, st,
                Text(basename(h.path)) if h else Text("—", "dim"),
                Text(quality(h), "bold #ff2bd6" if h.ext == "flac" else "") if h else "",
                Text(h.user, "#00e5ff") if h else "")

    def _update(self, r: Row) -> None:
        try:
            dt = self.query_one(DataTable)
            for (_, key, _), cell in zip(COLS, self._cells(r)):
                dt.update_cell(str(r.track.index), key, cell)
        except Exception:
            pass  # tab closed meanwhile

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows:
            out[r.state] = out.get(r.state, 0) + 1
        return out

    def _summary(self) -> None:
        c = self.counts()
        n = len(self.rows)
        busy = c.get("waiting", 0) + c.get("searching", 0)
        s = Text()
        s.append(f" ♫ {self.title} ", "bold reverse")
        s.append(f"  {n} tracks   ")
        s.append(f"✔ {c.get('done', 0)} done   ", "#39ff14")
        got = sum(c.get(k, 0) for k in ("queued", "transferring", "paused"))
        s.append(f"↓ {got} downloading   ", "#ffd23f")
        if c.get("not found") or c.get("failed"):
            s.append(f"✖ {c.get('not found', 0) + c.get('failed', 0)} missing   ", "#ff4d6d")
        if busy and self.running:
            s.append(f"searching… {busy} left", "#00e5ff")
        elif not self.running:
            s.append("stopped", "dim")
        s.append("\n enter: search a track yourself · r: retry · x: stop", "dim")
        try:
            self.query_one("#tl-summary", Static).update(s)
            self.app.query_one("SearchPane").refresh_tab_label(self)
        except Exception:
            pass

    # ------------------------------------------------------------------ actions
    def _row(self) -> Optional[Row]:
        dt = self.query_one(DataTable)
        if not self.rows or dt.cursor_row is None:
            return None
        return self.rows[dt.cursor_row]

    @on(DataTable.RowSelected)
    def _selected(self, e: DataTable.RowSelected) -> None:
        e.stop()
        self.action_manual()

    def action_manual(self) -> None:
        if (r := self._row()):
            q = (queries_for(r.track) or [r.track.label])[0]
            self.app.query_one("SearchPane").new_search(q)

    def action_retry(self) -> None:
        r = self._row()
        if r is None or r.state in ("searching", "waiting"):
            return
        if r.state in ("queued", "transferring", "done") and r.hit:
            self.notify("Already downloading. Use n in Transfers for another source.", severity="warning")
            return
        self.running = True
        r.hit, r.results, r.state = None, 0, "waiting"
        self._update(r)
        r.task = asyncio.create_task(self._run(r))

    def action_stop(self) -> None:
        if self.running:
            self.stop()
            self.notify("Stopped the tracklist (queued downloads keep going)")

    def stop(self) -> None:
        self.running = False
        for r in self.rows:
            if r.state == "waiting" and r.task:
                r.task.cancel()
                r.state = "skipped"
                self._update(r)
        self._summary()

    def action_close(self) -> None:
        self.app.query_one("SearchPane").close_search(self)

    @property
    def hits(self) -> list:  # tab label count
        return [r for r in self.rows if r.hit]
