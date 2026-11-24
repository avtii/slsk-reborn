import pytest

from slsk_reborn.engine import FileEntry, MAX_FOLDER_BYTES, _listed_path, folder_batch


def test_directory_membership_and_duplicate_entries():
    assert _listed_path("Music/Album", "Music/Other/song") is None
    assert _listed_path("Music/Album", "song") == r"Music\Album\song"
    entry = FileEntry("song", 32, "mp3")
    assert folder_batch([entry, entry]) == [entry]
    with pytest.raises(ValueError):
        folder_batch([FileEntry("huge", MAX_FOLDER_BYTES + 1, "flac")])
