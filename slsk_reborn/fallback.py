"""Find the same file at another user when a download fails or sits in a long queue.

Pure functions; the app runs the search and calls pick_alternative() on what
comes back.
"""
from __future__ import annotations

import re

from .engine import Hit, Xfer
from .util import basename, ext_of

_NOISE = re.compile(r"^\s*(?:\d{1,2}[-.])?\d{1,3}\s*[-._)\]]*\s*")  # "01 - ", "1-07. ", "03_"
_SEP = re.compile(r"[\s_\-.,()\[\]{}!?'\"&+]+")
SIZE_SLACK = 0.005  # edited tags shift a few KB; same audio within 0.5 %
RIP_SLACK = 0.15    # same name + format, size within 15 %: very likely the same track


def stem(path: str) -> str:
    name = basename(path)
    return name.rsplit(".", 1)[0] if "." in name else name


def norm_name(path: str) -> str:
    """Filename without track number, extension, case or punctuation."""
    return " ".join(w for w in _SEP.split(_NOISE.sub("", stem(path)).lower()) if w)


def alt_query(path: str, max_words: int = 6) -> str:
    """A search for the same track: filename words, longest first, no track number."""
    words = [w for w in norm_name(path).split() if len(w) > 1 and not w.isdigit()]
    if len(words) > max_words:
        keep = set(sorted(words, key=len, reverse=True)[:max_words])
        words = [w for w in words if w in keep][:max_words]
    return " ".join(words)


def match_score(x: Xfer, h: Hit, *, auto: bool = False) -> float | None:
    """None when h is not the same track as x, otherwise higher = better source."""
    if h.user == x.user or h.locked or h.ext != ext_of(x.path) or h.ext != ext_of(h.path):
        return None
    same_name = norm_name(h.path) == norm_name(x.path)
    if auto and (not same_name or not x.size or not h.size):
        return None
    same_size = bool(x.size) and h.size == x.size
    diff = abs(h.size - x.size) / x.size if x.size else 0.0
    if same_size:
        score = 100.0
    elif same_name and diff <= SIZE_SLACK:
        score = 80.0                      # same file, tags edited
    elif same_name and diff <= RIP_SLACK:
        score = 40.0                      # same track and format, another rip
    else:
        return None
    score += 20 if same_name else 0
    score += 30 if h.free_slot else -min(h.queue, 50) / 2
    score += min(h.speed / 1e6, 10)
    return score


def pick_alternative(x: Xfer, hits: list[Hit], *, auto: bool = False) -> Hit | None:
    scored = [(s, h) for h in hits if (s := match_score(x, h, auto=auto)) is not None]
    return max(scored, key=lambda sh: sh[0])[1] if scored else None


def good_enough(x: Xfer, hits: list[Hit], *, auto: bool = False) -> bool:
    """Stop searching early: an exact-size copy with a free slot is as good as it gets."""
    return any(h.free_slot and h.size == x.size and match_score(x, h, auto=auto) is not None for h in hits)
