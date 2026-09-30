"""Ocean desktop protocol lives inside the Agent Server, alongside the research graphs."""
from __future__ import annotations

import hmac
import ipaddress
import os
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocketDisconnect

from oceanx.research.services import host


@asynccontextmanager
async def lifespan(app):
    from oceanx.backend.host import OceanBackendHost
    from oceanx.research import services
    services._active_host = OceanBackendHost(Path(os.environ["OCEAN_STATE_DIRECTORY"]), write_frame=lambda _: None)
    services._active_host.start_cache_maintenance()
    try:
        yield
    finally:
        await services._active_host.close()
        services._active_host = None


async def protocol(socket):
    from oceanx.backend.events import BackendClient
    # An opaque local-launch token protects both desktop protocol and graph API.
    # Graph/API authentication alone never grants local file attachment rights.
    # The native stdio launcher holds a separate ephemeral capability, which is
    # not sent to models or subagents. Reject browser and non-loopback clients.
    desktop_secret = os.environ.get("OCEAN_DESKTOP_TOKEN", "")
    try:
        local_peer = socket.client is not None and ipaddress.ip_address(socket.client.host).is_loopback
    except ValueError:
        local_peer = False
    if (not local_peer or socket.headers.get("origin") is not None or not desktop_secret
            or not hmac.compare_digest(socket.headers.get("x-ocean-desktop-token", ""), desktop_secret)
            or not hmac.compare_digest(socket.headers.get("authorization", ""), "Bearer " + os.environ["OCEAN_SERVER_TOKEN"])):
        await socket.close(code=1008)
        return
    await socket.accept()
    async def send(event):
        await socket.send_text(event.model_dump_json())
    client = BackendClient(transport="websocket", expected_client_kind=os.environ.get("OCEAN_CLIENT_KIND", "desktop"),
                           sender=send, verified_local_desktop=True)
    await host().event_bus.register(client)
    try:
        while True:
            await host().router.handle_payload(client, await socket.receive_json())
    except WebSocketDisconnect:
        pass
    finally:
        await host().event_bus.unregister(client)


app = Starlette(lifespan=lifespan, routes=[WebSocketRoute("/ocean/protocol", protocol)])
