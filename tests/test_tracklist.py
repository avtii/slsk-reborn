"""Tracklist parsing and matching (no network)."""
from slsk_reborn.engine import Hit
from slsk_reborn.tracklist import parse_line, parse_text, pick, queries_for, score, Track

MIXGRAB = """Boiler Room: Some DJ
https://www.youtube.com/watch?v=abc
source: description

01. Burial - Archangel
02. [12:34] Daft Punk – Digital Love
03. ID - ID
04. Massive Attack - Teardrop (Mad Professor Remix)
"""


def test_parse_shapes():
    assert parse_line("01. Burial - Archangel") == ("Burial", "Archangel", None)
    assert parse_line("[1:02:03] Aphex Twin – Xtal") == ("Aphex Twin", "Xtal", 3723)
    assert parse_line("50 Cent - In Da Club")[0] == "50 Cent"
    assert parse_line("07 - Boards of Canada - Roygbiv") == ("Boards of Canada", "Roygbiv", None)
    assert parse_line("ID - ID") is None
    assert parse_line("https://example.com - x") is None
    assert parse_line("just some words") is None


def test_parse_mixgrab_file_skips_header():
    tracks = parse_text(MIXGRAB)
    assert [t.label for t in tracks] == ["Burial - Archangel", "Daft Punk - Digital Love",
                                         "Massive Attack - Teardrop (Mad Professor Remix)"]
    assert [t.index for t in tracks] == [1, 2, 3]
    assert tracks[1].start == 754


def test_queries_most_specific_first():
    t = Track(1, "Massive Attack feat. Liz Fraser", "Teardrop (Mad Professor Remix)")
    assert queries_for(t) == ["massive attack teardrop mad professor remix", "massive attack teardrop"]


def _h(path, ext="mp3", br=320, free=True, queue=0, user="u", size=9_000_000):
    return Hit(user, path, size, ext, br, 240, 44100, free, queue, 1_000_000)


def test_score_rejects_wrong_and_unasked_versions():
    t = Track(1, "Burial", "Archangel")
    assert score(_h(r"Music\Burial\Untrue\02 - Archangel.mp3"), t) is not None
    assert score(_h(r"Music\Burial\Untrue\02 - Near Dark.mp3"), t) is None          # other track
    assert score(_h(r"Music\Other\02 - Archangel.mp3"), t) is None                  # other artist
    assert score(_h(r"Music\Burial\Archangel.mp3", size=500_000), t) is None        # too small
    assert score(_h(r"Music\Burial\Archangel.txt", ext="txt"), t) is None
    plain = score(_h(r"Music\Burial\02 - Archangel.mp3"), t)
    remix = score(_h(r"Music\Burial\02 - Archangel (Remix).mp3"), t)
    assert remix < plain


def test_pick_prefers_lossless_and_free_slots():
    t = Track(1, "Burial", "Archangel")
    mp3 = _h(r"Burial\Untrue\02 - Archangel.mp3", user="a")
    flac = _h(r"Burial\Untrue\02 - Archangel.flac", ext="flac", br=1000, user="b")
    busy_flac = _h(r"Burial\Untrue\02 - Archangel.flac", ext="flac", free=False, queue=50, user="c")
    assert pick([mp3, flac, busy_flac], t)[0] is flac
    assert pick([mp3, flac], t, prefer_lossless=False)[0] is not None
    assert pick([_h(r"x\Near Dark.mp3")], t) == (None, float("-inf"))


def test_auto_pick_requires_the_filename_to_match_the_audio_format():
    t = Track(1, "Burial", "Archangel")
    for path in ("Music/Burial/Archangel.txt", "Music/Burial/Archangel", "Music/Burial/Archangel.wav"):
        assert pick([_h(path, ext="mp3")], t)[0] is None
    actual = _h("Music/Burial/Archangel.MP3")
    assert pick([actual], t)[0] is actual


async def test_failed_search_can_be_retried(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from slsk_reborn.app import SlskApp
    from slsk_reborn.config import Config
    from slsk_reborn.panes.search import SearchPane
    from slsk_reborn.panes.tracklist import TracklistView

    app = SlskApp(Config(path=tmp_path / "config.toml"), demo=True)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        search = AsyncMock(side_effect=[ConnectionError("offline"), 123])
        monkeypatch.setattr(app.engine, "search", search)
        monkeypatch.setattr("slsk_reborn.panes.tracklist.SEARCH_WAIT", 0)
        await app.query_one(SearchPane).open_tracklist([Track(1, "Example", "Song")], True, "list").wait()
        view = app.query_one(TracklistView)
        row = view.rows[0]
        await row.task
        assert (row.state, row.note) == ("failed", "ConnectionError")
        search.side_effect = None
        search.return_value = 123
        view.action_retry()
        await row.task
        assert row.state == "not found"
        assert search.await_count >= 2
