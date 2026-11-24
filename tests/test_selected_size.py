import pickle
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aioslsk.transfer.model import TransferDirection
from aioslsk.transfer.state import TransferState

from slsk_reborn.config import Config
from slsk_reborn.engine import Bus, SlskEngine
from slsk_reborn.transfer_sizes import DownloadClient


@pytest.mark.parametrize("size", [None, 0, 8128])
async def test_selected_size_survives_cache(size):
    engine = SlskEngine(Config(), Bus())
    engine.client = DownloadClient(engine._settings())
    await engine.download("peer", "album/song", size)
    transfer = engine.client.transfers.find_transfer("peer", "album/song", TransferDirection.DOWNLOAD)
    restored = pickle.loads(pickle.dumps(transfer))
    assert getattr(restored, "expected_size", None) == size


async def test_changed_offer_is_refused_before_data_connection():
    engine = SlskEngine(Config(), Bus())
    engine.client = DownloadClient(engine._settings())
    await engine.download("peer", "album/song", 7)
    manager = engine.client.transfers
    transfer = manager.find_transfer("peer", "album/song", TransferDirection.DOWNLOAD)
    peer = AsyncMock()
    await manager._initialize_download(transfer, peer, SimpleNamespace(filesize=8, ticket=1))
    assert not peer.send_message.await_args.args[0].allowed
    assert transfer.state.VALUE == TransferState.FAILED
    assert transfer.local_path is None


async def test_matching_offer_uses_normal_handshake():
    from aioslsk.exceptions import ConnectionWriteError

    engine = SlskEngine(Config(), Bus())
    engine.client = DownloadClient(engine._settings())
    await engine.download("peer", "album/song", 7)
    manager = engine.client.transfers
    transfer = manager.find_transfer("peer", "album/song", TransferDirection.DOWNLOAD)
    peer = AsyncMock()
    # Stop after the ordinary acceptance message, without opening a network socket.
    peer.send_message.side_effect = ConnectionWriteError("offline")
    await manager._initialize_download(transfer, peer, SimpleNamespace(filesize=7, ticket=1))
    assert peer.send_message.await_args.args[0].allowed
    assert transfer.filesize == 7
