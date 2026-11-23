"""Tracklists: parse 'Artist - Title' lines, build searches, pick the best file.

Reads pasted lists in the usual shapes ("01. Artist - Title", "[12:34] Artist – Title",
"Artist - Title (Remix) 1:02:03") and mixgrab's tracklist.txt (a header block, a
blank line, then numbered lines).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .engine import Hit
from .util import LOSSLESS, basename

TS_RE = re.compile(r"[\[(]?\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\b[\])]?")
NUM_RE = re.compile(r"^\s*(?:#|no\.?\s*)?\d{1,3}\s*[.)\]:]\s*|^\s*0\d\s+(?=\S)", re.I)  # keeps "50 Cent"
SEP_RE = re.compile(r"\s+[-–—~|]\s+|\s*[–—]\s*")
LEAD_JUNK_RE = re.compile(r"^[^\w(\[]+", re.UNICODE)
TRAIL_JUNK_RE = re.compile(r"[\s\-–—|:,.]+$")
UNKNOWN = {"id", "unknown", "?", "??", "???", "tba", "unreleased"}
STOP = {"the", "a", "an", "and", "of", "feat", "ft", "featuring", "vs", "x", "original", "mix"}
VERSION_WORDS = {"remix", "rmx", "live", "edit", "acoustic", "instrumental", "dub", "bootleg", "rework",
                 "vip", "demo", "radio", "extended", "karaoke", "cover", "remaster", "remastered", "acapella"}
AUDIO_SCORE = {"flac": 4.0, "wav": 3.0, "aiff": 3.0, "aif": 3.0, "alac": 3.5, "ape": 2.5, "wv": 2.5,
               "mp3": 0.0, "m4a": 1.0, "aac": 1.0, "ogg": 1.0, "opus": 1.0}


@dataclass
class Track:
    index: int
    artist: str
    title: str
    start: Optional[int] = None  # seconds into a mix, when the list has timestamps

    @property
    def label(self) -> str:
        return f"{self.artist} - {self.title}"


def parse_line(line: str) -> Optional[tuple[str, str, Optional[int]]]:
    if not line or "http" in line.lower() or len(line) > 200:
        return None
    start = None
    if (m := TS_RE.search(line)):
        h, mi, s = m.groups()
        start = int(h or 0) * 3600 + int(mi) * 60 + int(s)
        line = line[:m.start()] + " " + line[m.end():]
    line = LEAD_JUNK_RE.sub("", line.strip())
    line = LEAD_JUNK_RE.sub("", NUM_RE.sub("", line))
    line = TRAIL_JUNK_RE.sub("", line).strip()
    parts = [p.strip() for p in SEP_RE.split(line, maxsplit=1)]
    if len(parts) != 2 or not all(parts):
        return None
    artist, title = parts
    if artist.isdigit():  # "01 - Artist - Title"
        sub = [p.strip() for p in SEP_RE.split(title, maxsplit=1)]
        if len(sub) != 2:
            return None
        artist, title = sub
    title = TRAIL_JUNK_RE.sub("", title).strip()
    if not artist or not title or len(artist) > 100:
        return None
    if artist.lower() in UNKNOWN and title.lower() in UNKNOWN:
        return None
    return artist, title, start


def parse_text(text: str) -> list[Track]:
    lines = text.splitlines()
    # mixgrab tracklist.txt: "<mix title>\n<url>\nsource: ...\n\n01. ..." -> skip the header block
    if len(lines) > 2 and lines[1].strip().lower().startswith("http") and "" in lines[:6]:
        lines = lines[lines.index("", 0, 6) + 1:]
    tracks: list[Track] = []
    for raw in lines:
        if (p := parse_line(raw)):
            tracks.append(Track(len(tracks) + 1, *p))
    return tracks


def load(path: str | Path) -> list[Track]:
    return parse_text(Path(path).expanduser().read_text(encoding="utf-8", errors="replace"))


# ----------------------------------------------------------------------------- matching

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("&", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", s)).strip()


def tokens(s: str) -> list[str]:
    return [t for t in norm(s).split() if t not in STOP]


def strip_parens(s: str) -> str:
    return re.sub(r"\s*[\[(][^\])]*[\])]", "", s).strip()


def queries_for(t: Track) -> list[str]:
    """Most specific first: artist + full title, artist + bare title, bare title."""
    artist = re.split(r"\s+(?:feat\.?|ft\.?|featuring|vs\.?|x)\s+", t.artist, flags=re.I)[0]
    title = re.sub(r"\((?:original mix|feat[^)]*|ft[^)]*)\)", "", t.title, flags=re.I)
    out: list[str] = []
    for cand in (f"{artist} {title}", f"{artist} {strip_parens(title)}", strip_parens(title)):
        q = " ".join(w for w in norm(cand).split() if len(w) > 1 or w.isdigit())
        if q and q not in out and len(q.split()) >= 2:
            out.append(q)
    return out


def score(h: Hit, t: Track, prefer_lossless: bool = True) -> Optional[float]:
    """None = not this track (or unusable); higher = better pick."""
    if h.locked or h.ext not in AUDIO_SCORE or h.size < 1_000_000:
        return None
    path_tokens = set(norm(h.path).split())
    stem = basename(h.path).rsplit(".", 1)[0]
    base_tokens = set(norm(stem).split())
    want_title = tokens(t.title) or norm(t.title).split()
    want_artist = tokens(t.artist) or norm(t.artist).split()
    if not want_title:
        return None
    tf = sum(w in path_tokens for w in want_title) / len(want_title)
    af = sum(w in path_tokens for w in want_artist) / len(want_artist) if want_artist else 1.0
    core = tokens(strip_parens(t.title)) or want_title
    if not all(w in path_tokens for w in core) or tf < 0.75 or af < 0.5:
        return None
    s = 10 * tf + 5 * af
    s -= 4 * len((base_tokens & VERSION_WORDS) - set(norm(t.title).split()))  # unasked-for remix/live...
    if h.ext in LOSSLESS:
        s += AUDIO_SCORE[h.ext] if prefer_lossless else 1.0
    elif h.ext == "mp3":
        br = h.bitrate or (int(h.size * 8 / h.duration / 1000) if h.duration else 0)
        s += 3.5 if br >= 310 else 2.5 if br >= 250 else 1.0 if br >= 190 else -2.0
    else:
        s += AUDIO_SCORE[h.ext]
    s += 3 if h.free_slot else 0
    s -= min(h.queue, 50) / 10
    s += min(h.speed / 1_000_000, 2)
    return s


def pick(hits: list[Hit], t: Track, prefer_lossless: bool = True) -> tuple[Optional[Hit], float]:
    best, best_s = None, float("-inf")
    for h in hits:
        if (s := score(h, t, prefer_lossless)) is not None and s > best_s:
            best, best_s = h, s
    return best, best_s


GOOD_SCORE = 18.0  # full title + artist match, good quality, free slot: stop searching early
