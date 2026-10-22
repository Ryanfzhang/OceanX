"""Loopback browser adapter for one owner's existing OceanX research backend.

No new users, research scheduler, filesystem browser or model execution path.
The persistent upstream belongs to the server, so closing a tab does not cancel a run.
"""
from __future__ import annotations

import asyncio
import copy
import fcntl
import ipaddress
import json
import logging
import os
import secrets
import signal
import socket
import sys
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import anyio
import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect

from oceanx.backend.auth import REQUEST_CAPABILITIES
from oceanx.web.resources import PathNotAllowed, ResourceGrants, source_path

_LOG = logging.getLogger(__name__)
_WORKSPACE_ALIAS = "web-project"
_FRAME_LIMIT = 1024 * 1024


@dataclass(frozen=True)
class WebSettings:
    workspace: Path
    frontend: Path
    source_roots: tuple[Path, ...] = ()
    cache_hours: float = 24
    archived_cache_hours: float = 6
    sweep_seconds: float = 3600

    @property
    def state(self):
        return self.workspace / ".oceanx-web"

    def resolve_source(self, raw: str) -> Path:
        path = source_path(raw, (self.workspace, *self.source_roots))
        # A project cannot attach its own database, credentials, logs, or task tree.
        if path.is_relative_to(self.state) or self.state.is_relative_to(path):
            raise PathNotAllowed("path_not_allowed")
        return path


def local_request(scope) -> bool:
    """Only literal loopback Host and same-origin browser requests are accepted."""
    try:
        url = urlsplit("http://" + scope.headers.get("host", ""))
        host = url.hostname
        if host != "localhost" and (host is None or not ipaddress.ip_address(host).is_loopback):
            return False
    except ValueError:
        return False
    origin = scope.headers.get("origin")
    expected = f"{scope.url.scheme.replace('ws', 'http')}://{scope.headers.get('host')}"
    if origin is not None and origin != expected:
        return False
    return scope.headers.get("sec-fetch-site") != "cross-site"


def prepare_frame(settings: WebSettings, incoming: dict) -> dict:
    frame = copy.deepcopy(incoming)
    kind = frame.get("type")
    if (kind not in REQUEST_CAPABILITIES or kind in {"system.shutdown", "portable.export.create"}
            or (isinstance(kind, str) and kind.startswith("research.library."))):
        raise ValueError("request_not_available")
    payload = frame.get("payload")
    if not isinstance(payload, dict):
        raise TypeError("invalid_request")
    context = frame.get("context")
    if isinstance(context, dict) and context.get("workspace_id") not in {None, "ws_desktop"}:
        raise ValueError("project_not_available")
    if kind == "session.open" and payload.get("requested_workspace_id") != "ws_desktop":
        raise ValueError("project_not_available")
    if kind == "workspace.open":
        if payload.get("path") != _WORKSPACE_ALIAS:
            raise ValueError("project_not_available")
        payload["path"] = str(settings.workspace)
    if kind in {"source.import", "dataset.import"}:
        raw = payload.get("local_path")
        if not isinstance(raw, str) or payload.get("relative_path"):
            raise PathNotAllowed("absolute_source_path_required")
        payload["local_path"] = str(settings.resolve_source(raw))
        if kind == "dataset.import" and payload.get("materialization_level", "local_reference") != "local_reference":
            raise ValueError("reference_sources_only")
    if kind == "paper.import":
        raw = payload.get("relative_path")
        if not isinstance(raw, str) or Path(raw).is_absolute() or ".." in Path(raw).parts:
            raise PathNotAllowed("path_not_allowed")
        settings.resolve_source(str(settings.workspace / raw))
    return frame


