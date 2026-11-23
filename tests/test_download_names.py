import os

import pytest
from aioslsk.naming import chain_strategies

from slsk_reborn.engine import _naming_strategies


def place(remote: str, root) -> str:
    folder, name = chain_strategies(_naming_strategies(), remote, str(root))
    return os.path.join(folder, name)


@pytest.mark.parametrize("remote", [
    r"@@music\..\evil.sh",
    r"@@music\Album\..",
    r"@@music\..\..",
    r"@@music\ . \song.mp3",
    r"@@music\...\song.mp3",
    r"C:\..\song.mp3",
    "x/../song.mp3",
    r"@@music\Album\C:song.mp3",
    r"@@music\C:x\song.mp3",
    "",
])
def test_peer_paths_stay_in_the_download_folder(tmp_path, remote):
    root = tmp_path / "downloads"
    root.mkdir()
    path = os.path.abspath(place(remote, root))
    assert os.path.commonpath([path, str(root)]) == str(root)
    assert path != str(root)


def test_album_folder_is_kept(tmp_path):
    path = place(r"@@music\Artist\Album (2001)\01 Song.flac", tmp_path)
    assert path == os.path.join(str(tmp_path), "Album (2001)", "01 Song.flac")


def test_file_without_folder_goes_to_the_root(tmp_path):
    assert place(r"@@music\Song.mp3", tmp_path) == os.path.join(str(tmp_path), "Song.mp3")
