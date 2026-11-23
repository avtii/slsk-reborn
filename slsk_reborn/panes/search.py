"""Search tab: one sub-tab per query, results stream in live."""
from __future__ import annotations

import itertools
import re

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, DataTable, Input, Static, TabbedContent, TabPane

from ..engine import Hit
from ..util import (LOSSLESS, basename, human_duration, human_size, human_speed, quality_text,
                    short_dir, user_color)

SORTS = ["arrival", "quality", "speed", "size", "user"]
_ids = itertools.count(1)


def hit_score(h: Hit) -> float:
    q = 5 if h.ext in LOSSLESS else (h.bitrate or 0) / 80
    return q + (3 if h.free_slot else 0) - min(h.queue, 50) / 10 + min(h.speed / 1e6, 3)


def matches(h: Hit, flt: str) -> bool:
    if not flt:
        return True
    hay = (h.user + " " + h.path).lower()
    for w in flt.lower().split():
        if w.startswith("-") and len(w) > 1:
            if w[1:] in hay:
                return False
        elif re.fullmatch(r">\d+", w):
            if not (h.ext in LOSSLESS or (h.bitrate or 0) >= int(w[1:])):
                return False
        elif w in ("flac", "mp3", "wav", "lossless", "m4a", "ogg", "opus"):
            if w == "lossless":
                if h.ext not in LOSSLESS:
                    return False
            elif h.ext != w:
                return False
        elif w not in hay:
            return False
    return True


class ResultsView(Vertical):
    BINDINGS = [
        Binding("d", "download", "Download"),
        Binding("f", "download_folder", "Folder"),
        Binding("b", "browse", "Browse user"),
        Binding("i", "info", "User info"),
        Binding("m", "message", "Message"),
        Binding("s", "cycle_sort", "Sort"),
        Binding("ctrl+w", "close", "Close tab"),
    ]

    def __init__(self, query: str, **kw):
        super().__init__(**kw)
        self.query_text = query
        self.ticket: int | None = None
        self.hits: list[Hit] = []
        self.pending: list[Hit] = []
        self.users: set[str] = set()
        self.sort = "arrival"

    def compose(self) -> ComposeResult:
        with Horizontal(classes="filter-row"):
            yield Input(placeholder="filter results:  words  -exclude  flac  >256", classes="flt")
            yield Checkbox("free slot", classes="chk-free")
            yield Checkbox("lossless", classes="chk-lossless")
        yield DataTable(cursor_type="row", zebra_stripes=True, classes="results")
        yield Static(classes="summary")

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_column(" ", key="slot", width=2)
        t.add_column("User", key="user", width=16)
        t.add_column("Speed", key="speed", width=9)
        t.add_column("Q", key="queue", width=4)
        t.add_column("Folder", key="folder", width=34)
        t.add_column("File", key="file")
        t.add_column("Size", key="size", width=7)
        t.add_column("Quality", key="quality", width=10)
        t.add_column("Len", key="len", width=6)
        self.set_interval(0.4, self.flush)
        self.update_summary()

    # incoming hits are buffered and drawn in batches so big result floods stay smooth
    def add_hits(self, hits: list[Hit]) -> None:
        self.pending.extend(hits)

    def flush(self) -> None:
        if not self.pending:
            return
        new, self.pending = self.pending, []
        start = len(self.hits)
        self.hits.extend(new)
        for h in new:
            self.users.add(h.user)
        if self.sort == "arrival":
            t = self.query_one(DataTable)
            for i, h in enumerate(new, start):
                if self._visible(h):
                    t.add_row(*self._cells(h), key=str(i))
        else:
            self.rebuild()
        self.update_summary()
        self.app.query_one("SearchPane").refresh_tab_label(self)

    def _visible(self, h: Hit) -> bool:
        if self.query_one(".chk-free", Checkbox).value and not h.free_slot:
            return False
        if self.query_one(".chk-lossless", Checkbox).value and h.ext not in LOSSLESS:
            return False
        return matches(h, self.query_one(".flt", Input).value)

    def _cells(self, h: Hit):
        slot = Text("●", "bold #39ff88") if h.free_slot else Text("●", "#ff4d6d")
        lock = "🔒 " if h.locked else ""
        return (slot, Text(h.user, user_color(h.user)), Text(human_speed(h.speed), "#7ab8ff"),
                Text(str(h.queue), "dim" if h.queue else "#39ff88"), Text(short_dir(h.path), "dim"),
                Text(lock + basename(h.path), "bold" if not h.locked else "dim strike"),
                human_size(h.size), quality_text(h.ext, h.bitrate), human_duration(h.duration))

    def rebuild(self) -> None:
        t = self.query_one(DataTable)
        idx = list(range(len(self.hits)))
        key = {
            "quality": lambda i: -((5000 if self.hits[i].ext in LOSSLESS else 0) + (self.hits[i].bitrate or 0)),
            "speed": lambda i: -(self.hits[i].speed + (10**9 if self.hits[i].free_slot else 0)),
            "size": lambda i: -self.hits[i].size,
            "user": lambda i: (self.hits[i].user.lower(), self.hits[i].path),
        }.get(self.sort)
        if key:
            idx.sort(key=key)
        t.clear()
        for i in idx:
            h = self.hits[i]
            if self._visible(h):
                t.add_row(*self._cells(h), key=str(i))
        self.update_summary()

    def update_summary(self) -> None:
        t = self.query_one(DataTable)
        s = Text()
        s.append(f" “{self.query_text}” ", "bold reverse")
        s.append(f"  {len(self.hits):,} files", "bold #00e5ff")
        s.append(f" from {len(self.users):,} users", "#b388ff")
        s.append(f"   showing {t.row_count:,}", "dim")
        s.append(f"   sort: {self.sort}", "#ffd23f")
        s.append("   enter download · f folder · b browse · i info · s sort", "dim")
        self.query_one(".summary", Static).update(s)

    @on(Input.Changed, ".flt")
    @on(Checkbox.Changed)
    def _refilter(self) -> None:
        self.rebuild()

    def current(self) -> Hit | None:
        t = self.query_one(DataTable)
        if not t.row_count:
            return None
        k = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
        return self.hits[int(k)]

    @on(DataTable.RowSelected)
    def _selected(self, e: DataTable.RowSelected) -> None:
        self.action_download()

    def action_download(self) -> None:
        if (h := self.current()):
            if h.locked:
                self.notify("That file is locked (shared to buddies only).", severity="warning")
                return
            self.app.start_download(h.user, h.path, h.size)

    def action_download_folder(self) -> None:
        if (h := self.current()):
            folder = h.path[:max(h.path.rfind("\\"), h.path.rfind("/"))]
            self.app.start_folder_download(h.user, folder)

    def action_browse(self) -> None:
        if (h := self.current()):
            self.app.browse_user(h.user, focus_path=h.path)

    def action_info(self) -> None:
        if (h := self.current()):
            self.app.show_user(h.user)

    def action_message(self) -> None:
        if (h := self.current()):
            self.app.open_pm(h.user)

    def action_cycle_sort(self) -> None:
        self.sort = SORTS[(SORTS.index(self.sort) + 1) % len(SORTS)]
        self.rebuild()

    def action_close(self) -> None:
        self.app.query_one("SearchPane").close_search(self)


