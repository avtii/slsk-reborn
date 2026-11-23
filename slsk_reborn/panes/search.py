"""Search tab: one sub-tab per query, results stream in live."""
from __future__ import annotations

import itertools
import re
import time
from collections import Counter
from dataclasses import dataclass, field

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, DataTable, Input, Static, TabbedContent, TabPane

from ..engine import Hit
from ..util import (LOSSLESS, basename, dirname, human_duration, human_size, human_speed, quality_text,
                    short_dir, split_path, user_color)

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


TRACK_NO = re.compile(r"^\s*(?:\d-)?(\d{1,2})(?=\D)")  # "07 - x", "1-07 x", "07. x"


@dataclass
class Album:
    """Search hits grouped by user + folder."""
    idx: int
    user: str
    folder: str
    hits: list[int] = field(default_factory=list)
    size: int = 0
    duration: int = 0
    numbers: set[int] = field(default_factory=set)
    exts: Counter = field(default_factory=Counter)
    min_bitrate: int = 0
    free_slot: bool = False
    speed: int = 0
    queue: int = 0
    locked: int = 0

    def add(self, i: int, h: Hit) -> None:
        self.hits.append(i)
        self.size += h.size
        self.duration += h.duration or 0
        self.exts[h.ext] += 1
        if h.ext not in LOSSLESS and h.bitrate:
            self.min_bitrate = min(self.min_bitrate or h.bitrate, h.bitrate)
        if (m := TRACK_NO.match(basename(h.path))) and 0 < int(m.group(1)) < 100:
            self.numbers.add(int(m.group(1)))
        self.free_slot, self.speed, self.queue = h.free_slot, h.speed, h.queue
        self.locked += h.locked

    @property
    def lossless(self) -> bool:
        return all(e in LOSSLESS for e in self.exts)

    def quality(self) -> Text:
        ext = self.exts.most_common(1)[0][0]
        return quality_text(ext, None if self.lossless else (self.min_bitrate or None))

    def tracks(self) -> Text:
        """Track count; a check when the track numbers run 1..n with no gaps, n/m when some are missing."""
        top = max(self.numbers, default=0)
        if top >= 2 and self.numbers == set(range(1, top + 1)):
            return Text(f"{len(self.hits)} ✔", "bold #39ff88")
        if top > len(self.numbers):
            return Text(f"{len(self.numbers)}/{top}", "#ffd23f")
        return Text(str(len(self.hits)))


FILE_COLS = [(" ", "slot", 2), ("User", "user", 16), ("Speed", "speed", 9), ("Q", "queue", 4),
             ("Folder", "folder", 34), ("File", "file", 48), ("Size", "size", 7), ("Quality", "quality", 10),
             ("Len", "len", 6)]
ALBUM_COLS = [(" ", "slot", 2), ("User", "user", 16), ("Speed", "speed", 9), ("Q", "queue", 4),
              ("Album folder", "file", 48), ("Tracks", "tracks", 7), ("Size", "size", 8),
              ("Quality", "quality", 10), ("Len", "len", 8)]


class IdxText(Text):
    """Row's first cell; carries the hit index so DataTable.sort can sort in place."""

    def __init__(self, idx: int, *a, **kw):
        super().__init__(*a, **kw)
        self.idx = idx


MAX_RESULTS = 10_000   # per search; the search stops itself after this many files
FLUSH_EVERY = 0.3      # seconds between UI updates while results stream in
ROWS_PER_FLUSH = 400   # cap per update so a flood of results never blocks the UI
RESORT_EVERY = 1.0     # seconds between in-place re-sorts while streaming


