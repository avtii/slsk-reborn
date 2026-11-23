"""Modal screens: login, user card, room list, help."""
from __future__ import annotations

import random
import string

from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, LoadingIndicator, Static

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
                yield Button("Close", id="card-close")

    def on_mount(self) -> None:
        self.load()

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
  [b]ctrl+p[/]       command palette     [b]?[/]       this help        [b]ctrl+q[/]  quit

[b $primary]Search results[/]
  [b]enter / d[/]    download file       [b]f[/]  download the whole folder
  [b]b[/]            browse user         [b]i[/]  user info       [b]m[/]  message user
  [b]s[/]            cycle sort          [b]ctrl+w[/]  close search tab
  Filter box: words to include, [b]-word[/] to exclude, [b]flac[/] / [b]mp3[/] / [b]>256[/] for quality.

[b $primary]Transfers[/]
  [b]p[/] pause   [b]r[/] resume/retry   [b]x[/] abort   [b]del[/] remove   [b]c[/] clear finished
  [b]o[/] open download folder

[b $primary]Browse[/]
  Type a username. [b]enter[/] downloads a file, [b]d[/] downloads a whole folder.

[b $primary]Chat[/]
  [b]/join room[/]  [b]/leave[/]  [b]/msg user text[/]  [b]/rooms[/]  [b]/clear[/]
  Plain text goes to the open conversation.

[b $primary]Shares[/]
  Add folders to share; they are scanned and announced. Settings save to
  ~/.slsk-reborn/config.toml and apply live.
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,question_mark", "dismiss(None)", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box", classes="modal-box"):
            yield Center(Static(logo(), id="help-logo"))
            yield Static(HELP, markup=True)