class SearchPane(Vertical):
    BINDINGS = [Binding("ctrl+w", "close_current", "Close tab", show=False)]

    def compose(self) -> ComposeResult:
        with Horizontal(id="search-bar"):
            yield Static("⌕", id="search-icon")
            yield Input(placeholder="search the soulseek network…  (artist, album, track)", id="search-input")
            yield Button("Search", variant="primary", id="search-go")
        yield Static(id="search-empty")
        yield TabbedContent(id="search-tabs")

    def on_mount(self) -> None:
        self.views: dict[int, ResultsView] = {}
        self.app.bus.on("search.hits", self._on_hits)
        self.query_one("#search-empty", Static).update(Text.from_markup(
            "\n\n[b #ff2bd6]Type something above and hit Enter.[/]\n\n"
            "[dim]Results stream in live from peers. Each search opens its own tab.\n"
            "Green dot = free upload slot (starts right away). Glowing badge = lossless.[/]",
            justify="center"))
        self.query_one("#search-tabs").display = False

    def focus_input(self) -> None:
        self.query_one("#search-input", Input).focus()

    @on(Input.Submitted, "#search-input")
    @on(Button.Pressed, "#search-go")
    def _submit(self) -> None:
        inp = self.query_one("#search-input", Input)
        q = inp.value.strip()
        if len(q) < 2:
            return
        inp.value = ""
        self.new_search(q)

    @work
    async def new_search(self, query: str) -> None:
        if not self.app.engine.connected:
            self.notify("Not connected yet.", severity="warning")
            return
        tabs = self.query_one(TabbedContent)
        pane_id = f"sr{next(_ids)}"
        view = ResultsView(query)
        await tabs.add_pane(TabPane(self._label(query, 0), view, id=pane_id))
        tabs.display = True
        self.query_one("#search-empty").display = False
        tabs.active = pane_id
        try:
            view.ticket = await self.app.engine.search(query)
        except Exception as e:
            self.notify(f"Search failed: {e}", severity="error")
            return
        self.views[view.ticket] = view
        view.query_one(DataTable).focus()

    @staticmethod
    def _label(q: str, n: int) -> str:
        q = q if len(q) <= 18 else q[:17] + "…"
        return f"{q} ({n})" if n else q

    def refresh_tab_label(self, view: ResultsView) -> None:
        pane = view.parent
        if isinstance(pane, TabPane):
            tabs = self.query_one(TabbedContent)
            try:
                tabs.get_tab(pane.id).label = self._label(view.query_text, len(view.hits))
            except Exception:
                pass

    def _on_hits(self, ticket: int, hits: list[Hit]) -> None:
        if (v := self.views.get(ticket)):
            v.add_hits(hits)

    def close_search(self, view: ResultsView) -> None:
        if view.ticket is not None:
            self.app.engine.stop_search(view.ticket)
            self.views.pop(view.ticket, None)
        tabs = self.query_one(TabbedContent)
        pane = view.parent
        if isinstance(pane, TabPane):
            tabs.remove_pane(pane.id)
        if not self.views:
            tabs.display = False
            self.query_one("#search-empty").display = True
            self.focus_input()

    def action_close_current(self) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active:
            pane = tabs.get_pane(tabs.active)
            self.close_search(pane.query_one(ResultsView))