class ProtocolBackend:
    """One real Agent Server and one long-lived native protocol connection."""
    server_module = "oceanx.web.backend"

    def __init__(self, settings: WebSettings, grants: ResourceGrants):
        self.settings, self.grants = settings, grants
        self.process = self.upstream = self.reader = None
        self.ready = None
        self._ready = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self.browser_queues: dict[asyncio.Queue, str | None] = {}
        self.request_queues: dict[str, asyncio.Queue] = {}
        self.lock = self.log = None
        self.failure = None
        self.closing = False

    async def start(self):
        self.settings.workspace.mkdir(parents=True, exist_ok=True)
        self.settings.state.mkdir(mode=0o700, exist_ok=True)
        self.lock = (self.settings.state / "web.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            self.lock = None
            raise RuntimeError("This project's web backend is already running") from exc
        token, desktop_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        environment = {**os.environ, "OCEAN_SERVER_TOKEN": token, "OCEAN_DESKTOP_TOKEN": desktop_token,
                       "OCEAN_WEB_CACHE_HOURS": str(self.settings.cache_hours),
                       "OCEAN_WEB_ARCHIVED_CACHE_HOURS": str(self.settings.archived_cache_hours),
                       "OCEAN_WEB_SWEEP_SECONDS": str(self.settings.sweep_seconds),
                       "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}
        self.log = (self.settings.state / "web-agent-server.log").open("ab")
        try:
            self.process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", self.server_module, "--state", str(self.settings.state),
                "--port", str(port), env=environment, stdin=asyncio.subprocess.DEVNULL,
                stdout=self.log, stderr=self.log, start_new_session=True,
            )
            headers = {"authorization": "Bearer " + token}
            async with asyncio.timeout(90), httpx.AsyncClient(timeout=2, trust_env=False) as client:
                while True:
                    if self.process.returncode is not None:
                        raise RuntimeError("Web backend failed to start; see the server-local log")
                    try:
                        if (await client.get(f"http://127.0.0.1:{port}/ok", headers=headers)).is_success:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(.2)
            self.upstream = await connect(
                f"ws://127.0.0.1:{port}/ocean/protocol",
                additional_headers={**headers, "x-ocean-desktop-token": desktop_token},
                max_size=32 * 1024 * 1024, proxy=None,
            )
            self.reader = asyncio.create_task(self._read())
            await self.upstream.send(json.dumps({"protocol_version": 2,
                "request_id": "req_web_handshake_" + uuid4().hex, "type": "system.handshake",
                "payload": {"client_kind": "desktop", "client_version": "oceanx-web",
                            "supported_protocol_versions": [2]}}))
            await asyncio.wait_for(self._ready.wait(), 45)
            if self.ready is None:
                raise RuntimeError("Web backend handshake failed; see the server-local log")
        except BaseException:
            await self.close()
            raise

    def public_frame(self, event):
        result = event.get("payload", {}).get("result")
        if event.get("type") == "request.completed" and isinstance(result, dict) and "resource_token" in result:
            self.grants.capture(result)
        # Keep the fixed project identity independent of its server filesystem path.
        def project_alias(value):
            if isinstance(value, dict):
                return {k: project_alias(v) for k, v in value.items() if k != "resource_uri"}
            if isinstance(value, list):
                return [project_alias(v) for v in value]
            return _WORKSPACE_ALIAS if value == str(self.settings.workspace) else value
        return {"kind": "event", "payload": project_alias(event)}

    async def _read(self):
        try:
            async for raw in self.upstream:
                event = json.loads(raw)
                if event.get("type") == "system.ready":
                    self.ready = event
                    self._ready.set()
                    continue
                if self.ready is None and event.get("type") in {"system.error", "request.failed"}:
                    self._ready.set()
                self.deliver(event)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - isolate and log failures at the transport boundary
            self.failure = "Backend connection ended; inspect the server log and restart the web service."
            _LOG.exception("Web upstream protocol failed")
        finally:
            if not self.closing:
                self.failure = "Backend connection ended; restart the web service."
            self._ready.set()
            for queue in tuple(self.browser_queues):
                with suppress(asyncio.QueueFull):
                    queue.put_nowait({"kind": "exit", "code": 1})

    def deliver(self, event):
        frame = self.public_frame(event)
        owner = self.request_queues.get(event.get("request_id"))
        task_id = event.get("task_id")
        for queue, selected_task in tuple(self.browser_queues.items()):
            # RPC replies always reach their requester; task progress reaches
            # only tabs displaying that task. The native backend stays shared.
            if task_id and task_id != selected_task and queue is not owner:
                continue
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                # Refresh only the slow tab, never cancel/replay its research.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({"kind": "resync"})
        if event.get("type") in {"request.completed", "request.failed", "request.cancelled"}:
            self.request_queues.pop(event.get("request_id"), None)

    def disconnect(self, queue):
        self.browser_queues.pop(queue, None)
        self.request_queues = {key: owner for key, owner in self.request_queues.items() if owner is not queue}

    async def send(self, incoming, *, browser_queue=None):
        if self.failure or self.upstream is None:
            raise RuntimeError("backend_unavailable")
        frame = prepare_frame(self.settings, incoming)
        async with self._send_lock:
            if browser_queue is not None:
                if isinstance(frame.get("request_id"), str):
                    self.request_queues[frame["request_id"]] = browser_queue
                task_id = (frame.get("context") or {}).get("task_id")
                if frame["type"] in {"task.open", "task.snapshot.get"}:
                    task_id = frame["payload"].get("task_id")
                if isinstance(task_id, str):
                    self.browser_queues[browser_queue] = task_id
            await self.upstream.send(json.dumps(frame, ensure_ascii=False))

    def status(self):
        return {"running": self.ready is not None and self.failure is None,
                "workspacePath": _WORKSPACE_ALIAS,
                "readyEvent": self.public_frame(copy.deepcopy(self.ready))["payload"] if self.ready else None}

    async def close(self):
        self.closing = True
        if self.upstream is not None:
            await self.upstream.close()
            self.upstream = None
        if self.reader is not None:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
            self.reader = None
        if self.process is not None and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 30)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                await self.process.wait()
        if self.log is not None:
            self.log.close()
        if self.lock is not None:
            self.lock.close()


