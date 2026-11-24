"""Selected-size support for versions of aioslsk predating the expected_size argument."""
from inspect import signature

from aioslsk.client import SoulSeekClient
from aioslsk.protocol.messages import PeerTransferReply
from aioslsk.transfer.manager import TransferManager
from aioslsk.transfer.model import Transfer, TransferDirection


class SizeCheckedTransfers(TransferManager):
    async def download(self, username, filename, paused=False, *, expected_size=None):
        if expected_size is None:
            return await super().download(username, filename, paused)
        if expected_size < 0:
            raise ValueError("expected size must be non-negative")

        candidate = Transfer(username, filename, TransferDirection.DOWNLOAD)
        # The transfer cache persists attributes, including this one, across restarts.
        candidate.expected_size = expected_size
        transfer = await self.add(candidate)
        if transfer is not candidate:
            previous = getattr(transfer, "expected_size", None)
            if previous is not None and previous != expected_size:
                raise ValueError("existing download has a different selected size")
            if transfer.is_processing() and transfer.filesize != expected_size:
                raise ValueError("active download has a different offered size")
            transfer.expected_size = expected_size
        if paused:
            await transfer.state.pause()
        else:
            await transfer.state.queue()
        return transfer

    async def _initialize_download(self, transfer, peer_connection, request):
        expected = getattr(transfer, "expected_size", None)
        if expected is None or request.filesize == expected:
            return await super()._initialize_download(transfer, peer_connection, request)

        reason = "File size changed."
        await transfer.state.initialize()
        await transfer.state.fail(reason=reason)
        await peer_connection.send_message(PeerTransferReply.Request(
            ticket=request.ticket, allowed=False, reason=reason))


class DownloadClient(SoulSeekClient):
    def create_transfer_manager(self, cache):
        if "expected_size" in signature(TransferManager.download).parameters:
            return super().create_transfer_manager(cache)
        return SizeCheckedTransfers(self.settings, self.events, self.users, self.shares,
                                    self.network, cache=cache)
