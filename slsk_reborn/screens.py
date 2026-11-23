"""Modal screens: login, user card, room list, lists, help, folder picker."""
from __future__ import annotations

import os
import random
import string
import sys
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Button, Checkbox, DataTable, DirectoryTree, Input, Label, ListItem, ListView,
                             LoadingIndicator, Static, TextArea, Tree)

from .engine import RoomInfo, UserCard
from .theme import logo
from .util import human_size, human_speed


class LoginScreen(ModalScreen[tuple[str, str] | None]):
    """Ask for Soulseek credentials. Unknown names get registered on first login."""

    BINDINGS = [Binding("escape", "quit", "Quit")]

    def __init__(self, username: str = "", error: str = ""):
        super().__init__()
        self._username = username
        self._error = error

    def compose(self) -> ComposeResult:
        with Vertical(id="login-box"):
            yield Static(logo(), id="login-logo")
            yield Static(Text("search · download · share · chat",
                              style="italic #b388ff"), id="login-tag")
            yield Label("Username")
            yield Input(self._username, placeholder="your soulseek name", id="login-user")
            yield Label("Password")
            yield Input(placeholder="password", password=True, id="login-pass")
            yield Static(Text(self._error, style="bold #ff4d6d") if self._error else
                         Text("New name? It is registered automatically on first login.", style="dim"),
                         id="login-hint")
            with Horizontal(id="login-buttons"):
                yield Button("Connect", variant="primary", id="login-go")
                yield Button("Random account", id="login-random")
                yield Button("Quit", variant="error", id="login-quit")

    def on_mount(self) -> None:
        self.query_one("#login-pass" if self._username else "#login-user", Input).focus()

    @on(Button.Pressed, "#login-random")
    def _random(self) -> None:
        self.query_one("#login-user", Input).value = "reborn_" + "".join(random.choices(string.digits, k=6))
        self.query_one("#login-pass", Input).value = "".join(
            random.choices(string.ascii_letters + string.digits, k=16))

    @on(Input.Submitted)
    @on(Button.Pressed, "#login-go")
    def _go(self) -> None:
        u = self.query_one("#login-user", Input).value.strip()
        p = self.query_one("#login-pass", Input).value
        if not u or not p:
            self.query_one("#login-hint", Static).update(Text("Both fields are required.", style="bold #ff4d6d"))
            return
        self.dismiss((u, p))

    @on(Button.Pressed, "#login-quit")
    def action_quit(self) -> None:
        self.dismiss(None)


class UserInfoScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape,q", "dismiss(None)", "Close"), Binding("b", "act('browse')", "Browse"),
                Binding("m", "act('message')", "Message")]

    def __init__(self, user: str):
        super().__init__()
        self.user = user

    def compose(self) -> ComposeResult:
        with Vertical(id="card-box", classes="modal-box"):
            yield Static(f"[b $primary]◉ {self.user}[/]", id="card-title", markup=True)
            yield LoadingIndicator(id="card-loading")
            yield Static(id="card-body")
            with Horizontal(classes="modal-buttons"):
                yield Button("Browse files", id="card-browse", variant="primary")
                yield Button("Message", id="card-msg")
                yield Button(self._friend_label(), id="card-friend")
                yield Button(*self._block_label(), id="card-block")
                yield Button("Close", id="card-close")

    def on_mount(self) -> None:
        self.load()

    def _friend_label(self) -> str:
        return "♥ Unfriend" if self.user in self.app.cfg.friends else "♥ Friend"

    def _block_label(self) -> tuple[str, str]:
        return ("Unblock", "default") if self.user in self.app.cfg.blocked else ("⛔ Block", "error")

    def _labels(self) -> None:
        self.query_one("#card-friend", Button).label = self._friend_label()
        b = self.query_one("#card-block", Button)
        b.label, b.variant = self._block_label()

    @on(Button.Pressed, "#card-friend")
    def _friend(self) -> None:
        on = self.user not in self.app.cfg.friends
        self.app.set_listed("friends", self.user, on)
        self.notify(f"{self.user} {'added to' if on else 'removed from'} friends")
        self._labels()

    @on(Button.Pressed, "#card-block")
    def _block(self) -> None:
        on = self.user not in self.app.cfg.blocked
        self.app.set_listed("blocked", self.user, on)
        self.notify(f"{self.user} {'blocked: no messages, searches, browsing or uploads' if on else 'unblocked'}")
        self._labels()

    @work(exclusive=True)
    async def load(self) -> None:
        body = self.query_one("#card-body", Static)
        try:
            card: UserCard = await self.app.engine.user_info(self.user)
        except Exception as e:
            body.update(Text(f"Could not fetch user info: {e}", style="#ff4d6d"))
        else:
            t = Table.grid(padding=(0, 2))
            t.add_column(style="dim")
            t.add_column()
            status_style = {"online": "bold #39ff88", "away": "bold #ffd23f"}.get(card.status, "#ff4d6d")
            t.add_row("status", Text(card.status + ("  ★ privileged" if card.privileged else ""), status_style))
            if card.country:
                t.add_row("country", card.country)
            t.add_row("shares", f"{card.files:,} files in {card.folders:,} folders")
            t.add_row("avg speed", human_speed(card.avg_speed))
            t.add_row("uploads", f"{card.uploads:,}")
            if card.upload_slots is not None:
                t.add_row("slots", Text(f"{card.upload_slots} ({'free' if card.free_slots else 'busy'})",
                                        "#39ff88" if card.free_slots else "#ffd23f"))
                t.add_row("queue", str(card.queue))
            if card.description:
                t.add_row("about", Text(card.description, style="italic"))
            body.update(t)
        self.query_one("#card-loading").display = False

    def action_act(self, what: str) -> None:
        self.dismiss(what)

    @on(Button.Pressed, "#card-browse")
    def _b(self):
        self.dismiss("browse")

    @on(Button.Pressed, "#card-msg")
    def _m(self):
        self.dismiss("message")

    @on(Button.Pressed, "#card-close")
    def _c(self):
        self.dismiss(None)


