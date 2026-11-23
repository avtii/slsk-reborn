import os
import stat
from pathlib import Path

import pytest

from slsk_reborn.config import Config


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_config_is_private_before_replacement(tmp_path, monkeypatch):
    destination = tmp_path / "config.toml"
    replace = os.replace

    def check_permissions(source, target):
        assert stat.S_IMODE(Path(source).stat().st_mode) == 0o600
        replace(source, target)

    monkeypatch.setattr(os, "replace", check_permissions)
    Config(path=destination, username="tester").save()
    assert Config.load(destination).username == "tester"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_failed_replace_preserves_previous_config(tmp_path, monkeypatch):
    destination = tmp_path / "custom.toml"
    Config(path=destination, username="previous").save()

    def fail_replace(source, target):
        raise PermissionError("replacement unavailable")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(PermissionError):
        Config(path=destination, username="updated").save()
    assert list(tmp_path.iterdir()) == [destination]
    assert Config.load(destination).username == "previous"
