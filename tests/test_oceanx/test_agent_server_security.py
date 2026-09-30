"""An API bearer does not imply trusted desktop filesystem attachment rights."""
from types import SimpleNamespace

import pytest

from oceanx.research.app import protocol


@pytest.mark.asyncio
@pytest.mark.parametrize("peer,desktop,origin", [
    ("127.0.0.1", None, None),
    ("127.0.0.1", "wrong", None),
    ("192.0.2.1", "desktop-secret", None),
    ("127.0.0.1", "desktop-secret", "https://example.org"),
])
async def test_api_token_alone_cannot_attach_local_files(monkeypatch, peer, desktop, origin):
    monkeypatch.setenv("OCEAN_SERVER_TOKEN", "api-secret")
    monkeypatch.setenv("OCEAN_DESKTOP_TOKEN", "desktop-secret")

    class Socket:
        client = SimpleNamespace(host=peer)
        closed = None

        def __init__(self):
            self.headers = {"authorization": "Bearer api-secret"}

        async def close(self, code):
            self.closed = code

        async def accept(self):
            pytest.fail("Untrusted client reached the desktop protocol")

    socket = Socket()
    if desktop:
        socket.headers["x-ocean-desktop-token"] = desktop
    if origin:
        socket.headers["origin"] = origin
    await protocol(socket)
    assert socket.closed == 1008
