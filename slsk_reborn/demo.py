"""Offline engine with fake peers. Run `slsk-reborn --demo` to explore the UI
without touching the network; the test-suite and README screenshots use it too."""
from __future__ import annotations

import asyncio
import random
import time

from .engine import Engine, FileEntry, Folder, Hit, RoomInfo, UserCard, Xfer

ARTISTS = {
    "Boards of Canada": ("Music Has the Right to Children", ["Wildlife Analysis", "An Eagle in Your Mind",
                         "Telephasic Workshop", "Roygbiv", "Aquarius", "Olson", "Turquoise Hexagon Sun"]),
    "Aphex Twin": ("Selected Ambient Works 85-92", ["Xtal", "Tha", "Pulsewidth", "Ageispolis", "Heliosphan",
                   "We Are the Music Makers", "Green Calx"]),
    "Burial": ("Untrue", ["Archangel", "Near Dark", "Ghost Hardware", "Endorphin", "Etched Headplate",
               "In McDonalds", "Untrue"]),
    "Daft Punk": ("Discovery", ["One More Time", "Aerodynamic", "Digital Love", "Harder Better Faster Stronger",
                  "Crescendolls", "Something About Us", "Veridis Quo"]),
    "Massive Attack": ("Mezzanine", ["Angel", "Risingson", "Teardrop", "Inertia Creeps", "Exchange",
                       "Dissolved Girl", "Group Four"]),
}
PEERS = ["vinylhoarder", "flac_monk", "dj_nebula", "crate_digger_77", "lowpass", "kassette", "midnight_owl",
         "subharmonic", "wax_tracks", "ozone_layer", "tapehiss", "basslinez", "glitchgarden", "ytterbium"]
CHAT = ["anyone got the 2003 vinyl rip?", "flac or bust", "thanks for the slot!", "queue is moving again",
        "that pressing is so warm", "uploading the full discography tonight", "nice taste in your shares",
        "is the server lagging for anyone else?", "brb, coffee", "lol", "check my folder 'rare b-sides'"]


def _album(artist: str, user: str, lossless: bool) -> Folder:
    album, tracks = ARTISTS[artist]
    year = random.choice([1994, 1997, 1998, 2001, 2007])
    fmt = "FLAC" if lossless else "MP3 320"
    root = f"@@{user[:5]}\\Music\\{artist}\\{year} - {album} [{fmt}]"
    ext = "flac" if lossless else "mp3"
    files = []
    for i, t in enumerate(tracks, 1):
        dur = random.randint(150, 420)
        br = random.choice([900, 1011, 1057]) if lossless else 320
        files.append(FileEntry(f"{root}\\{i:02d} - {t}.{ext}", int(dur * br * 125 * random.uniform(.97, 1.03)),
                               ext, br, dur))
    return Folder(root, files)


