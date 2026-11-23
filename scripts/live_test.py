"""Live end-to-end check against the real Soulseek network.

Two throwaway accounts (random names, registered on first login) run side by
side on different ports. A shares a folder of generated files; B finds them,
browses A, downloads a file and the folder, and they exchange messages.

    python scripts/live_test.py [--port-a 62000] [--port-b 62100] [--keep]

Both clients run on this machine. Peer addresses come from the server as
your public IP, which most routers won't loop back to (no NAT hairpinning),
so by default the two test accounts reach each other on 127.0.0.1 instead;
everything else (server, peer protocol, transfers) is the real thing. Use
--no-loopback to go through the router. Nothing outside the generated test
folder is shared.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import secrets
import shutil
import sys
import tempfile
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from slsk_reborn.config import Config  # noqa: E402
from slsk_reborn.engine import Bus, SlskEngine  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)
    return ok


async def until(cond, timeout: float, every: float = 0.25):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        await asyncio.sleep(every)
    return None


def loopback(engine: SlskEngine, peers: set[str]) -> None:
    """Connect to the given users on 127.0.0.1 instead of the public IP."""
    net = engine.client.network
    get_addr, handle = net._get_peer_address, net._handle_connect_to_peer

    async def _get_peer_address(username):
        ip, port, obf = await get_addr(username)
        return ("127.0.0.1" if username in peers else ip), port, obf

    async def _handle_connect_to_peer(message):
        if message.username in peers:
            message = dataclasses.replace(message, ip="127.0.0.1")
        return await handle(message)

    net._get_peer_address, net._handle_connect_to_peer = _get_peer_address, _handle_connect_to_peer


def make_engine(root: Path, name: str, password: str, port: int, shared: list[str]):
    cfg = Config(path=root / name / "config.toml", username=name, password=password,
                 listen_port=port, upnp=False, download_dir=str(root / name / "downloads"),
                 shared_dirs=shared, share_downloads=False, welcomed=True)
    bus = Bus()
    events: dict[str, list] = {}
    for ev in ("search.hits", "pm", "status", "log", "shares.scanned"):
        bus.on(ev, lambda _ev=ev, **kw: events.setdefault(_ev, []).append(kw))
    return SlskEngine(cfg, bus), events


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port-a", type=int, default=62000)
    ap.add_argument("--port-b", type=int, default=62100)
    ap.add_argument("--keep", action="store_true", help="keep the temp folder")
    ap.add_argument("--no-loopback", action="store_true", help="connect via the public IP")
    ap.add_argument("-v", "--verbose", action="count", default=0, help="aioslsk warnings (-vv: debug)")
    a = ap.parse_args()
    logging.basicConfig(level=[logging.CRITICAL, logging.WARNING, logging.DEBUG][min(a.verbose, 2)])

    tag = secrets.token_hex(3)
    root = Path(tempfile.mkdtemp(prefix="slsk-live-"))
    token = f"rbzq{tag}"  # unique search word
    album = root / "share" / f"Reborn Test {token}"
    album.mkdir(parents=True)
    payloads = {}
    for i in range(1, 4):  # short valid WAVs (noise) so the share scanner reads their metadata
        f = album / f"0{i} - {token} track {i}.wav"
        with wave.open(str(f), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(os.urandom(44100 * 4 * i // 2))
        payloads[f.name] = f.read_bytes()

    # the server limits new registrations per IP, so reuse one throwaway pair
    acct_file = Path(tempfile.gettempdir()) / "slsk-reborn-livetest.json"
    try:
        ua, ub, pw = json.loads(acct_file.read_text())
    except (OSError, ValueError):
        ua, ub, pw = f"reborn_t{tag}a", f"reborn_t{tag}b", secrets.token_urlsafe(12)
        acct_file.write_text(json.dumps([ua, ub, pw]))
    A, ev_a = make_engine(root, ua, pw, a.port_a, [str(root / "share")])
    B, ev_b = make_engine(root, ub, pw, a.port_b, [])
    print(f"accounts {ua} / {ub}, ports {a.port_a} / {a.port_b}, temp {root}")

    try:
        # 1. login
        try:
            await asyncio.wait_for(A.start(), 30)
            await asyncio.wait_for(B.start(), 30)
            step("login both accounts", A.connected and B.connected)
            if not a.no_loopback:
                loopback(A, {ub})
                loopback(B, {ua})
        except Exception as e:
            step("login both accounts", False, f"{type(e).__name__}: {e}")
            return 1

        # 2. A scans and announces its share
        await until(lambda: A.share_stats()[1] >= 3, 30)
        step("A scanned its share", A.share_stats()[1] >= 3, f"{A.share_stats()} folders/files")
        await A.client.shares.report_shares()

        # 3. private message B -> A and back (server relayed, no peer link needed)
        await B.send_pm(ua, f"hello from {ub}")
        got = await until(lambda: ev_a.get("pm"), 20)
        step("PM B → A", bool(got), got[0]["text"] if got else "nothing arrived")
        await A.send_pm(ub, "hi back")
        got = await until(lambda: ev_b.get("pm"), 20)
        step("PM A → B", bool(got))

        # 4. user info (needs a peer connection)
        card = await B.user_info(ua)
        reachable = "did not answer" not in card.description
        step("user info from A (peer connection)", reachable,
             f"status={card.status} files={card.files} desc={card.description[:60]!r}")

        # 5. user search B -> A (server routes the query, results come over a peer link)
        req = await B.client.searches.search_user(ua, token)
        B._searches[req.ticket] = req
        hits = await until(lambda: [h for e in ev_b.get("search.hits", []) if e["ticket"] == req.ticket
                                    for h in e["hits"]], 30)
        step("user search finds A's files", bool(hits) and len(hits) >= 3, f"{len(hits or [])} hits")

        # 6. global search (distributed network; can be slow for a brand new account)
        t = await B.search(token)
        ghits = await until(lambda: [h for e in ev_b.get("search.hits", []) if e["ticket"] == t
                                     for h in e["hits"]], 45)
        step("global search finds A's files", bool(ghits), f"{len(ghits or [])} hits"
             + ("" if ghits else "; new accounts may need a while in the distributed network"))
        B.stop_search(t)

        # 7. browse
        try:
            folders = await asyncio.wait_for(B.browse(ua), 60)
            files = [f for d in folders for f in d.files]
            step("browse A", any(token in f.path for f in files), f"{len(folders)} folders, {len(files)} files")
        except Exception as e:
            folders = []
            step("browse A", False, f"{type(e).__name__}: {e}")

        # 8. single download, byte-for-byte
        remote = next((f.path for d in folders for f in d.files if f.path.endswith("track 1.wav")), None)
        if remote is None and hits:
            remote = next((h.path for h in hits if h.path.endswith("track 1.wav")), None)
        if remote:
            await B.download(ua, remote)
            x = await until(lambda: next((x for x in B.transfers() if x.path == remote
                                          and x.state in ("done", "failed", "aborted")), None), 90)
            ok = bool(x and x.state == "done")
            same = ok and Path(x.local_path).read_bytes() == payloads[Path(x.local_path).name]
            step("download one file", ok and same,
                 (f"{x.state} → {x.local_path}" if x else "timed out: "
                  + ", ".join(f"{y.state}:{y.reason}" for y in B.transfers())))
        else:
            step("download one file", False, "no remote path to download")

        # 9. whole folder
        if remote:
            folder = remote.rsplit("\\", 1)[0]
            try:
                n = await asyncio.wait_for(B.download_folder(ua, folder), 60)
                done = await until(lambda: sum(x.state == "done" for x in B.transfers()) >= 3, 90)
                step("download whole folder", bool(done), f"queued {n}, done "
                     f"{sum(x.state == 'done' for x in B.transfers())}")
            except Exception as e:
                step("download whole folder", False, f"{type(e).__name__}: {e}")

        # 10. A saw the uploads
        ups = [x for x in A.transfers() if x.upload]
        step("A lists the uploads", bool(ups), f"{len(ups)} uploads, states "
             f"{sorted({x.state for x in ups})}")
    finally:
        await A.stop()
        await B.stop()
        if not a.keep:
            shutil.rmtree(root, ignore_errors=True)

    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