class ResultsView(Vertical):
    BINDINGS = [
        Binding("d", "download", "Download"),
        Binding("f", "download_folder", "Folder"),
        Binding("a", "toggle_albums", "Albums"),
        Binding("w", "wishlist", "Wishlist"),
        Binding("b", "browse", "Browse user"),
        Binding("i", "info", "User info"),
        Binding("m", "message", "Message"),
        Binding("s", "cycle_sort", "Sort"),
        Binding("x", "stop", "Stop search"),
        Binding("ctrl+w", "close", "Close tab"),
    ]

    def __init__(self, query: str, wish: bool = False, **kw):
        super().__init__(**kw)
        self.query_text = query
        self.wish = wish            # results of the periodic wishlist search
        self._seen: set[tuple[str, str]] = set()
        self.ticket: int | None = None
        self.hits: list[Hit] = []
        self.pending: list[Hit] = []
        self.users: set[str] = set()
        self.sort = "arrival"
        self.running = True
        self.stop_reason = ""
        self.flt = (False, False, "")  # free slot, lossless, filter text
        self._dirty_sort = False
        self._last_sort = 0.0
        self._refilter_timer = None
        self.albums_mode = False
        self.albums: dict[tuple[str, str], Album] = {}
        self.album_list: list[Album] = []
        self._album_rows: set[int] = set()

    def compose(self) -> ComposeResult:
        with Horizontal(classes="filter-row"):
            yield Input(placeholder="filter results:  words  -exclude  flac  >256", classes="flt")
            yield Checkbox("free slot", classes="chk-free")
            yield Checkbox("lossless", classes="chk-lossless")
            yield Button("■ Stop", variant="error", classes="stop-btn")
        yield DataTable(cursor_type="row", zebra_stripes=True, classes="results")
        yield Static(classes="summary")

    def on_mount(self) -> None:
        self.table = self.query_one(DataTable)
        self.albums_mode = bool(getattr(self.app.cfg, "album_view", False))
        self._add_columns()
        self.summary = self.query_one(".summary", Static)
        self.set_interval(FLUSH_EVERY, self.flush)
        self.update_summary()

    @property
    def cols(self):
        return ALBUM_COLS if self.albums_mode else FILE_COLS

    def _add_columns(self) -> None:
        for label, key, width in self.cols:
            self.table.add_column(label, key=key, width=width)

    def on_resize(self) -> None:
        # File column takes what the fixed columns leave over; a fixed width means
        # adding rows never re-measures the whole table
        from textual.widgets.data_table import ColumnKey
        col = self.table.columns.get(ColumnKey("file"))
        fixed = sum(w for _, k, w in self.cols if k != "file") + 2 * len(self.cols) + 2
        w = max(20, self.size.width - fixed)
        if col is not None and col.width != w:
            col.width = w
            col.auto_width = False
            self.table.refresh()

    # ------------------------------------------------------------------ streaming
    @property
    def label(self) -> str:
        return ("★ " if self.wish else "") + self.query_text

    def add_hits(self, hits: list[Hit]) -> int:
        """Queue hits for display; returns how many were new."""
        if not self.running:
            return 0
        if self.wish:  # every wishlist round returns the same files again
            hits = [h for h in hits if (h.user, h.path) not in self._seen]
            self._seen.update((h.user, h.path) for h in hits)
        room = MAX_RESULTS - len(self.hits) - len(self.pending)
        self.pending.extend(hits[:max(room, 0)])
        if room <= len(hits):
            self.stop(f"stopped at {MAX_RESULTS:,} files")
        return len(hits)

    def flush(self) -> None:
        if self.pending:
            new, self.pending = self.pending[:ROWS_PER_FLUSH], self.pending[ROWS_PER_FLUSH:]
            start = len(self.hits)
            self.hits.extend(new)
            self.users.update(h.user for h in new)
            t = self.table
            added = False
            touched: dict[int, Album] = {}
            for i, h in enumerate(new, start):
                if not self._visible(h):
                    continue
                if self.albums_mode:
                    a = self._album_add(i, h)
                    touched[a.idx] = a
                else:
                    t.add_row(*self._cells(i, h), key=str(i))
                    added = True
            for a in touched.values():
                if a.idx in self._album_rows:
                    for (_, col, _), v in zip(ALBUM_COLS, self._album_cells(a)):
                        t.update_cell(f"a{a.idx}", col, v)
                else:
                    t.add_row(*self._album_cells(a), key=f"a{a.idx}")
                    self._album_rows.add(a.idx)
                added = True
            if added and self.sort != "arrival":
                self._dirty_sort = True
            self.update_summary()
            self.app.query_one("SearchPane").refresh_tab_label(self)
        if self._dirty_sort and time.monotonic() - self._last_sort >= RESORT_EVERY:
            self.resort()

    def stop(self, why: str = "stopped") -> None:
        if not self.running:
            return
        self.running = False
        self.stop_reason = why
        if self.ticket is not None:
            self.app.engine.stop_search(self.ticket)
        for b in self.query(".stop-btn"):
            b.disabled = True
        self.update_summary()
        self.app.query_one("SearchPane").refresh_tab_label(self)

    # ------------------------------------------------------------------ rows
    def _visible(self, h: Hit) -> bool:
        free, lossless, text = self.flt
        if free and not h.free_slot:
            return False
        if lossless and h.ext not in LOSSLESS:
            return False
        return matches(h, text)

    def _cells(self, i: int, h: Hit):
        slot = IdxText(i, "●", "bold #39ff88" if h.free_slot else "#ff4d6d")
        lock = "🔒 " if h.locked else ""
        return (slot, Text(h.user, user_color(h.user)), Text(human_speed(h.speed), "#7ab8ff"),
                Text(str(h.queue), "dim" if h.queue else "#39ff88"), Text(short_dir(h.path), "dim"),
                Text(lock + basename(h.path), "bold" if not h.locked else "dim strike"),
                human_size(h.size), quality_text(h.ext, h.bitrate), human_duration(h.duration))

    def _album_add(self, i: int, h: Hit) -> Album:
        key = (h.user, dirname(h.path))
        if (a := self.albums.get(key)) is None:
            a = self.albums[key] = Album(len(self.album_list), *key)
            self.album_list.append(a)
        a.add(i, h)
        return a

    def _album_cells(self, a: Album):
        slot = IdxText(a.idx, "●", "bold #39ff88" if a.free_slot else "#ff4d6d")
        name = Text("🔒 " if a.locked == len(a.hits) else "")
        parts = split_path(a.folder)
        if len(parts) > 1:
            name.append(parts[-2] + "/", "dim")
        name.append(parts[-1] if parts else a.folder, "bold")
        return (slot, Text(a.user, user_color(a.user)), Text(human_speed(a.speed), "#7ab8ff"),
                Text(str(a.queue), "dim" if a.queue else "#39ff88"), name, a.tracks(),
                human_size(a.size), a.quality(), human_duration(a.duration))

    def _sort_key(self):
        if self.albums_mode:
            A = self.album_list
            return {
                "quality": lambda i: -((5000 if A[i].lossless else 0) + A[i].min_bitrate),
                "speed": lambda i: -(A[i].speed + (10**9 if A[i].free_slot else 0)),
                "size": lambda i: -A[i].size,
                "user": lambda i: (A[i].user.lower(), A[i].folder),
                "arrival": lambda i: i,
            }[self.sort]
        H = self.hits
        return {
            "quality": lambda i: -((5000 if H[i].ext in LOSSLESS else 0) + (H[i].bitrate or 0)),
            "speed": lambda i: -(H[i].speed + (10**9 if H[i].free_slot else 0)),
            "size": lambda i: -H[i].size,
            "user": lambda i: (H[i].user.lower(), H[i].path),
            "arrival": lambda i: i,
        }[self.sort]

    def resort(self) -> None:
        """Sort rows in place, keeping the cursor on the same result."""
        self._dirty_sort = False
        self._last_sort = time.monotonic()
        t = self.table
        if not t.row_count:
            return
        keep = t.coordinate_to_cell_key(t.cursor_coordinate).row_key
        offset = t.cursor_row - int(t.scroll_y)
        k = self._sort_key()
        t.sort("slot", key=lambda cell: k(cell.idx))
        row = t.get_row_index(keep)
        if row != t.cursor_row:
            t.move_cursor(row=row, animate=False, scroll=False)
            t.scroll_to(y=max(0, row - offset), animate=False, immediate=True)

    def rebuild(self) -> None:
        """Full redraw; only needed when the filter changes (sorting is in place)."""
        t = self.table
        t.clear()
        if self.albums_mode:
            self.albums, self.album_list, self._album_rows = {}, [], set()
            for i, h in enumerate(self.hits):
                if self._visible(h):
                    self._album_add(i, h)
            for j in sorted(range(len(self.album_list)), key=self._sort_key()):
                t.add_row(*self._album_cells(self.album_list[j]), key=f"a{j}")
                self._album_rows.add(j)
            self._dirty_sort = False
            self.update_summary()
            return
        idx = sorted(range(len(self.hits)), key=self._sort_key())
        for i in idx:
            h = self.hits[i]
            if self._visible(h):
                t.add_row(*self._cells(i, h), key=str(i))
        self._dirty_sort = False
        self.update_summary()

    def update_summary(self) -> None:
        s = Text()
        s.append(f" “{self.query_text}” ", "bold reverse")
        if self.wish and self.running:
            s.append("  ★ wishlist: new results keep arriving", "bold #ffd23f")
        elif self.running:
            s.append("  ● receiving", "bold #39ff88")
        else:
            s.append(f"  ■ {self.stop_reason}", "bold #ff8c42")
        s.append(f"  {len(self.hits):,} files", "bold #00e5ff")
        s.append(f" from {len(self.users):,} users", "#b388ff")
        unit = " albums" if self.albums_mode else ""
        s.append(f"   showing {self.table.row_count:,}{unit}", "dim")
        s.append(f"   sort: {self.sort}", "#ffd23f")
        if self.albums_mode:
            s.append("   enter download album · a files · s sort · x stop", "dim")
        else:
            s.append("   enter download · f folder · a albums · s sort · x stop", "dim")
        self.summary.update(s)

    # ------------------------------------------------------------------ filter
    @on(Input.Changed, ".flt")
    @on(Checkbox.Changed)
    def _refilter(self) -> None:
        # wait for a short pause in typing, then redraw once
        if self._refilter_timer is not None:
            self._refilter_timer.stop()
        self._refilter_timer = self.set_timer(0.2, self._apply_filter)

    def _apply_filter(self) -> None:
        self.flt = (self.query_one(".chk-free", Checkbox).value,
                    self.query_one(".chk-lossless", Checkbox).value,
                    self.query_one(".flt", Input).value)
        self.rebuild()

    @on(Button.Pressed, ".stop-btn")
    def _stop_pressed(self) -> None:
        self.stop()
        self.table.focus()

    def current(self) -> Hit | None:
        """The hit under the cursor (an album row gives its first file)."""
        t = self.table
        if not t.row_count:
            return None
        k = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
        if k.startswith("a"):
            return self.hits[self.album_list[int(k[1:])].hits[0]]
        return self.hits[int(k)]

    @on(DataTable.RowSelected)
    def _selected(self, e: DataTable.RowSelected) -> None:
        self.action_download()

    def action_download(self) -> None:
        if self.albums_mode:
            return self.action_download_folder()
        if (h := self.current()):
            if h.locked:
                self.notify("That file is locked (shared to buddies only).", severity="warning")
                return
            self.app.start_download(h.user, h.path, h.size)

    def action_download_folder(self) -> None:
        if (h := self.current()):
            self.app.start_folder_download(h.user, dirname(h.path))

    def action_browse(self) -> None:
        if (h := self.current()):
            self.app.browse_user(h.user, focus_path=h.path)

    def action_info(self) -> None:
        if (h := self.current()):
            self.app.show_user(h.user)

    def action_message(self) -> None:
        if (h := self.current()):
            self.app.open_pm(h.user)

    def action_wishlist(self) -> None:
        if self.app.set_listed("wishlist", self.query_text, True):
            self.notify(f"“{self.query_text}” is on your wishlist: the network is searched for it "
                        "every few minutes (ctrl+l to manage)", title="★ wishlist")
        else:
            self.notify("Already on your wishlist", severity="warning")

    def action_toggle_albums(self) -> None:
        self.albums_mode = not self.albums_mode
        self.app.cfg.album_view = self.albums_mode
        self.app.cfg.save()
        self.table.clear(columns=True)
        self._add_columns()
        self.on_resize()
        self.rebuild()

    def action_cycle_sort(self) -> None:
        self.sort = SORTS[(SORTS.index(self.sort) + 1) % len(SORTS)]
        self.resort()
        self.update_summary()

    def action_stop(self) -> None:
        if self.running:
            self.stop()
            self.notify(f"Stopped search “{self.query_text}”")

    def action_close(self) -> None:
        self.app.query_one("SearchPane").close_search(self)


