import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aioslsk.transfer.manager import TransferManager

from slsk_reborn.config import Config
from slsk_reborn.engine import Bus, SlskEngine


@pytest.mark.parametrize("size", [None, 0, 8128])
async def test_selected_size_reaches_transfer_manager(size):
    signature = inspect.signature(TransferManager.download)
    download = AsyncMock()
    engine = SlskEngine(Config(), Bus())
    engine.client = SimpleNamespace(transfers=SimpleNamespace(download=download))
    await engine.download("peer", "album/song", size)
    args, kwargs = download.await_args
    bound = signature.bind(None, *args, **kwargs)
    assert bound.arguments["expected_size"] == size