LISTS = {
    "wishlist": ("★ Wishlist", "searched for you every few minutes;\nnew results open a ★ tab", "add a search…"),
    "friends": ("♥ Friends", "people you trust; shown in\nyour friends list on the server", "add a username…"),
    "blocked": ("⛔ Blocked", "no messages, searches,\nbrowsing or uploads", "block a username…"),
}


class ListsScreen(ModalScreen[tuple[str, str] | None]):
    """Wishlist, friends and blocked users. Changes apply right away."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Close"), Binding("delete,backspace", "remove", "Remove")]

    def compose(self) -> ComposeResult:
        with Vertical(id="lists-box", classes="modal-box"):
            yield Static("[b $primary]Lists[/]   [dim]enter adds · del removes · "
                         "enter on an entry: search now / user card[/]", markup=True)
            with Horizontal(id="lists-cols"):
                for key, (title, hint, placeholder) in LISTS.items():
                    with Vertical(classes="list-col"):
                        yield Static(f"[b]{title}[/]\n[dim]{hint}[/]", markup=True, classes="list-title")
                        yield Input(placeholder=placeholder, id=f"in-{key}")
                        yield ListView(id=f"lv-{key}")
            with Horizontal(classes="modal-buttons"):
                yield Button("Close", id="lists-close")

    async def on_mount(self) -> None:
        for key in LISTS:
            await self._fill(key)
        self.query_one("#in-wishlist", Input).focus()

    async def _fill(self, key: str) -> None:
        lv = self.query_one(f"#lv-{key}", ListView)
        await lv.clear()
        items = getattr(self.app.cfg, key)
        await lv.extend([ListItem(Label(v), name=v) for v in items] or
                        [ListItem(Label(Text("— empty —", "dim")), name="", disabled=True)])
        lv.index = 0 if items else None

    @on(Input.Submitted)
    async def _add(self, e: Input.Submitted) -> None:
        key, value = e.input.id[3:], e.value.strip()
        if value:
            self.app.set_listed(key, value, True)
            e.input.value = ""
            for k in LISTS:  # friend <-> blocked move between lists
                await self._fill(k)

    @on(ListView.Selected)
    def _pick(self, e: ListView.Selected) -> None:
        if e.item.name:
            self.dismiss(("search" if e.list_view.id == "lv-wishlist" else "user", e.item.name))

    async def action_remove(self) -> None:
        lv = self.focused
        if isinstance(lv, ListView) and lv.highlighted_child and lv.highlighted_child.name:
            key = lv.id[3:]
            self.app.set_listed(key, lv.highlighted_child.name, False)
            await self._fill(key)

    @on(Button.Pressed, "#lists-close")
    def _close(self) -> None:
        self.dismiss(None)


class TracklistScreen(ModalScreen[tuple | None]):
    """Paste a tracklist (or load mixgrab's tracklist.txt); returns (tracks, prefer_lossless, name)."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Close")]

    def __init__(self, path: str = ""):
        super().__init__()
        self.path = path

    def compose(self) -> ComposeResult:
        with Vertical(id="tl-box", classes="modal-box"):
            yield Static("[b $primary]♫ Download a tracklist[/]\n[dim]One track per line, “Artist - Title”. "
                         "Numbers, timestamps and mixgrab's tracklist.txt are fine.[/]", markup=True)
            yield TextArea(id="tl-text")
            yield Static(id="tl-count")
            with Horizontal(id="tl-file-row"):
                yield Input(placeholder="…or a file path, then enter", id="tl-file", value=self.path)
                yield Checkbox("prefer lossless", value=True, id="tl-lossless")
            with Horizontal(classes="modal-buttons"):
                yield Button("Find & download", variant="primary", id="tl-go")
                yield Button("Cancel", id="tl-cancel")

    def on_mount(self) -> None:
        if self.path:
            self._load(self.path)
        self.query_one("#tl-text", TextArea).focus()
        self._count()

    def _tracks(self):
        from .tracklist import parse_text
        return parse_text(self.query_one("#tl-text", TextArea).text)

    @on(TextArea.Changed)
    def _count(self) -> None:
        n = len(self._tracks())
        self.query_one("#tl-count", Static).update(
            Text(f"{n} tracks recognised", "bold" if n else "dim"))

    @on(Input.Submitted, "#tl-file")
    def _file(self, e: Input.Submitted) -> None:
        self._load(e.value.strip().strip('"'))

    def _load(self, path: str) -> None:
        try:
            text = Path(path).expanduser().read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.notify(f"Can't read {path}: {e.strerror or e}", severity="error")
            return
        self.query_one("#tl-text", TextArea).text = text
        self.path = path

    @on(Button.Pressed, "#tl-go")
    def _go(self) -> None:
        tracks = self._tracks()
        if not tracks:
            self.notify("No “Artist - Title” lines found", severity="warning")
            return
        lines = self.query_one("#tl-text", TextArea).text.splitlines()
        if len(lines) > 1 and lines[1].strip().lower().startswith("http"):  # mixgrab: title, url, ...
            name = lines[0].strip()
        else:
            name = Path(self.path).stem if self.path else f"{len(tracks)} tracks"
        self.dismiss((tracks, self.query_one("#tl-lossless", Checkbox).value, name[:24] or "tracklist"))

    @on(Button.Pressed, "#tl-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class RoomListScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "dismiss(None)", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="rooms-box", classes="modal-box"):
            yield Static("[b $primary]Chat rooms[/]")
            yield Input(placeholder="filter… (or type a new room name and press Enter)", id="rooms-filter")
            yield LoadingIndicator(id="rooms-loading")
            yield DataTable(id="rooms-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_column("Room", key="name", width=36)
        t.add_column("Users", key="users", width=8)
        self.rooms: list[RoomInfo] = []
        self.load()
        self.query_one(Input).focus()

    @work(exclusive=True)
    async def load(self):
        try:
            self.rooms = await self.app.engine.room_list()
        except Exception as e:
            self.notify(f"Room list failed: {e}", severity="error")
        self.query_one("#rooms-loading").display = False
        self._fill("")

    def _fill(self, flt: str):
        t = self.query_one(DataTable)
        t.clear()
        for r in self.rooms:
            if flt.lower() in r.name.lower():
                t.add_row(Text(("🔒 " if r.private else "# ") + r.name), Text(str(r.users), "#00e5ff"),
                          key=r.name)

    @on(Input.Changed, "#rooms-filter")
    def _flt(self, e: Input.Changed):
        self._fill(e.value)

    @on(Input.Submitted, "#rooms-filter")
    def _sub(self, e: Input.Submitted):
        t = self.query_one(DataTable)
        if t.row_count:
            self.dismiss(t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value)
        elif e.value.strip():
            self.dismiss(e.value.strip())

    @on(DataTable.RowSelected)
    def _pick(self, e: DataTable.RowSelected):
        self.dismiss(e.row_key.value)


HELP = """\
[b $primary]Global[/]
  [b]1-5[/] / [b]F2-F6[/]  switch tab (Search, Transfers, Browse, Chat, Shares)
  [b]esc[/]          leave a text box so single-key shortcuts work
  [b]/[/] or [b]ctrl+f[/]  new search          [b]ctrl+t[/]  cycle theme
  [b]ctrl+p[/]       command palette     [b]?[/]       this help        [b]ctrl+q[/] or [b]ctrl+c[/]  quit
  [b]ctrl+l[/]       lists: wishlist, friends, blocked users (block/friend also on any user card, [b]i[/])
  [b]ctrl+o[/]       tracklist: paste “Artist - Title” lines, every track is found and queued

[b $primary]Search results[/]
  [b]enter / d[/]    download file       [b]f[/]  download the whole folder
  [b]b[/]            browse user         [b]i[/]  user info       [b]m[/]  message user
  [b]s[/]            cycle sort          [b]x[/]  stop search   [b]ctrl+w[/]  close tab
  [b]a[/]            album view: one row per folder with track count, size, quality;
                 [b]✔[/] = track numbers complete, [b]9/12[/] = some missing; enter downloads it
  [b]w[/]            add this search to the wishlist (re-run every few minutes, results in a ★ tab)
  Filter box: words to include, [b]-word[/] to exclude, [b]flac[/] / [b]mp3[/] / [b]>256[/] for quality.

[b $primary]Player[/]  (MP3, FLAC, WAV, OGG built in; other formats via mpv or ffplay if installed)
  [b]enter[/] on a finished download plays it, the rest of its folder follows
  [b]space[/] play/pause   [b]← →[/] or [b][ ][/] seek ∓10s ([b]shift+← →[/] ∓1 min)   [b]- +[/] volume
  [b]< >[/] prev/next   [b]\\ [/]stop   (arrows seek while something plays; on a tab row they switch tabs)

[b $primary]Transfers[/]
  [b]enter[/] play   [b]p[/] pause   [b]r[/] resume/retry   [b]x[/] abort   [b]del[/] remove   [b]c[/] clear finished
  [b]o[/] open download folder   [b]n[/] get the same file from another user (failed or stuck in a queue)
  Failed downloads try another user once by themselves (Shares → settings to turn off).

[b $primary]Browse[/]
  Type a username. [b]enter[/] downloads a file, [b]d[/] downloads a whole folder.

[b $primary]Chat[/]
  [b]/join room[/]  [b]/leave[/]  [b]/msg user text[/]  [b]/rooms[/]  [b]/clear[/]
  Plain text goes to the open conversation.

[b $primary]Shares[/]
  [b]Browse…[/] picks a folder to share; it is scanned and announced. Settings save to
  ~/.slsk-reborn/config.toml and apply live.

[b $primary]Sharing and ports[/]
  Soulseek is a sharing network: share some music back, many users won't serve people
  who share nothing. Peers connect to you on TCP port [b]N[/] and [b]N+1[/] (default 61000/61001,
  change with [b]--port N[/]). If UPnP can't open them, forward both on your router.
"""


WELCOME = """[b $primary]Soulseek runs on sharing.[/]
Everything you download comes from someone else's shared folder. Please share
some music back: many users only upload to people who share, and some ban
users who share nothing.
{share_line}

[b $primary]Let other users reach you.[/]
Peers connect to your computer on [b]TCP port {port}[/] (and [b]{port1}[/] for
obfuscated connections). {upnp_line}
If uploads never start or browsing you fails, forward [b]both ports[/] to this
computer in your router settings (and allow them in your firewall).
Use [b]--port N[/] to pick other ports.

[dim]This is shown once. The same notes are in help ([b]?[/]).[/]
"""


class WelcomeScreen(ModalScreen[str | None]):
    """First-run notes: sharing etiquette and the listening ports."""
    BINDINGS = [Binding("escape", "dismiss(None)", "Close")]

    def __init__(self, port: int, upnp: bool, shared_files: int):
        super().__init__()
        self.port, self.upnp, self.shared_files = port, upnp, shared_files

    def compose(self) -> ComposeResult:
        share_line = (f"You share [b]{self.shared_files:,}[/] files right now."
                      if self.shared_files else "[b $warning]You don't share any files yet.[/]")
        upnp_line = ("UPnP is on, so the app asks your router to open them automatically;"
                     " not every router allows that." if self.upnp else
                     "UPnP is off, so the router won't open them for you.")
        text = WELCOME.format(port=self.port, port1=self.port + 1, share_line=share_line,
                              upnp_line=upnp_line)
        with Vertical(id="welcome-box", classes="modal-box"):
            yield Center(Static(logo(), id="help-logo"))
            yield Static(text, markup=True, id="welcome-text")
            with Horizontal(id="welcome-buttons"):
                yield Button("Share a folder…", variant="primary", id="welcome-share")
                yield Button("Got it", id="welcome-ok")

    @on(Button.Pressed, "#welcome-share")
    def share(self) -> None:
        self.dismiss("share")

    @on(Button.Pressed, "#welcome-ok")
    def ok(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,question_mark", "dismiss(None)", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box", classes="modal-box"):
            yield Center(Static(logo(), id="help-logo"))
            yield Static(HELP, markup=True)


# ---------------------------------------------------------------------- folder picker

def places() -> list[tuple[str, str]]:
    """Quick-jump locations: home folders plus every drive / mounted volume."""
    from pathlib import Path
    home = Path.home()
    out = [("⌂ Home", str(home))]
    for name in ("Music", "Downloads", "Desktop", "Documents"):
        if (home / name).is_dir():
            out.append((name, str(home / name)))
    if sys.platform == "win32":
        drives = os.listdrives() if hasattr(os, "listdrives") else [
            f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
        out += [(f"▣ {d.rstrip(chr(92))}", d) for d in drives]
    else:
        out.append(("/ root", "/"))
        for base in ("/Volumes", "/media", "/mnt", f"/run/media/{home.name}"):
            try:
                out += [(f"▣ {e.name}", e.path) for e in os.scandir(base) if e.is_dir()]
            except OSError:
                pass
    return out


class LocalFolderTree(DirectoryTree):
    """Directory tree that only lists folders (hidden ones skipped)."""

    def filter_paths(self, paths):
        out = []
        for p in paths:
            try:
                if p.is_dir() and not p.name.startswith((".", "$")):
                    out.append(p)
            except OSError:
                pass
        return out

    def render_label(self, node, base_style, style):
        if node is self.root:  # show the full path, not just "C:" → ""
            return Text("📂 " + str(self.path), "bold #ff2bd6")
        return super().render_label(node, base_style, style)


class FolderPickerScreen(ModalScreen[str | None]):
    """Browse the local disk and pick a folder. Dismisses with the path or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel"),
                Binding("backspace", "up", "Parent folder", show=False)]

    def __init__(self, title: str = "Choose a folder", start: str = "", ok_label: str = "Select"):
        super().__init__()
        self.title_text = title
        self.ok_label = ok_label
        self.start = start if start and os.path.isdir(start) else os.path.expanduser("~")

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box", classes="modal-box"):
            yield Static(f"[b $primary]▣ {self.title_text}[/]", markup=True)
            with Horizontal(id="picker-places"):
                for i, (label, _) in enumerate(places()):
                    yield Button(label, id=f"place-{i}", classes="place")
            with Horizontal(id="picker-body"):
                yield LocalFolderTree(self.start, id="picker-tree")
            with Horizontal(id="picker-pathrow"):
                yield Button("↑", id="picker-up")
                yield Input(self.start, id="picker-path")
            with Horizontal(classes="modal-buttons"):
                yield Button(self.ok_label, variant="primary", id="picker-ok")
                yield Button("Cancel", id="picker-cancel")
            yield Static(Text("enter/→ open · ↑↓ move · backspace parent · type a path and press enter",
                              "dim"), id="picker-hint")

    def on_mount(self) -> None:
        self._places = places()
        self.query_one("#picker-tree", LocalFolderTree).focus()

    @property
    def path(self) -> str:
        return self.query_one("#picker-path", Input).value.strip().strip('"')

    def go(self, path: str) -> None:
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(path):
            self.notify(f"Not a folder: {path}", severity="error")
            return
        tree = self.query_one("#picker-tree", LocalFolderTree)
        tree.path = path
        self.query_one("#picker-path", Input).value = path
        tree.focus()

    @on(DirectoryTree.DirectorySelected)
    def _selected(self, e: DirectoryTree.DirectorySelected) -> None:
        self.query_one("#picker-path", Input).value = str(e.path)

    @on(Tree.NodeHighlighted, "#picker-tree")
    def _highlighted(self, e: Tree.NodeHighlighted) -> None:
        if e.node.data is not None:
            self.query_one("#picker-path", Input).value = str(e.node.data.path)

    @on(Button.Pressed, ".place")
    def _place(self, e: Button.Pressed) -> None:
        self.go(self._places[int(e.button.id.split("-")[1])][1])

    @on(Input.Submitted, "#picker-path")
    def _typed(self) -> None:
        self.go(self.path)

    @on(Button.Pressed, "#picker-up")
    def action_up(self) -> None:
        if isinstance(self.focused, Input):
            return
        from pathlib import Path
        self.go(str(Path(self.query_one("#picker-tree", LocalFolderTree).path).resolve().parent))

    @on(Button.Pressed, "#picker-ok")
    def _ok(self) -> None:
        if os.path.isdir(self.path):
            self.dismiss(os.path.abspath(self.path))
        else:
            self.notify(f"Not a folder: {self.path}", severity="error")

    @on(Button.Pressed, "#picker-cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)