class SearchPane(Vertical):
    BINDINGS = [Binding("ctrl+w", "close_current", "Close tab", show=False)]

    def compose(self) -> ComposeResult:
        with Horizontal(id="search-bar"):
            yield Static("⌕", id="search-icon")
            yield Input(placeholder="search the soulseek network…  (artist, album, track)", id="search-input")
            yield Button("Search", variant="primary", id="search-go")
            yield Button("♫ Tracklist", id="search-tracklist")
        yield Static(id="search-empty")
        yield TabbedContent(id="search-tabs")

    def on_mount(self) -> None:
        self.views: dict[int, ResultsView] = {}
        self.wish_views: dict[str, ResultsView] = {}
        self._wish_pending: dict[str, list[Hit]] = {}
        self._wish_noted: dict[str, float] = {}
        self.lists: set = set()  # tracklist imports
        self.app.bus.on("search.hits", self._on_hits)
        self.app.bus.on("wishlist.hits", self._on_wishlist)
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

    @on(Button.Pressed, "#search-tracklist")
    def _tracklist_pressed(self) -> None:
        self.app.action_tracklist()

    @work
    async def open_tracklist(self, tracks, prefer_lossless: bool, name: str) -> None:
        if not self.app.engine.connected:
            self.notify("Not connected yet.", severity="warning")
            return
        from .tracklist import TracklistView
        tabs = self.query_one(TabbedContent)
        pane_id = f"sr{next(_ids)}"
        view = TracklistView(tracks, prefer_lossless, name)
        await tabs.add_pane(TabPane(self._label(view.label, 0), view, id=pane_id))
        tabs.display = True
        self.query_one("#search-empty").display = False
        tabs.active = pane_id
        self.lists.add(view)
        view.query_one(DataTable).focus()

    @work
    async def new_search(self, query: str) -> None:
        if not self.app.engine.connected:
            self.notify("Not connected yet.", severity="warning")
            return
        tabs = self.query_one(TabbedContent)
        pane_id = f"sr{next(_ids)}"
        view = ResultsView(query)
        await tabs.add_pane(TabPane(self._label(view.label, 0), view, id=pane_id))
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
    def _label(q: str, n: int, running: bool = True) -> str:
        q = q if len(q) <= 18 else q[:17] + "…"
        mark = "" if running else "■ "
        return f"{mark}{q} ({n:,})" if n else f"{mark}{q}"

    def refresh_tab_label(self, view: ResultsView) -> None:
        pane = view.parent
        if isinstance(pane, TabPane):
            tabs = self.query_one(TabbedContent)
            try:
                tabs.get_tab(pane.id).label = self._label(view.label, len(view.hits), view.running)
            except Exception:
                pass

    def _on_hits(self, ticket: int, hits: list[Hit]) -> None:
        if (v := self.views.get(ticket)):
            v.add_hits(hits)

    def _on_wishlist(self, query: str, hits: list[Hit]) -> None:
        if (v := self.wish_views.get(query)) is not None:
            if v.add_hits(hits) and time.monotonic() - self._wish_noted.get(query, 0) > 60:
                self._wish_noted[query] = time.monotonic()  # one note per round, not per peer
                self.app.notify(f"New results for “{query}”", title="★ wishlist")
            return
        first = query not in self._wish_pending
        self._wish_pending.setdefault(query, []).extend(hits)
        if first:
            self._open_wish(query)

    @work
    async def _open_wish(self, query: str) -> None:
        """Wishlist results get their own tab, opened in the background."""
        tabs = self.query_one(TabbedContent)
        view = ResultsView(query, wish=True)
        await tabs.add_pane(TabPane(self._label(view.label, 0), view, id=f"sr{next(_ids)}"))
        tabs.display = True
        self.query_one("#search-empty").display = False
        self.wish_views[query] = view
        n = view.add_hits(self._wish_pending.pop(query, []))
        self._wish_noted[query] = time.monotonic()
        self.app.notify(f"{n:,} files for “{query}” (Search tab)", title="★ wishlist", timeout=8)

    def close_search(self, view) -> None:
        if view in self.lists:
            view.stop()
            self.lists.discard(view)
        elif view.wish:
            view.stop()
            self.wish_views.pop(view.query_text, None)
        elif view.ticket is not None:
            view.stop()
            self.views.pop(view.ticket, None)
        tabs = self.query_one(TabbedContent)
        pane = view.parent
        if isinstance(pane, TabPane):
            tabs.remove_pane(pane.id)
        if not self.views and not self.wish_views and not self.lists:
            tabs.display = False
            self.query_one("#search-empty").display = True
            self.focus_input()

    def action_close_current(self) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active:
            pane = tabs.get_pane(tabs.active)
            self.close_search(pane.children[0])
