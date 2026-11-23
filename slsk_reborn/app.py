"""The Textual application shell: top status bar, five tabs, footer."""
from __future__ import annotations

import asyncio
import logging
import time

from rich.text import Text
from textual import work
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Static, TabbedContent, TabPane

from . import __version__
from .config import Config
from .engine import Bus, Engine, FileEntry, SlskEngine, Xfer
from .fallback import alt_query, good_enough, pick_alternative
from .panes import BrowsePane, ChatPane, SearchPane, SharesPane, TransfersPane
from .player import Player, album_queue
from .playerbar import PlayerBar
from .screens import (HelpScreen, ListsScreen, LoginScreen, RoomListScreen, TracklistScreen, UserInfoScreen,
                      WelcomeScreen)
from .theme import THEMES, mini_logo
from .util import basename, human_speed

log = logging.getLogger("slsk_reborn")

ALT_WAIT = 12.0
QUIT_WAIT = 5.0  # seconds to save transfers and log out before leaving anyway  # seconds of search results to collect when looking for another source

TABS = [("search", "⌕ Search"), ("transfers", "⇅ Transfers"), ("browse", "◉ Browse"),
        ("chat", "✉ Chat"), ("shares", "▣ Shares")]


class TopBar(Static):
    def on_mount(self) -> None:
        self.state, self.detail = "offline", "not connected"
        self.files = 0
        self.app.bus.on("status", self._status)
        self.app.bus.on("shares.scanned", self._scanned)
        self.set_interval(0.5, self.redraw)
        self.redraw()

    def _status(self, state: str, detail: str = "") -> None:
        self.state, self.detail = state, detail
        self.redraw()

    def _scanned(self, folders: int, files: int) -> None:
        self.files = files

    def redraw(self) -> None:
        app = self.app
        t = mini_logo()
        t.append(f" v{__version__}   ", "dim")
        dot = {"online": ("●", "bold #39ff88"), "connecting": ("◌", "bold #ffd23f")}.get(
            self.state, ("●", "bold #ff4d6d"))
        t.append(dot[0] + " ", dot[1])
        t.append(self.state, dot[1])
        t.append(f" {self.detail}   ", "#b388ff")
        d, u = app.engine.speeds()
        xs = app.engine.transfers()
        t.append("▼ ", "bold #00e5ff")
        t.append(f"{human_speed(d):>9}  ", "#00e5ff")
        t.append("▲ ", "bold #ff2bd6")
        t.append(f"{human_speed(u):>9}   ", "#ff2bd6")
        act = sum(x.state == "transferring" for x in xs)
        t.append(f"⇅ {act} active  ", "bold" if act else "dim")
        t.append(f"▣ {self.files:,} shared", "#39ff88")
        t.append(f"   {time.strftime('%H:%M')}", "dim")
        self.update(t)


class SlskApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "slsk-reborn"
    BINDINGS = [
        Binding("1", "tab('search')", "Search", show=False),
        Binding("2", "tab('transfers')", "Transfers", show=False),
        Binding("3", "tab('browse')", "Browse", show=False),
        Binding("4", "tab('chat')", "Chat", show=False),
        Binding("5", "tab('shares')", "Shares", show=False),
        Binding("f2", "tab('search')", "Search", show=False),
        Binding("f3", "tab('transfers')", "Transfers", show=False),
        Binding("f4", "tab('browse')", "Browse", show=False),
        Binding("f5", "tab('chat')", "Chat", show=False),
        Binding("f6", "tab('shares')", "Shares", show=False),
        Binding("escape", "unfocus", "Leave input", show=False),
        # player
        Binding("space", "play_pause", "Play/Pause", show=False),
        # arrows (and keypad arrows) seek while something plays; otherwise they pass through
        Binding("left", "arrow_seek(-10)", "-10s", show=False, priority=True),
        Binding("right", "arrow_seek(10)", "+10s", show=False, priority=True),
        Binding("shift+left", "arrow_seek(-60)", "-1m", show=False, priority=True),
        Binding("shift+right", "arrow_seek(60)", "+1m", show=False, priority=True),
        Binding("left_square_bracket", "seek(-10)", "-10s", show=False),
        Binding("right_square_bracket", "seek(10)", "+10s", show=False),
        Binding("minus", "volume(-0.1)", "Vol -", show=False),
        Binding("equals_sign,plus", "volume(0.1)", "Vol +", show=False),
        Binding("less_than_sign,comma", "track(-1)", "Prev", show=False),
        Binding("greater_than_sign,full_stop", "track(1)", "Next", show=False),
        Binding("backslash", "stop_playback", "Stop", show=False),
        Binding("slash,ctrl+f", "new_search", "Search", key_display="/"),
        Binding("question_mark,f1", "help", "Help", key_display="?"),
        Binding("ctrl+t", "cycle_theme", "Theme"),
        Binding("ctrl+l", "lists", "Lists"),
        Binding("ctrl+o", "tracklist", "Tracklist"),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(self, cfg: Config, demo: bool = False, tracklist: str = ""):
        super().__init__()
        self.cfg = cfg
        self.demo = demo
        self.tracklist_path = tracklist  # --tracklist FILE: opened once logged in
        self.bus = Bus()
        self.engine: Engine = self._make_engine()
        self.player = Player()
        self._alt_running: set[tuple] = set()
        self.player.set_volume(cfg.volume)

    def _make_engine(self) -> Engine:
        if self.demo:
            from .demo import DemoEngine
            return DemoEngine(self.cfg, self.bus)
        return SlskEngine(self.cfg, self.bus)

    def compose(self) -> ComposeResult:
        yield TopBar(id="topbar")
        with TabbedContent(id="main", initial="search"):
            with TabPane(TABS[0][1], id="search"):
                yield SearchPane()
            with TabPane(TABS[1][1], id="transfers"):
                yield TransfersPane()
            with TabPane(TABS[2][1], id="browse"):
                yield BrowsePane()
            with TabPane(TABS[3][1], id="chat"):
                yield ChatPane()
            with TabPane(TABS[4][1], id="shares"):
                yield SharesPane()
        yield PlayerBar(id="playerbar")
        yield Footer()

    def on_mount(self) -> None:
        for th in THEMES:
            self.register_theme(th)
        self.theme = self.cfg.theme if self.cfg.theme in {t.name for t in THEMES} else THEMES[0].name
        self.query_one(SearchPane).focus_input()
        self._quitting = False
        self._catch_signals()
        if self.demo or self.cfg.has_credentials:
            self.connect()
        else:
            self.ask_login()

    # ------------------------------------------------------------------ connection
    def ask_login(self, error: str = "") -> None:
        def done(result):
            if result is None:
                self.exit()
                return
            self.cfg.username, self.cfg.password = result
            self.engine.username = result[0]
            self.cfg.save()
            self.connect()

        self.push_screen(LoginScreen(self.cfg.username, error), done)

    @work(exclusive=True, group="connect")
    async def connect(self) -> None:
        try:
            await self.engine.start()
        except Exception as e:
            log.exception("connect failed")
            await self.engine.stop()
            self.bus.emit("status", state="offline", detail=str(e)[:60])
            name = type(e).__name__
            if name == "AuthenticationError":
                reason = getattr(e, "reason", "") or "wrong password?"
                self.engine = self._make_engine()
                self.ask_login(f"Login refused: {reason}")
            else:
                self.notify(f"Could not connect: {name}: {e}", severity="error", timeout=10)
            return
        self.notify(f"Logged in as {self.engine.username}", title="● online")
        self.bus.emit("log", msg=f"logged in as {self.engine.username}", level="info")
        self.query_one(SharesPane).refresh_table()
        for room in list(self.cfg.auto_join_rooms):
            self.query_one(ChatPane).join(room)
        self.first_run_notes()
        if self.tracklist_path:
            path, self.tracklist_path = self.tracklist_path, ""
            self.action_tracklist(path)

    def action_tracklist(self, path: str = "") -> None:
        def done(res):
            if res:
                tracks, lossless, name = res
                self.action_tab("search")
                self.query_one(SearchPane).open_tracklist(tracks, lossless, name)

        self.push_screen(TracklistScreen(path), done)

    def first_run_notes(self) -> None:
        """Once: explain sharing and ports. Later: remind if nothing is shared."""
        if self.demo:
            return
        files = self.engine.share_stats()[1]
        if not self.cfg.welcomed:
            self.cfg.welcomed = True
            self.cfg.save()

            def done(choice):
                if choice == "share":
                    self.action_tab("shares")
                    self.query_one(SharesPane).browse_for_share()

            self.push_screen(WelcomeScreen(self.cfg.listen_port, self.cfg.upnp, files), done)
        else:
            self.set_timer(30, self._remind_if_nothing_shared)  # after the startup scan

    def _remind_if_nothing_shared(self) -> None:
        if self.engine.connected and not self.engine.share_stats()[1]:
            self.notify("You share no files. Soulseek works by sharing: add a folder in Shares (5).",
                        title="Nothing shared", severity="warning", timeout=10)

    async def action_quit(self) -> None:
        if self._quitting:  # pressed again while disconnecting: leave now
            self.exit()
            return
        self._quitting = True
        self.notify("Saving transfers and disconnecting… (ctrl+c again to leave now)")
        try:  # open search tabs come back on the next start, like the transfers
            self.query_one("SearchPane").save_session()
        except Exception:
            log.warning("could not save the open searches", exc_info=True)
        try:
            self.player.close()
            if not self.demo and abs(self.cfg.volume - self.player.volume) > 0.001:
                self.cfg.volume = self.player.volume
                self.cfg.save()
            await asyncio.wait_for(self.engine.stop(), QUIT_WAIT)
        except Exception:  # a slow or broken disconnect must not keep the app open
            log.warning("unclean shutdown", exc_info=True)
        self.exit()

    def action_help_quit(self) -> None:
        """ctrl+c (with no text selected to copy) quits like ctrl+q, cleanly."""
        self.run_worker(self.action_quit(), exclusive=False)

    def _catch_signals(self) -> None:
        """SIGINT/SIGTERM from outside (kill, a closing terminal) also take the clean path."""
        import signal
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: self.call_later(self.action_help_quit))
            except (NotImplementedError, RuntimeError, ValueError):
                pass  # Windows: console ctrl+c arrives as a key; main() catches the rest

    # ------------------------------------------------------------------ navigation
    def action_tab(self, tab: str) -> None:
        self.query_one("#main", TabbedContent).active = tab
        if tab == "chat":
            self.update_chat_badge()

    def action_unfocus(self) -> None:
        """Escape leaves a text box so single-key shortcuts work again."""
        from textual.widgets import DataTable, Input, Tree
        if isinstance(self.focused, Input):
            pane = self.query_one("#main", TabbedContent).active_pane
            target = None
            if pane is not None:
                target = pane.query(DataTable).first() if pane.query(DataTable) else (
                    pane.query(Tree).first() if pane.query(Tree) else None)
            self.set_focus(target)

    def is_tab_active(self, tab: str) -> bool:
        return self.query_one("#main", TabbedContent).active == tab

    def action_new_search(self) -> None:
        self.action_tab("search")
        self.query_one(SearchPane).focus_input()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_cycle_theme(self) -> None:
        names = [t.name for t in THEMES]
        nxt = names[(names.index(self.theme) + 1) % len(names)] if self.theme in names else names[0]
        self.theme = nxt
        self.cfg.theme = nxt
        if not self.demo:
            self.cfg.save()
        self.notify(f"Theme: {nxt}")

    def on_tabbed_content_tab_activated(self, e: TabbedContent.TabActivated) -> None:
        if e.tabbed_content.id == "main" and e.pane.id == "chat":
            chat = self.query_one(ChatPane)
            if chat.active:
                chat.convs[chat.active].bump(0)
            self.update_chat_badge()

    def update_chat_badge(self) -> None:
        n = self.query_one(ChatPane).unread_total()
        try:
            self.query_one("#main", TabbedContent).get_tab("chat").label = (
                f"✉ Chat [b reverse] {n} [/]" if n else "✉ Chat")
        except Exception:
            pass

    # ------------------------------------------------------------------ player
    def play_file(self, path: str) -> None:
        """Play a local file; the rest of its folder follows as the queue."""
        files, i = album_queue(path)
        if self.player.play_files(files, i):
            self.query_one(PlayerBar).tick()
        else:
            self.notify(self.player.error or "can't play this file", title="Player", severity="warning")

    def action_play_pause(self) -> None:
        if self.player.queue:
            self.player.toggle()
            self.query_one(PlayerBar).tick()

    def action_seek(self, delta: float) -> None:
        self.player.seek_by(delta)
        self.query_one(PlayerBar).tick()

    def action_arrow_seek(self, delta: float) -> None:
        from textual.widgets import Input, TextArea
        if (not self.player.queue or self.player.state not in ("playing", "paused")
                or isinstance(self.focused, (Input, TextArea)) or len(self.screen_stack) > 1):
            raise SkipAction()  # the key goes to the focused widget as usual
        self.action_seek(delta)

    def action_volume(self, delta: float) -> None:
        self.player.set_volume(self.player.volume + delta)
        if self.player.state != "playing" and self.player.queue:
            self.notify(f"Volume {int(self.player.volume * 100)}%")

    def action_track(self, step: int) -> None:
        if not self.player.queue:
            return
        if step < 0:
            self.player.prev()
        elif not self.player.next():
            self.notify("End of the queue")
        self.query_one(PlayerBar).tick()

    def action_stop_playback(self) -> None:
        self.player.stop()
        self.query_one(PlayerBar).tick()

    # ------------------------------------------------------------------ actions used by panes
    def start_download(self, user: str, path: str, size: int = 0) -> None:
        self._download(user, path, size)

    @work
    async def _download(self, user: str, path: str, size: int) -> None:
        try:
            await self.engine.download(user, path, size)
        except Exception as e:
            self.notify(f"Download failed: {e}", severity="error")
            return
        name = path.replace("/", "\\").rsplit("\\", 1)[-1]
        self.notify(f"{name}\nfrom {user}", title="▼ queued")

    def start_many(self, user: str, files: list[FileEntry]) -> None:
        self._many(user, files)

    @work
    async def _many(self, user: str, files: list[FileEntry]) -> None:
        for f in files:
            try:
                await self.engine.download(user, f.path, f.size)
            except Exception as e:
                self.notify(f"Queue failed: {e}", severity="error")
                return
        self.notify(f"{len(files)} files from {user}", title="▼ folder queued")

    def start_folder_download(self, user: str, folder: str) -> None:
        self._folder(user, folder)

    @work
    async def _folder(self, user: str, folder: str) -> None:
        self.notify(f"Asking {user} for the folder contents…")
        try:
            n = await self.engine.download_folder(user, folder)
        except Exception as e:
            self.notify(f"Folder download failed: {type(e).__name__} {e}", severity="error")
            return
        self.notify(f"{n} files from {user}", title="▼ folder queued")

    def find_alternative(self, x: Xfer, auto: bool = False) -> None:
        """Look for the same file at another user; queue the best copy and drop this one."""
        if x.key in self._alt_running:
            return
        self._alt_running.add(x.key)
        self._alternative(x, auto)

    @work
    async def _alternative(self, x: Xfer, auto: bool) -> None:
        name = basename(x.path)
        try:
            q = alt_query(x.path)
            if not q:
                self.notify(f"Can't build a search from “{name}”", severity="warning")
                return
            if not auto:
                self.notify(f"Searching for “{q}”…", title="↻ other source")
            found: list = []

            def collect(ticket: int, hits: list) -> None:
                if ticket == tk:
                    found.extend(hits)

            tk = None
            self.bus.on("search.hits", collect)
            try:
                tk = await self.engine.search(q)
                for _ in range(int(ALT_WAIT / 0.5)):
                    await asyncio.sleep(0.5)
                    if good_enough(x, found):
                        break
            finally:
                self.bus.off("search.hits", collect)
                if tk is not None:
                    self.engine.stop_search(tk)
            h = pick_alternative(x, found)
            if h is None:
                self.notify(f"{name}: no other copy found ({len(found)} results)",
                            title="↻ other source", severity="warning", timeout=6)
                return
            await self.engine.download(h.user, h.path, h.size)
            if x.active:
                await self.engine.abort(x.key)
            await self.engine.remove(x.key)
            note = "free slot" if h.free_slot else f"queue {h.queue}"
            self.notify(f"{name}\n{x.user} → {h.user} ({note})", title="↻ switched source", timeout=6)
        except Exception as e:
            self.notify(f"Other source failed: {type(e).__name__} {e}", severity="warning")
        finally:
            self._alt_running.discard(x.key)

    def browse_user(self, user: str, focus_path: str | None = None) -> None:
        self.action_tab("browse")
        self.query_one(BrowsePane).load(user, focus_path)

    def show_user(self, user: str) -> None:
        def done(what):
            if what == "browse":
                self.browse_user(user)
            elif what == "message":
                self.open_pm(user)

        self.push_screen(UserInfoScreen(user), done)

    def set_listed(self, key: str, value: str, on: bool) -> bool:
        """Add to / remove from cfg.wishlist, friends or blocked; saved and applied at once."""
        items: list[str] = getattr(self.cfg, key)
        if on == (value in items):
            return False
        if on:
            items.append(value)
            other = {"friends": "blocked", "blocked": "friends"}.get(key)
            if other and value in getattr(self.cfg, other):  # can't be both
                getattr(self.cfg, other).remove(value)
        else:
            items.remove(value)
        self.cfg.save()
        self.engine.apply_lists()
        return True

    def action_lists(self) -> None:
        def done(pick):
            if not pick:
                return
            kind, value = pick
            if kind == "search":
                self.action_tab("search")
                self.query_one(SearchPane).new_search(value)
            else:
                self.show_user(value)

        self.push_screen(ListsScreen(), done)

    def open_pm(self, user: str) -> None:
        self.action_tab("chat")
        chat = self.query_one(ChatPane)
        chat.switch("pm", user)
        chat.query_one("#chat-input").focus()

    def pick_room(self) -> None:
        def done(room):
            if room:
                self.action_tab("chat")
                self.query_one(ChatPane).join(room)

        self.push_screen(RoomListScreen(), done)

    def remember_room(self, room: str, joined: bool) -> None:
        rooms = self.cfg.auto_join_rooms
        if joined and room not in rooms:
            rooms.append(room)
        elif not joined and room in rooms:
            rooms.remove(room)
        if not self.demo:
            self.cfg.save()
