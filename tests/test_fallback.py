from slsk_reborn.engine import Hit, Xfer
from slsk_reborn.fallback import alt_query, good_enough, match_score, norm_name, pick_alternative

P = "@@x/Music/Aphex Twin/SAW/01 - Aphex Twin - Xtal (Remastered).flac"


def x(size=30_000_000, user="ann", path=P):
    return Xfer((user, path, 0), False, user, path, "failed", size)


def h(user, size=30_000_000, path=P, ext="flac", free=True, queue=0, speed=1_000_000):
    return Hit(user, path, size, ext, None, 300, 44100, free, queue, speed)


def test_names_and_query():
    assert norm_name(P) == "aphex twin xtal remastered"
    assert norm_name("1-07. Track_name.mp3") == "track name"
    assert alt_query(P) == "aphex twin xtal remastered"
    assert len(alt_query("01 " + " ".join(f"word{i}" for i in range(12)) + ".mp3").split()) == 6


def test_match_rules():
    other = "@@y/rips/Xtal.flac"
    assert match_score(x(), h("ann")) is None                       # same user
    assert match_score(x(), h("bob", ext="mp3")) is None            # other format
    assert match_score(x(), h("bob", path=other, size=29_000_000)) is None  # other name, other size
    assert match_score(x(), h("bob", path=other)) is not None       # exact size, renamed
    assert match_score(x(), h("bob", size=31_000_000)) is not None  # same name, another rip
    assert match_score(x(), h("bob", size=40_000_000)) is None      # same name, too different
    assert match_score(x(size=0), h("bob", size=1)) is not None     # unknown size: name decides


def test_pick_prefers_exact_size_and_free_slot():
    hits = [h("rip", size=31_000_000), h("busy", free=False, queue=40), h("free"), h("ann")]
    assert pick_alternative(x(), hits).user == "free"
    assert pick_alternative(x(), [h("ann")]) is None
    assert good_enough(x(), hits) and not good_enough(x(), hits[:2])