class DemoEngine(Engine):
    def __init__(self, cfg, bus):
        super().__init__(cfg, bus)
        self.username = cfg.username or "you"
        self._xfers: dict[tuple, Xfer] = {}
        self._tasks: set[asyncio.Task] = set()
        self._rooms: dict[str, list[str]] = {}
        self.active_download_dir = cfg.download_dir
        self._shares = [(r"D:\Music\Electronic", 3812)]
        if cfg.share_downloads or cfg.download_dir in cfg.shared_dirs:
            self._shares.insert(0, (cfg.download_dir, 214))
        self._libs: dict[str, list[Folder]] = {}
        self._stopped: set[int] = set()

    def _spawn(self, coro):
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def start(self):
        self.bus.emit("status", state="connecting", detail="demo network")
        await asyncio.sleep(0.2)
        self.connected = True
        self.bus.emit("status", state="online", detail=f"{self.username} (demo)")
        self.bus.emit("shares.scanned", folders=318, files=4026)
        self._spawn(self._uploader())
        self._spawn(self._chatter())

    async def stop(self):
        for t in list(self._tasks):
            t.cancel()

    def _lib(self, user: str) -> list[Folder]:
        if user not in self._libs:
            rnd = random.Random(user)
            artists = rnd.sample(list(ARTISTS), 3)
            self._libs[user] = [_album(a, user, rnd.random() < .5) for a in artists]
        return self._libs[user]

    # search: results trickle in like the real network
    async def search(self, query: str) -> int:
        ticket = random.randint(1, 1 << 30)
        self._spawn(self._stream(ticket, query))
        return ticket

    async def _stream(self, ticket: int, query: str):
        words = [w for w in query.lower().split() if w]
        for user in random.sample(PEERS, len(PEERS)):
            await asyncio.sleep(random.uniform(0.05, 0.4))
            free, queue, speed = random.random() < .6, random.randint(0, 40), random.randint(40_000, 9_000_000)
            hits = []
            for folder in self._lib(user):
                for f in folder.files:
                    if all(w in f.path.lower() for w in words):
                        hits.append(Hit(user, f.path, f.size, f.ext, f.bitrate, f.duration,
                                        44100, free, queue, speed))
            if ticket in self._stopped:
                return
            if hits:
                self.bus.emit("search.hits", ticket=ticket, hits=hits)

    def stop_search(self, ticket: int) -> None:
        self._stopped.add(ticket)

    # transfers
    async def download(self, user, path, size=0):
        key = (user, path, 0)
        if key in self._xfers and self._xfers[key].active:
            return
        self._xfers[key] = Xfer(key, False, user, path, "queued", size or random.randint(5, 40) * 1_000_000)
        self._spawn(self._run(key))

    async def download_folder(self, user, folder):
        n = 0
        for f in (x for fo in self._lib(user) if fo.path == folder for x in fo.files):
            await self.download(user, f.path, f.size)
            n += 1
        return n

    async def _run(self, key):
        x = self._xfers[key]
        x.state = "waiting"
        x.place = random.randint(0, 6)
        while x.place:
            await asyncio.sleep(0.6)
            if x.state != "waiting":
                return
            x.place -= 1
        x.state, x.place = "transferring", None
        rate = random.uniform(0.6, 6.0) * 1_000_000
        while x.done < x.size:
            await asyncio.sleep(0.25)
            if x.state != "transferring":
                return
            x.speed = rate * random.uniform(.7, 1.2)
            x.done = min(x.size, x.done + int(x.speed / 4))
            if random.random() < .002:
                x.state, x.reason, x.speed = "failed", "connection reset by peer", 0
                return
        x.state, x.speed = "done", 0

    async def _uploader(self):
        while True:
            await asyncio.sleep(random.uniform(3, 9))
            user = random.choice(PEERS)
            f = random.choice(random.choice(self._lib("you-share")).files)
            key = (user, f.path, 1)
            self._xfers[key] = Xfer(key, True, user, f.path, "transferring", f.size)
            x = self._xfers[key]
            rate = random.uniform(0.3, 2.5) * 1_000_000
            while x.done < x.size and x.state == "transferring":
                await asyncio.sleep(0.25)
                x.speed = rate * random.uniform(.8, 1.1)
                x.done = min(x.size, x.done + int(x.speed / 4))
            if x.state == "transferring":
                x.state, x.speed = "done", 0

    def transfers(self):
        return list(self._xfers.values())

    async def pause(self, key):
        if (x := self._xfers.get(key)) and x.active:
            x.state, x.speed = "paused", 0

    async def resume(self, key):
        if (x := self._xfers.get(key)) and x.state in ("paused", "failed", "aborted"):
            x.state, x.reason = "queued", ""
            self._spawn(self._run(key) if not x.upload else asyncio.sleep(0))

    async def abort(self, key):
        if (x := self._xfers.get(key)) and x.state not in ("done",):
            x.state, x.speed, x.reason = "aborted", 0, "requested"

    async def remove(self, key):
        self._xfers.pop(key, None)

    def speeds(self):
        d = sum(x.speed for x in self._xfers.values() if not x.upload and x.state == "transferring")
        u = sum(x.speed for x in self._xfers.values() if x.upload and x.state == "transferring")
        return d, u

    # peers
    async def browse(self, user):
        await asyncio.sleep(0.4)
        return self._lib(user)

    async def user_info(self, user):
        await asyncio.sleep(0.3)
        rnd = random.Random(user)
        return UserCard(user, "online", rnd.random() < .2, rnd.choice(["NL", "DE", "US", "JP", "BR", "GE"]),
                        rnd.randint(100_000, 9_000_000), rnd.randint(10, 90_000), rnd.randint(500, 80_000),
                        rnd.randint(40, 6_000), "Sharing is caring. Please don't queue whole discographies.",
                        rnd.random() < .6, rnd.randint(1, 8), rnd.randint(0, 40))

    # chat
    async def send_pm(self, user, text):
        async def reply():
            await asyncio.sleep(random.uniform(1, 3))
            self.bus.emit("pm", user=user, text=random.choice(CHAT), ts=time.time(), outgoing=False)
        self._spawn(reply())

    async def room_list(self):
        return [RoomInfo(n, c) for n, c in [("nicotine", 312), ("electronic", 288), ("indie", 140),
                                            ("jazz", 96), ("ambient", 77), ("vinyl", 54), ("japan", 41)]]

    async def join_room(self, room):
        users = sorted(random.sample(PEERS, 9) + [self.username])
        self._rooms[room] = users
        return users

    async def leave_room(self, room):
        self._rooms.pop(room, None)

    async def send_room(self, room, text):
        pass

    async def _chatter(self):
        while True:
            await asyncio.sleep(random.uniform(1.5, 4))
            if self._rooms:
                room = random.choice(list(self._rooms))
                self.bus.emit("room.msg", room=room, user=random.choice(PEERS), text=random.choice(CHAT),
                              ts=time.time())
            if random.random() < .05:
                self.bus.emit("pm", user=random.choice(PEERS), text="hey, can I grab your Burial folder?",
                              ts=time.time(), outgoing=False)

    # shares
    def share_stats(self):
        return 318, sum(n for _, n in self._shares)

    def shared_dirs(self):
        return list(self._shares)

    async def add_share(self, path):
        self._shares.append((path, random.randint(20, 900)))
        f, n = self.share_stats()
        self.bus.emit("shares.scanned", folders=f, files=n)

    async def remove_share(self, path):
        self._shares = [s for s in self._shares if s[0] != path]
        f, n = self.share_stats()
        self.bus.emit("shares.scanned", folders=f, files=n)

    async def rescan(self):
        await asyncio.sleep(0.5)
        f, n = self.share_stats()
        self.bus.emit("shares.scanned", folders=f, files=n)

    def apply_limits(self):
        pass
