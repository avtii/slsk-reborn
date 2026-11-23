import logging

import pytest
from aioslsk.protocol.messages import Login, NewPassword

from slsk_reborn.cli import _omit_authentication


@pytest.mark.parametrize("message", [
    Login.Request("tester", "test-password", 1, "test-hash", 1),
    Login.Response(True),
    NewPassword.Request("test-password"),
])
def test_authentication_records_omitted(message):
    record = logging.makeLogRecord({"msg": "connection warning %s", "args": (message,)})
    assert not _omit_authentication(record)
    record.args = ()
    record.message_type = type(message)
    assert not _omit_authentication(record)


def test_ordinary_diagnostics_retained():
    record = logging.makeLogRecord({"msg": "connected to %s", "args": ("server",)})
    assert _omit_authentication(record)
