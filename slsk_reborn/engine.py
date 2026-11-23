"""Network engine: a thin, UI-friendly facade over aioslsk.

The UI only talks to :class:`Engine`. Everything it gets back is a plain
dataclass from this module, so the panes never touch aioslsk objects and the
offline :class:`slsk_reborn.demo.DemoEngine` can stand in for the real network.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .config import Config
from .util import ext_of

log = logging.getLogger("slsk_reborn")

# ----------------------------------------------------------------------------- models


@dataclass
class Hit:
    user: str
    path: str
    size: int
    ext: str
    bitrate: Optional[int] = None
    duration: Optional[int] = None
    samplerate: Optional[int] = None
    free_slot: bool = False
    queue: int = 0
    speed: int = 0
    locked: bool = False


@dataclass
class FileEntry:
    path: str  # full remote path
    size: int
    ext: str
    bitrate: Optional[int] = None
    duration: Optional[int] = None


@dataclass
class Folder:
    path: str  # full remote directory path
    files: list[FileEntry] = field(default_factory=list)
    locked: bool = False


@dataclass
class Xfer:
    key: tuple
    upload: bool
    user: str
    path: str
    state: str  # queued, waiting, transferring, done, failed, aborted, paused, incomplete
    size: int = 0
    done: int = 0
    speed: float = 0.0
    place: Optional[int] = None
    reason: str = ""
    local_path: str = ""
    added: float = field(default_factory=time.time)

    @property
    def fraction(self) -> float:
        return self.done / self.size if self.size else (1.0 if self.state == "done" else 0.0)

    @property
    def active(self) -> bool:
        return self.state in ("queued", "waiting", "transferring", "incomplete")


@dataclass
class UserCard:
    name: str
    status: str = "?"
    privileged: bool = False
    country: str = ""
    avg_speed: int = 0
    uploads: int = 0
    files: int = 0
    folders: int = 0
    description: str = ""
    free_slots: Optional[bool] = None
    upload_slots: Optional[int] = None
    queue: Optional[int] = None


@dataclass
class RoomInfo:
    name: str
    users: int = 0
    private: bool = False


# ----------------------------------------------------------------------------- event bus


class Bus:
    """Synchronous pub/sub. Engine and UI run on the same asyncio loop."""

    def __init__(self):
        self._subs: dict[str, list[Callable]] = defaultdict(list)

    def on(self, name: str, fn: Callable) -> None:
        self._subs[name].append(fn)

    def emit(self, name: str, **data) -> None:
        for fn in list(self._subs.get(name, ())):
            try:
                fn(**data)
            except Exception:  # never let one broken widget kill the network loop
                log.exception("bus listener for %s failed", name)


class Engine:
    """Interface the UI programs against."""

    def __init__(self, cfg: Config, bus: Bus):
        self.cfg = cfg
        self.bus = bus
        self.connected = False
        self.username = cfg.username

    # lifecycle
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    # search
    async def search(self, query: str) -> int: ...
    def stop_search(self, ticket: int) -> None: ...

    # transfers
    async def download(self, user: str, path: str, size: int = 0) -> None: ...
    async def download_folder(self, user: str, folder: str) -> int: ...
    def transfers(self) -> list[Xfer]: ...
    async def pause(self, key: tuple) -> None: ...
    async def resume(self, key: tuple) -> None: ...
    async def abort(self, key: tuple) -> None: ...
    async def remove(self, key: tuple) -> None: ...
    def speeds(self) -> tuple[float, float]: ...

    # peers
    async def browse(self, user: str) -> list[Folder]: ...
    async def user_info(self, user: str) -> UserCard: ...

    # chat
    async def send_pm(self, user: str, text: str) -> None: ...
    async def room_list(self) -> list[RoomInfo]: ...
    async def join_room(self, room: str) -> list[str]: ...
    async def leave_room(self, room: str) -> None: ...
    async def send_room(self, room: str, text: str) -> None: ...

    # shares
    def share_stats(self) -> tuple[int, int]: ...
    def shared_dirs(self) -> list[tuple[str, int]]: ...
    async def add_share(self, path: str) -> None: ...
    async def remove_share(self, path: str) -> None: ...
    async def rescan(self) -> None: ...
    def apply_limits(self) -> None: ...


# ----------------------------------------------------------------------------- real engine

_STATE_NAMES = {
    "VIRGIN": "queued", "QUEUED": "queued", "INITIALIZING": "waiting",
    "DOWNLOADING": "transferring", "UPLOADING": "transferring", "COMPLETE": "done",
    "FAILED": "failed", "ABORTED": "aborted", "PAUSED": "paused", "INCOMPLETE": "incomplete",
}


def _directory_command(user: str, folder: str):
    """PeerGetDirectoryContentCommand with its ticket picked up front.

    aioslsk 1.7.2 builds the expected-reply filter before send(), but this
    command only picks its ticket inside send(), so the filter waits for
    ticket None and every folder request times out. Pick it first.
    """
    from aioslsk.commands import PeerGetDirectoryContentCommand
    from aioslsk.protocol.messages import PeerDirectoryContentsRequest

    class Cmd(PeerGetDirectoryContentCommand):
        def build_expected_response(self, client):
            if self._ticket is None:
                self._ticket = next(client.ticket_generator)
            return super().build_expected_response(client)

        async def send(self, client):
            if self._ticket is None:
                self._ticket = next(client.ticket_generator)
            await client.network.send_peer_messages(
                self.username, PeerDirectoryContentsRequest.Request(self._ticket, self.directory))

    return Cmd(user, folder)


class SlskEngine(Engine):
    def __init__(self, cfg: Config, bus: Bus):
        super().__init__(cfg, bus)
        self.client = None
        self._searches: dict[int, object] = {}
        self._by_key: dict[tuple, object] = {}

    # ------------------------------------------------------------------ lifecycle
    def _settings(self):
        from aioslsk.settings import (CredentialsSettings, ListeningSettings, NetworkLimitSettings,
                                      NetworkSettings, ReconnectSettings, RoomsSettings,
                                      SearchReceiveSettings, SearchSendSettings, SearchSettings,
                                      ServerSettings, Settings, SharedDirectorySettingEntry,
                                      SharesSettings, TransferLimitSettings, TransfersSettings,
                                      UpnpSettings, UserInfoSettings, UsersSettings,
                                      WishlistSettingEntry)
        c = self.cfg
        dirs = list(dict.fromkeys(c.shared_dirs + ([c.download_dir] if c.share_downloads else [])))
        return Settings(
            credentials=CredentialsSettings(username=c.username, password=c.password,
                                            info=UserInfoSettings(description=c.description)),
            network=NetworkSettings(
                server=ServerSettings(reconnect=ReconnectSettings(auto=True)),
                listening=ListeningSettings(port=c.listen_port, obfuscated_port=c.listen_port + 1),
                upnp=UpnpSettings(enabled=c.upnp),
                limits=NetworkLimitSettings(upload_speed_kbps=c.upload_limit_kbps,
                                            download_speed_kbps=c.download_limit_kbps)),
            searches=SearchSettings(
                send=SearchSendSettings(request_timeout=c.search_timeout),
                receive=SearchReceiveSettings(max_results=100),
                wishlist=[WishlistSettingEntry(query=q) for q in c.wishlist]),
            shares=SharesSettings(download=c.download_dir,
                                  directories=[SharedDirectorySettingEntry(path=d) for d in dirs
                                               if os.path.isdir(d)]),
            transfers=TransfersSettings(limits=TransferLimitSettings(upload_slots=c.upload_slots)),
            rooms=RoomsSettings(auto_join=False),
            users=UsersSettings(friends=set(c.friends)),
        )

    async def start(self) -> None:
        from aioslsk.client import SoulSeekClient
        from aioslsk.events import (PrivateMessageEvent, RoomJoinedEvent, RoomLeftEvent,
                                    RoomMessageEvent, ScanCompleteEvent, SearchRequestReceivedEvent,
                                    SearchResultEvent, ServerReconnectedEvent,
                                    SessionDestroyedEvent, SessionInitializedEvent)
        from aioslsk.naming import (DefaultNamingStrategy, KeepDirectoryStrategy,
                                    NumberDuplicateStrategy)
        from aioslsk.shares.cache import SharesShelveCache
        from aioslsk.transfer.cache import TransferShelveCache

        Path(self.cfg.download_dir).mkdir(parents=True, exist_ok=True)
        data = self.cfg.data_dir
        data.mkdir(parents=True, exist_ok=True)

        self.client = SoulSeekClient(self._settings(),
                                     shares_cache=SharesShelveCache(str(data)),
                                     transfer_cache=TransferShelveCache(str(data)))
        # keep the remote album folder: Downloads/<album>/<file>
        self.client.shares.naming_strategies = [DefaultNamingStrategy(), KeepDirectoryStrategy(),
                                                NumberDuplicateStrategy()]
        ev = self.client.events
        ev.register(SearchResultEvent, self._on_search_result)
        ev.register(PrivateMessageEvent, self._on_pm)
        ev.register(RoomMessageEvent, self._on_room_msg)
        ev.register(RoomJoinedEvent, self._on_room_joined)
        ev.register(RoomLeftEvent, self._on_room_left)
        ev.register(ScanCompleteEvent, self._on_scan)
        ev.register(SearchRequestReceivedEvent, self._on_search_received)
        ev.register(SessionInitializedEvent, self._on_session)
        ev.register(SessionDestroyedEvent, self._on_session_lost)
        ev.register(ServerReconnectedEvent, self._on_reconnected)

        self.bus.emit("status", state="connecting", detail="server.slsknet.org:2416")
        await self.client.start()
        await self.client.login()
        self.connected = True
        self.bus.emit("status", state="online", detail=self.cfg.username)

    async def stop(self) -> None:
        if self.client:
            try:
                await asyncio.wait_for(self.client.stop(), 10)
            except Exception:
                log.exception("stop failed")
        self.connected = False

    # ------------------------------------------------------------------ events
    def _on_session(self, event):
        self.connected = True
        self.bus.emit("status", state="online", detail=self.cfg.username)

    def _on_session_lost(self, event):
        self.connected = False
        self.bus.emit("status", state="offline", detail="connection lost - reconnecting")

    async def _on_reconnected(self, event):
        try:
            await self.client.login()
        except Exception as e:
            self.bus.emit("log", msg=f"re-login failed: {e}", level="error")

    def _on_search_result(self, event):
        ticket = event.query.ticket
        if ticket not in self._searches:
            return
        r = event.result
        hits = [self._hit(r, f, False) for f in r.shared_items]
        hits += [self._hit(r, f, True) for f in r.locked_results]
        hits = [h for h in hits if not self.cfg.min_bitrate or not h.bitrate
                or h.bitrate >= self.cfg.min_bitrate]
        if hits:
            self.bus.emit("search.hits", ticket=ticket, hits=hits)

    @staticmethod
    def _attrs(f) -> dict:
        from aioslsk.protocol.primitives import AttributeKey
        a = {x.key: x.value for x in (f.attributes or [])}
        return {"bitrate": a.get(AttributeKey.BITRATE.value),
                "duration": a.get(AttributeKey.DURATION.value),
                "samplerate": a.get(AttributeKey.SAMPLE_RATE.value)}

    def _hit(self, r, f, locked: bool) -> Hit:
        ext = (f.extension or ext_of(f.filename)).lower().lstrip(".") or ext_of(f.filename)
        return Hit(user=r.username, path=f.filename, size=f.filesize, ext=ext, free_slot=r.has_free_slots,
                   queue=r.queue_size, speed=r.avg_speed, locked=locked, **self._attrs(f))

    def _on_pm(self, event):
        m = event.message
        self.bus.emit("pm", user=m.user.name, text=m.message, ts=m.timestamp, outgoing=False)

    def _on_room_msg(self, event):
        m = event.message
        if self.client.session and m.user.name == self.client.session.user.name:
            return  # our own echo, already shown
        self.bus.emit("room.msg", room=m.room.name, user=m.user.name, text=m.message, ts=m.timestamp)

    def _on_room_joined(self, event):
        if event.user is not None:
            self.bus.emit("room.user", room=event.room.name, user=event.user.name, joined=True)

    def _on_room_left(self, event):
        if event.user is not None:
            self.bus.emit("room.user", room=event.room.name, user=event.user.name, joined=False)
        else:
            self.bus.emit("room.left", room=event.room.name)

    def _on_scan(self, event):
        self.bus.emit("shares.scanned", folders=event.folder_count, files=event.file_count)

    def _on_search_received(self, event):
        if event.result_count:
            self.bus.emit("log", level="info",
                          msg=f"{event.username} searched “{event.query}” → {event.result_count} hits")

    # ------------------------------------------------------------------ search
    async def search(self, query: str) -> int:
        req = await self.client.searches.search(query)
        self._searches[req.ticket] = req
        return req.ticket

    def stop_search(self, ticket: int) -> None:
        req = self._searches.pop(ticket, None)
        if req is not None:
            try:
                self.client.searches.remove_request(req)
            except Exception:
                pass

    # ------------------------------------------------------------------ transfers
    async def download(self, user: str, path: str, size: int = 0) -> None:
        await self.client.transfers.download(user, path)

    async def download_folder(self, user: str, folder: str) -> int:
        from aioslsk.transfer.model import TransferDirection
        dirs = await self.client(_directory_command(user, folder), response=True, timeout=60)
        have = {(t.username, t.remote_path) for t in self.client.transfers.transfers
                if t.direction == TransferDirection.DOWNLOAD
                and _STATE_NAMES.get(t.state.VALUE.name) not in ("failed", "aborted")}
        n = 0
        for d in dirs or []:
            for f in d.files:
                full = f.filename if ("\\" in f.filename or "/" in f.filename) else f"{d.name}\\{f.filename}"
                if (user, full) in have:
                    continue  # already downloaded or on its way
                await self.client.transfers.download(user, full)
                n += 1
        return n

    def _view(self, t) -> Xfer:
        from aioslsk.transfer.model import TransferDirection
        key = (t.username, t.remote_path, t.direction.value)
        self._by_key[key] = t
        st = _STATE_NAMES.get(t.state.VALUE.name, t.state.VALUE.name.lower())
        if st == "queued" and t.remotely_queued:
            st = "waiting"
        return Xfer(key=key, upload=t.direction == TransferDirection.UPLOAD, user=t.username,
                    path=t.remote_path, state=st, size=t.filesize or 0, done=t.bytes_transfered,
                    speed=t.get_speed() if st == "transferring" else 0.0, place=t.place_in_queue,
                    reason=t.fail_reason or t.abort_reason or "", local_path=t.local_path or "",
                    added=t.start_time or 0)

    def transfers(self) -> list[Xfer]:
        if not self.client:
            return []
        return [self._view(t) for t in self.client.transfers.transfers]

    async def pause(self, key):
        if (t := self._by_key.get(key)):
            await self.client.transfers.pause(t)

    async def resume(self, key):
        if (t := self._by_key.get(key)):
            await self.client.transfers.queue(t)

    async def abort(self, key):
        if (t := self._by_key.get(key)):
            await self.client.transfers.abort(t)

    async def remove(self, key):
        if (t := self._by_key.pop(key, None)):
            await self.client.transfers.remove(t)

    def speeds(self):
        if not self.client:
            return 0.0, 0.0
        return self.client.transfers.get_download_speed(), self.client.transfers.get_upload_speed()

    # ------------------------------------------------------------------ peers
    async def browse(self, user: str) -> list[Folder]:
        from aioslsk.commands import PeerGetSharesCommand
        dirs, locked = await self.client(PeerGetSharesCommand(user), response=True, timeout=120)
        out = []
        for group, is_locked in ((dirs, False), (locked, True)):
            for d in group:
                files = []
                for f in d.files:
                    full = f"{d.name}\\{f.filename}"
                    a = self._attrs(f)
                    files.append(FileEntry(full, f.filesize, (f.extension or ext_of(f.filename)).lower(),
                                           a["bitrate"], a["duration"]))
                out.append(Folder(d.name, files, is_locked))
        return out

    async def user_info(self, user: str) -> UserCard:
        from aioslsk.commands import (GetUserStatsCommand, GetUserStatusCommand,
                                      PeerGetUserInfoCommand)
        card = UserCard(user)
        try:
            st = await self.client(GetUserStatusCommand(user), response=True, timeout=10)
            card.status, card.privileged = st.status.name.lower(), st.privileged
            stats = await self.client(GetUserStatsCommand(user), response=True, timeout=10)
            card.avg_speed, card.uploads = stats.avg_speed, stats.uploads
            card.files, card.folders = stats.shared_file_count, stats.shared_folder_count
        except Exception as e:
            log.debug("server user info failed: %s", e)
        u = self.client.users.get_user_object(user)
        card.country = u.country or ""
        try:
            info = await self.client(PeerGetUserInfoCommand(user), response=True, timeout=30)
            card.description = info.description or ""
            card.free_slots, card.upload_slots, card.queue = (info.has_slots_free, info.upload_slots,
                                                              info.queue_length)
        except Exception as e:
            card.description = f"(peer did not answer: {type(e).__name__})"
        return card

    # ------------------------------------------------------------------ chat
    async def send_pm(self, user: str, text: str) -> None:
        from aioslsk.commands import PrivateMessageCommand
        await self.client(PrivateMessageCommand(user, text))

    async def room_list(self) -> list[RoomInfo]:
        from aioslsk.commands import GetRoomListCommand
        rooms = await self.client(GetRoomListCommand(), response=True, timeout=20)
        return sorted((RoomInfo(r.name, r.user_count, r.private) for r in rooms or []),
                      key=lambda r: -r.users)

    async def join_room(self, room: str) -> list[str]:
        from aioslsk.commands import JoinRoomCommand
        r = await self.client(JoinRoomCommand(room), response=True, timeout=20)
        return sorted(u.name for u in r.users)

    async def leave_room(self, room: str) -> None:
        from aioslsk.commands import LeaveRoomCommand
        await self.client(LeaveRoomCommand(room))

    async def send_room(self, room: str, text: str) -> None:
        from aioslsk.commands import RoomMessageCommand
        await self.client(RoomMessageCommand(room, text))

    # ------------------------------------------------------------------ shares
    def share_stats(self) -> tuple[int, int]:
        return self.client.shares.get_stats() if self.client else (0, 0)

    def shared_dirs(self) -> list[tuple[str, int]]:
        if not self.client:
            return []
        return [(d.absolute_path, len(d.items)) for d in self.client.shares.shared_directories]

    async def add_share(self, path: str) -> None:
        d = self.client.shares.add_shared_directory(path)
        await self.client.shares.scan_directory_files(d)
        await self.client.shares.scan_directory_file_attributes(d)
        await self.client.shares.report_shares()
        self.bus.emit("shares.scanned", folders=self.share_stats()[0], files=self.share_stats()[1])

    async def remove_share(self, path: str) -> None:
        self.client.shares.remove_shared_directory(path)
        await self.client.shares.report_shares()
        self.bus.emit("shares.scanned", folders=self.share_stats()[0], files=self.share_stats()[1])

    async def rescan(self) -> None:
        await self.client.shares.scan()

    def apply_limits(self) -> None:
        if not self.client:
            return
        s = self.client.settings
        s.transfers.limits.upload_slots = self.cfg.upload_slots
        s.network.limits.upload_speed_kbps = self.cfg.upload_limit_kbps
        s.network.limits.download_speed_kbps = self.cfg.download_limit_kbps
        s.credentials.info.description = self.cfg.description
        self.client.network.load_speed_limits()
