"""Chat tab: rooms and private messages."""
from __future__ import annotations

import time

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, ContentSwitcher, Input, ListItem, ListView, RichLog, Static

from ..util import clock, user_color


def conv_id(kind: str, name: str) -> str:
    safe = "".join(c if c.isalnum() else f"_{ord(c):x}_" for c in name)
    return f"{kind}-{safe}"


class ConvItem(ListItem):
    def __init__(self, kind: str, name: str):
        self.kind, self.name_, self.unread = kind, name, 0
        self.label_widget = Static(self._label())
        super().__init__(self.label_widget, id="li-" + conv_id(kind, name))

    def _label(self) -> Text:
        icon = "#" if self.kind == "room" else "@"
        t = Text(f" {icon} ", "bold #00e5ff" if self.kind == "room" else "bold #ff2bd6")
        t.append(self.name_, "bold" if self.unread else "")
        if self.unread:
            t.append(f"  {self.unread}", "bold black on #ff2bd6")
        return t

    def bump(self, n: int = 1) -> None:
        self.unread = 0 if n == 0 else self.unread + n
        self.label_widget.update(self._label())


class ChatPane(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(id="chat-body"):
            with Vertical(id="chat-side"):
                yield Static(" Conversations", classes="side-title")
                yield ListView(id="chat-list")
                yield Button("＋ Join room", id="chat-rooms", variant="primary")
            with Vertical(id="chat-main"):
                yield Static(id="chat-header")
                yield ContentSwitcher(id="chat-logs")
                yield Input(placeholder="message…   /join room · /msg user text · /leave · /rooms · /clear",
                            id="chat-input")
            with Vertical(id="chat-users-box"):
                yield Static(" Users", classes="side-title", id="chat-users-title")
                yield ListView(id="chat-users")

    def on_mount(self) -> None:
        self.convs: dict[str, ConvItem] = {}
        self.room_users: dict[str, list[str]] = {}
        self.active: str | None = None
        bus = self.app.bus
        bus.on("pm", self._on_pm)
        bus.on("room.msg", self._on_room_msg)
        bus.on("room.user", self._on_room_user)
        bus.on("room.left", lambda room: self._close("room", room))
        self.query_one("#chat-users-box").display = False
        self.query_one("#chat-header", Static).update(Text(
            " No conversation yet — join a room or message someone (m on any search result).", "dim"))

    # ----------------------------------------------------------------- conversations
    def _ensure(self, kind: str, name: str) -> RichLog:
        cid = conv_id(kind, name)
        if cid not in self.convs:
            item = ConvItem(kind, name)
            self.convs[cid] = item
            self.query_one("#chat-list", ListView).append(item)
            log = RichLog(id=cid, wrap=True, markup=False, auto_scroll=True, classes="chat-log")
            log.display = False
            self.query_one(ContentSwitcher).mount(log)
            log.write(Text(f"── {('room #' if kind == 'room' else 'private chat with @')}{name} ──", "dim"))
            if self.active is None:
                self.call_after_refresh(self.switch, kind, name)
        return self.query_one(f"#{cid}", RichLog)

    def switch(self, kind: str, name: str) -> None:
        cid = conv_id(kind, name)
        self._ensure(kind, name)
        self.active = cid
        self.query_one(ContentSwitcher).current = cid
        self.convs[cid].bump(0)
        lv = self.query_one("#chat-list", ListView)
        idx = list(self.convs).index(cid)
        if lv.index != idx:
            lv.index = idx
        is_room = kind == "room"
        self.query_one("#chat-users-box").display = is_room
        if is_room:
            self._render_users(name)
        head = Text(f" {'#' if is_room else '@'}{name}", "bold #00e5ff" if is_room else "bold #ff2bd6")
        if is_room:
            head.append(f"   {len(self.room_users.get(name, []))} users", "dim")
        else:
            head.append("   private conversation", "dim")
        self.query_one("#chat-header", Static).update(head)

    def _render_users(self, room: str) -> None:
        lv = self.query_one("#chat-users", ListView)
        lv.clear()
        for u in self.room_users.get(room, []):
            lv.append(ListItem(Static(Text(u, user_color(u))), name=u))
        self.query_one("#chat-users-title", Static).update(f" Users ({len(self.room_users.get(room, []))})")

    def _write(self, kind: str, name: str, user: str, text: str, ts: float | None = None,
               me: bool = False) -> None:
        log = self._ensure(kind, name)
        line = Text(clock(ts) + " ", "dim")
        line.append(f"{user:>14} ", "bold " + ("#ffd23f" if me else user_color(user)))
        line.append("│ ", "#2a1f45")
        line.append(text, "italic #ffd23f" if (not me and self.app.engine.username.lower() in text.lower())
                    else "")
        log.write(line)
        cid = conv_id(kind, name)
        if cid != self.active or not self.app.is_tab_active("chat"):
            self.convs[cid].bump()
            if kind == "pm" and not me:
                self.app.notify(f"@{user}: {text[:80]}", title="Private message")
        self.app.update_chat_badge()

    def unread_total(self) -> int:
        return sum(c.unread for c in self.convs.values())

    # ----------------------------------------------------------------- bus events
    def _on_pm(self, user: str, text: str, ts: float, outgoing: bool) -> None:
        self._write("pm", user, self.app.engine.username if outgoing else user, text, ts, me=outgoing)

    def _on_room_msg(self, room: str, user: str, text: str, ts: float) -> None:
        self._write("room", room, user, text, ts)

    def _on_room_user(self, room: str, user: str, joined: bool) -> None:
        users = self.room_users.setdefault(room, [])
        if joined and user not in users:
            users.append(user)
            users.sort(key=str.lower)
        elif not joined and user in users:
            users.remove(user)
        cid = conv_id("room", room)
        if cid in self.convs:
            self.query_one(f"#{cid}", RichLog).write(
                Text(f"{clock()}  {'→' if joined else '←'} {user} {'joined' if joined else 'left'}", "dim"))
            if self.active == cid:
                self._render_users(room)

    def _close(self, kind: str, name: str) -> None:
        cid = conv_id(kind, name)
        if (item := self.convs.pop(cid, None)):
            item.remove()
            self.query_one(f"#{cid}").remove()
        if self.active == cid:
            self.active = None
            if self.convs:
                first = next(iter(self.convs.values()))
                self.call_after_refresh(self.switch, first.kind, first.name_)
            else:
                self.query_one("#chat-users-box").display = False
                self.query_one("#chat-header", Static).update(Text(" No conversation open.", "dim"))

    # ----------------------------------------------------------------- UI events
    @on(ListView.Selected, "#chat-list")
    def _pick(self, e: ListView.Selected) -> None:
        if isinstance(e.item, ConvItem):
            self.switch(e.item.kind, e.item.name_)
            self.query_one("#chat-input", Input).focus()

    @on(ListView.Selected, "#chat-users")
    def _user(self, e: ListView.Selected) -> None:
        if e.item.name:
            self.app.show_user(e.item.name)

    @on(Button.Pressed, "#chat-rooms")
    def _rooms(self) -> None:
        self.app.pick_room()

    @on(Input.Submitted, "#chat-input")
    def _send(self, e: Input.Submitted) -> None:
        text = e.value.strip()
        e.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            self._command(text)
            return
        if not self.active:
            self.notify("Open a conversation first (/join room or /msg user).", severity="warning")
            return
        item = self.convs[self.active]
        self.deliver(item.kind, item.name_, text)

    def _command(self, text: str) -> None:
        cmd, _, rest = text[1:].partition(" ")
        cmd = cmd.lower()
        if cmd in ("join", "j") and rest:
            self.join(rest.strip())
        elif cmd in ("leave", "part"):
            target = rest.strip()
            if not target and self.active and self.convs[self.active].kind == "room":
                target = self.convs[self.active].name_
            if target:
                self.leave(target)
            elif self.active:
                item = self.convs[self.active]
                self._close(item.kind, item.name_)
        elif cmd in ("msg", "m", "query") and rest:
            user, _, msg = rest.partition(" ")
            self.switch("pm", user)
            if msg:
                self.deliver("pm", user, msg)
        elif cmd == "rooms":
            self.app.pick_room()
        elif cmd == "clear" and self.active:
            self.query_one(f"#{self.active}", RichLog).clear()
        else:
            self.notify("Commands: /join room · /leave · /msg user text · /rooms · /clear")

    @work
    async def deliver(self, kind: str, name: str, text: str) -> None:
        try:
            if kind == "pm":
                await self.app.engine.send_pm(name, text)
            else:
                await self.app.engine.send_room(name, text)
        except Exception as e:
            self.notify(f"Send failed: {e}", severity="error")
            return
        self._write(kind, name, self.app.engine.username, text, time.time(), me=True)

    @work
    async def join(self, room: str) -> None:
        try:
            users = await self.app.engine.join_room(room)
        except Exception as e:
            self.notify(f"Could not join {room}: {e}", severity="error")
            return
        self.room_users[room] = users
        self._ensure("room", room)
        self.switch("room", room)
        self.app.remember_room(room, True)
        self.query_one("#chat-input", Input).focus()

    @work
    async def leave(self, room: str) -> None:
        try:
            await self.app.engine.leave_room(room)
        except Exception:
            pass
        self._close("room", room)
        self.app.remember_room(room, False)