def provider_status():
    from oceanx.model_config import load_model_profile

    roles = {}
    for role in ("coordinator", "expert"):
        p = load_model_profile(role, require_api_key=False)
        roles[role] = {"profile": p.name, "label": p.label, "provider": p.provider,
                       "model": p.model, "configured": bool(p.api_key), "imageInputs": bool(p.image_inputs)}
    return {**roles, "configured": all(p["configured"] for p in roles.values())}


def create_app(settings: WebSettings, *, backend_factory=ProtocolBackend) -> Starlette:
    grants = ResourceGrants(settings.workspace, settings.state)
    backend = backend_factory(settings, grants)

    @asynccontextmanager
    async def lifespan(app):
        await backend.start()
        try:
            yield
        finally:
            await backend.close()

    async def config(request: Request):
        if not local_request(request):
            return JSONResponse({"error": "origin_not_allowed"}, status_code=403)
        return JSONResponse({"project": {"path": _WORKSPACE_ALIAS, "name": settings.workspace.name},
                             "provider": await asyncio.to_thread(provider_status),
                             "backend": backend.status()}, headers={"Cache-Control": "no-store"})

    async def attach(request: Request):
        if not local_request(request) or request.headers.get("origin") is None:
            return JSONResponse({"error": "origin_not_allowed"}, status_code=403)
        try:
            data = bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > 8192:
                    return JSONResponse({"error": "invalid_request"}, status_code=413)
            payload = json.loads(data)
            raw = payload.get("path")
            if not isinstance(raw, str) or len(raw) > 4096:
                raise ValueError()
            path = await asyncio.to_thread(settings.resolve_source, raw)
        except PathNotAllowed as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (OSError, ValueError, AttributeError):
            return JSONResponse({"error": "source_unavailable"}, status_code=400)
        return JSONResponse({"kind": "folder" if path.is_dir() else "file", "localPath": str(path)})

    async def resource(request: Request):
        if not local_request(request):
            return Response(status_code=403)
        try:
            data, grant = await asyncio.to_thread(grants.read, request.path_params["token"])
        except (OSError, ValueError):
            return Response("Resource unavailable or changed", status_code=404)
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                   "Content-Security-Policy": "default-src 'none'; sandbox"}
        if request.query_params.get("download") == "1":
            from urllib.parse import quote
            headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(grant.path.name)
        return Response(data, media_type=grant.mime, headers=headers)

    async def browser(socket: WebSocket):
        if not local_request(socket) or socket.headers.get("origin") is None:
            await socket.close(code=1008)
            return
        await socket.accept()
        queue = asyncio.Queue(maxsize=256)
        backend.browser_queues[queue] = None

        async def transmit():
            while True:
                frame = await queue.get()
                if frame.get("kind") == "resync":
                    await socket.close(code=1013)
                    return
                await socket.send_json(frame)

        async def receive():
            while True:
                raw = await socket.receive_text()
                if len(raw.encode()) > _FRAME_LIMIT:
                    await socket.close(code=1009)
                    return
                frame = None
                try:
                    frame = json.loads(raw)
                    if not isinstance(frame, dict):
                        raise TypeError("invalid_request")
                    await backend.send(frame, browser_queue=queue)
                except (TypeError, ValueError, OSError, RuntimeError) as exc:
                    # No internal path/traceback is sent back as an error detail.
                    _LOG.info("Rejected web frame: %s", type(exc).__name__)
                    await queue.put({"kind": "event", "payload": {"type": "request.failed",
                        "request_id": frame.get("request_id") if isinstance(frame, dict) else None,
                        "payload": {"error": {"code": "permission_denied", "message": "Request unavailable or source path not allowed."}}}})
        tasks = [asyncio.create_task(transmit()), asyncio.create_task(receive())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
            pass
        finally:
            backend.disconnect(queue)
            for task in tasks:
                task.cancel()
            with anyio.CancelScope(shield=True):
                await asyncio.gather(*tasks, return_exceptions=True)
            # Deliberately leave the real upstream and native research run alive.

    async def frontend(request: Request):
        if not local_request(request):
            return Response(status_code=403)
        relative = request.path_params.get("path", "") or "index.html"
        root = settings.frontend.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or any(p.startswith(".") for p in Path(relative).parts) or not path.is_file():
            return Response(status_code=404)
        return FileResponse(path, headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

    app = Starlette(lifespan=lifespan, routes=[
        Route("/api/config", config), Route("/api/source", attach, methods=["POST"]),
        Route("/api/resources/{token}", resource), WebSocketRoute("/api/protocol", browser),
        Route("/{path:path}", frontend),
    ])
    app.state.backend = backend
    app.state.grants = grants
    return app
