"""The web adapter must not widen file access or change Desktop cleanup policy."""
import asyncio
import hashlib
from pathlib import Path
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from oceanx.cache_cleanup import ACTIVE_CACHE_RETENTION, ARCHIVED_CACHE_RETENTION, TaskCacheCleaner
from oceanx.web.backend import WebTaskCacheCleaner
from oceanx.web.resources import PathNotAllowed, source_path
from oceanx.web.server import ProtocolBackend, WebSettings, create_app, prepare_frame
from tests.test_oceanx.test_cache_cleanup import _managed_agent, _Projector, _Store, _task


class StubBackend:
    """Only endpoint unit tests use this stub; native protocol has its own integration test."""
    def __init__(self, settings, grants):
        self.settings, self.grants = settings, grants
        self.browser_queues = {}
        self.messages = []
        self.closed = False

    async def start(self):
        pass

    async def close(self):
        self.closed = True

    def status(self):
        return {"running": True, "workspacePath": "web-project", "readyEvent": None}

    def disconnect(self, queue):
        self.browser_queues.pop(queue, None)

    async def send(self, frame, *, browser_queue):
        self.messages.append(prepare_frame(self.settings, frame))
        await browser_queue.put({"kind": "event", "payload": {
            "type": "request.completed", "request_id": frame["request_id"], "payload": {"result": {}}}})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    workspace = tmp_path / "project"; workspace.mkdir()
    frontend = tmp_path / "frontend"; frontend.mkdir()
    (frontend / "index.html").write_text('<div id="root"></div>')
    sources = tmp_path / "sources"; sources.mkdir()
    monkeypatch.setattr("oceanx.web.server.provider_status", lambda *_: {"configured": False})
    settings = WebSettings(workspace, frontend, (sources,))
    app = create_app(settings, backend_factory=StubBackend)
    return settings, app, sources


def test_paths_are_explicit_and_cannot_escape_even_via_symlink(setup, tmp_path):
    settings, _, sources = setup
    pdf = sources / "paper.pdf"; pdf.write_bytes(b"%PDF-1.7")
    assert source_path(str(pdf), (sources,)) == pdf
    outside = tmp_path / "secret.txt"; outside.write_text("private")
    link = sources / "linked"; link.symlink_to(tmp_path, target_is_directory=True)
    for bad in (str(outside), str(link / "secret.txt"), str(sources / "../secret.txt"), "paper.pdf"):
        with pytest.raises(PathNotAllowed):
            settings.resolve_source(bad)
    leaf = sources / "leaf.pdf"; leaf.symlink_to(pdf)
    with pytest.raises(PathNotAllowed):
        settings.resolve_source(str(leaf))
    settings.state.mkdir()
    secret = settings.state / "state.txt"; secret.write_text("private")
    with pytest.raises(PathNotAllowed):
        settings.resolve_source(str(secret))
    with pytest.raises(PathNotAllowed):
        settings.resolve_source(str(settings.workspace))


def test_reference_import_is_revalidated_and_project_cannot_switch(setup):
    settings, _, sources = setup
    data = sources / "small.csv"; data.write_text("x,y\n1,2\n")
    frame = {"type": "source.import", "payload": {"local_path": str(data)}}
    assert prepare_frame(settings, frame)["payload"]["local_path"] == str(data)
    data.unlink(); data.symlink_to(settings.frontend / "index.html")
    with pytest.raises(PathNotAllowed):
        prepare_frame(settings, frame)
    with pytest.raises(ValueError):
        prepare_frame(settings, {"type": "workspace.open", "payload": {"path": "/etc"}})
    for kind in ("system.shutdown", "portable.export.create", "arbitrary.command",
                 "research.library.get", "research.library.update", "research.library.mark"):
        with pytest.raises(ValueError):
            prepare_frame(settings, {"type": kind, "payload": {}})


def test_http_has_no_file_browser_and_requires_same_origin_for_import(setup):
    settings, app, sources = setup
    data = sources / "data.csv"; data.write_text("x\n1\n")
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        config = client.get("/api/config")
        assert config.json()["project"]["path"] == "web-project"
        assert str(settings.workspace) not in config.text
        assert str(sources) not in config.text
        assert client.get("/api/list?path=/").status_code == 404
        assert client.post("/api/source", json={"path": str(data)}).status_code == 403
        assert client.post("/api/source", json={"path": str(data)}, headers={"Origin": "https://evil.example"}).status_code == 403
        headers = {"Origin": "http://127.0.0.1:8765"}
        result = client.post("/api/source", json={"path": str(data)}, headers=headers)
        assert result.json() == {"kind": "file", "localPath": str(data)}
        assert client.get("/api/config", headers={"Host": "evil.example"}).status_code == 403


def test_websocket_disconnect_does_not_close_native_backend(setup):
    _, app, _ = setup
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(
            "ws://127.0.0.1:8765/api/protocol", headers={"Origin": "https://evil.example"}
        ):
            pass
        for _ in range(2):
            with client.websocket_connect("ws://127.0.0.1:8765/api/protocol", headers={"Origin": "http://127.0.0.1:8765"}) as ws:
                ws.send_json({"request_id": "r", "type": "task.list", "payload": {}})
                assert ws.receive_json()["payload"]["type"] == "request.completed"
            assert app.state.backend.closed is False
    assert app.state.backend.closed is True


def test_pdf_upload_is_private_unique_and_uses_native_source_import(setup):
    settings, app, _ = setup
    content = b"%PDF-1.7\nfixture paper\n%%EOF"
    headers = {"Origin": "http://127.0.0.1:8765", "Content-Type": "application/pdf",
               "X-Filename": quote("论文.pdf")}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        paths = []
        for _ in range(2):
            result = client.post("/api/papers", content=content, headers=headers)
            assert result.status_code == 200, result.text
            path = Path(result.json()["localPath"])
            assert result.json()["kind"] == "file"
            assert path.name == "论文.pdf" and path.read_bytes() == content
            assert path.stat().st_mode & 0o777 == 0o600
            assert path.parent.stat().st_mode & 0o777 == 0o700
            assert settings.resolve_source(str(path)) == path
            assert prepare_frame(settings, {"type": "source.import", "payload": {"local_path": str(path)}})["payload"]["local_path"] == str(path)
            paths.append(path)
        assert paths[0] != paths[1]


def test_pdf_upload_rejects_cross_origin_and_leaves_no_partial_files(setup, monkeypatch):
    from oceanx.web import uploads
    settings, app, _ = setup
    monkeypatch.setattr(uploads, "MAX_PDF_BYTES", 32)
    headers = {"Origin": "http://127.0.0.1:8765", "Content-Type": "application/pdf", "X-Filename": "paper.pdf"}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        for origin in (None, "https://evil.example"):
            denied = {k: v for k, v in headers.items() if k != "Origin"}
            if origin:
                denied["Origin"] = origin
            assert client.post("/api/papers", content=b"%PDF-", headers=denied).status_code == 403
        assert client.post("/api/papers", content=b"%PDF-", headers={**headers, "Host": "evil.example"}).status_code == 403
        for name in ("../paper.pdf", "..%2Fpaper.pdf", "%5Cpaper.pdf", "paper.txt", "paper%00.pdf", ""):
            assert client.post("/api/papers", content=b"%PDF-", headers={**headers, "X-Filename": name}).status_code == 400
        assert client.post("/api/papers", content=b"%PDF-", headers={**headers, "Content-Type": "text/html"}).status_code == 400
        for content in (b"", b"<html>fake.pdf</html>"):
            assert client.post("/api/papers", content=content, headers=headers).status_code == 400
        assert client.post("/api/papers", content=b"%PDF-" + b"x" * 33, headers=headers).status_code == 413
        # A chunked body has no Content-Length: enforce the actual received length too.
        assert client.post("/api/papers", content=iter([b"%PDF-", b"x" * 33]), headers=headers).status_code == 413
        assert not list((settings.workspace / "Uploaded papers").iterdir())


def test_pdf_upload_cannot_write_through_symlink(setup, tmp_path):
    settings, app, _ = setup
    outside = tmp_path / "outside"; outside.mkdir()
    (settings.workspace / "Uploaded papers").symlink_to(outside, target_is_directory=True)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.post("/api/papers", content=b"%PDF-1.7", headers={
            "Origin": "http://127.0.0.1:8765", "Content-Type": "application/pdf", "X-Filename": "paper.pdf"})
        assert response.status_code == 400
        assert not list(outside.iterdir())


@pytest.mark.asyncio
async def test_disconnected_pdf_upload_removes_partial_file(setup):
    from starlette.requests import ClientDisconnect, Request
    from oceanx.web.uploads import stage_pdf
    settings, _, _ = setup
    messages = iter([{"type": "http.request", "body": b"%PDF-", "more_body": True},
                     {"type": "http.disconnect"}])

    async def receive():
        return next(messages)

    request = Request({"type": "http", "headers": [(b"content-type", b"application/pdf"),
                       (b"x-filename", b"paper.pdf")]}, receive)
    with pytest.raises(ClientDisconnect):
        await stage_pdf(request, settings.workspace)
    assert not list((settings.workspace / "Uploaded papers").iterdir())


def grant_for(path):
    return {"resource_token": "res_test123", "resource_uri": path.as_uri(),
            "size_bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mime_type": "text/plain"}


def test_result_grants_hide_paths_and_detect_replacement(setup, tmp_path):
    settings, app, _ = setup
    report = settings.workspace / "report.txt"; report.write_text("published")
    grant = grant_for(report); app.state.grants.capture(grant)
    assert "resource_uri" not in grant
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/resources/res_test123").text == "published"
        download = client.get("/api/resources/res_test123?download=1")
        assert download.headers["content-disposition"].startswith("attachment;")
        report.write_text("different")
        assert client.get("/api/resources/res_test123").status_code == 404
        unknown = tmp_path / "other.txt"; unknown.write_text("secret")
        invalid = grant_for(unknown); app.state.grants.capture(invalid)
        assert "resource_token" not in invalid


@pytest.mark.parametrize("busy", ["request", "workflow", "execution", "recent"])
def test_short_web_cleanup_keeps_busy_and_recent_work(tmp_path, busy):
    from types import SimpleNamespace
    now = datetime.now(UTC)
    agent = _managed_agent(tmp_path); scratch = agent / "scratch/keep.nc"; scratch.write_bytes(b"keep")
    task = _task(now, days_old=.5 if busy == "recent" else 2,
                 active_request_id="r" if busy == "request" else None)
    cleaner = WebTaskCacheCleaner(store=_Store(task,
        workflows=(SimpleNamespace(state="working"),) if busy == "workflow" else (),
        running=(SimpleNamespace(task_id="task"),) if busy == "execution" else ()),
        task_workspaces=_Projector(tmp_path))
    assert cleaner.clean_task("task", now=now).file_count == 0
    assert scratch.exists()


def test_web_shorter_retention_does_not_change_desktop_or_published_files(tmp_path):
    from types import SimpleNamespace
    now = datetime.now(UTC); agent = _managed_agent(tmp_path)
    cache = agent / "scratch/delete.nc"; cache.write_bytes(b"delete")
    published = agent / "outputs/figure.nc"; published.write_bytes(b"keep")
    execution = SimpleNamespace(result={"work_root": str(agent),
        "discovered_results": [{"data_output": "figure.nc"}]})
    store = _Store(_task(now, days_old=2), executions=(execution,))
    desktop = TaskCacheCleaner(store=store, task_workspaces=_Projector(tmp_path))
    web = WebTaskCacheCleaner(store=store, task_workspaces=_Projector(tmp_path))
    assert desktop.clean_task("task", now=now).file_count == 0
    assert web.clean_task("task", now=now).file_count == 1
    assert published.exists() and not cache.exists()
    assert ACTIVE_CACHE_RETENTION == timedelta(days=7)
    assert ARCHIVED_CACHE_RETENTION == timedelta(days=1)


def test_archived_web_retention_and_invalid_configuration(tmp_path):
    now = datetime.now(UTC); agent = _managed_agent(tmp_path)
    cache = agent / "scratch/delete.nc"; cache.write_bytes(b"delete")
    store = _Store(_task(now, days_old=.3, status="archived"))
    cleaner = WebTaskCacheCleaner(store=store, task_workspaces=_Projector(tmp_path))
    assert cleaner.clean_task("task", now=now).file_count == 1
    with pytest.raises(ValueError):
        WebTaskCacheCleaner(store=store, task_workspaces=_Projector(tmp_path), active_hours=0)


def test_two_forwarded_browser_tabs_remain_connected_independently(setup):
    _, app, _ = setup
    origin = "http://127.0.0.1:8766"
    with (
        TestClient(app, base_url=origin) as client,
        client.websocket_connect("ws://127.0.0.1:8766/api/protocol", headers={"Origin": origin}) as first,
    ):
        with client.websocket_connect("ws://127.0.0.1:8766/api/protocol", headers={"Origin": origin}) as second:
            assert len(app.state.backend.browser_queues) == 2
            for name, tab in [("first", first), ("second", second)]:
                tab.send_json({"request_id": name, "type": "task.list", "payload": {}})
                assert tab.receive_json()["payload"]["request_id"] == name
        first.send_json({"request_id": "still_open", "type": "task.list", "payload": {}})
        assert first.receive_json()["payload"]["request_id"] == "still_open"
        assert app.state.backend.closed is False


def test_shared_native_events_are_routed_by_task_and_request_owner(setup):
    settings, app, _ = setup
    backend = ProtocolBackend(settings, app.state.grants)
    first, second = asyncio.Queue(), asyncio.Queue()
    backend.browser_queues = {first: "task_first", second: "task_second"}
    backend.deliver({"type": "transcript.item.appended", "task_id": "task_first", "payload": {"text": "first only"}})
    assert first.get_nowait()["payload"]["task_id"] == "task_first"
    assert second.empty()
    backend.request_queues["create"] = second
    backend.deliver({"type": "request.completed", "request_id": "create", "task_id": "task_new", "payload": {}})
    assert second.get_nowait()["payload"]["request_id"] == "create"
    assert first.empty() and not backend.request_queues
    backend.request_queues["running"] = first
    backend.disconnect(first)
    assert first not in backend.browser_queues and not backend.request_queues
    assert backend.closing is False


@pytest.mark.asyncio
async def test_upstream_retries_without_replaying_requests(setup, monkeypatch):
    from unittest.mock import AsyncMock
    from oceanx.web.server import BackendUnavailable

    settings, app, _ = setup
    backend = ProtocolBackend(settings, app.state.grants)
    backend.upstream = old = AsyncMock()
    backend._ready.set()
    queue = asyncio.Queue()
    backend.browser_queues[queue] = "task_running"
    backend.request_queues["already_submitted"] = queue
    queue.put_nowait({"kind": "event"})
    attempts = 0

    async def connect_again():
        nonlocal attempts
        attempts += 1
        assert not backend.status()["running"]
        with pytest.raises(BackendUnavailable):
            await backend.send({"type": "session.submit", "payload": {}})
        if attempts < 3:
            raise OSError("Temporarily unavailable")
        backend.upstream = AsyncMock()
        backend._ready.set()

    monkeypatch.setattr(backend, "_connect", connect_again)
    monkeypatch.setattr("oceanx.web.server.asyncio.sleep", AsyncMock())
    await backend._reconnect()
    assert attempts == 3
    old.close.assert_awaited_once()
    old.send.assert_not_called()
    backend.upstream.send.assert_not_called()
    assert not backend.request_queues
    assert queue.get_nowait() == {"kind": "resync"}
    assert queue.empty()


@pytest.mark.asyncio
async def test_upstream_retry_deadline_and_shutdown(setup, monkeypatch):
    from unittest.mock import AsyncMock

    settings, app, _ = setup
    backend = ProtocolBackend(settings, app.state.grants)
    monkeypatch.setattr("oceanx.web.server._UPSTREAM_RECONNECT_SECONDS", .02)
    backend._connect = AsyncMock(side_effect=OSError("Unavailable"))
    with pytest.raises(TimeoutError):
        await backend._reconnect()
    assert not backend.status()["running"]
    backend.reader = asyncio.create_task(backend._reconnect())
    await asyncio.sleep(0)
    await backend.close()
    assert backend.reader is None and backend.closing


@pytest.mark.asyncio
async def test_web_review_hooks_do_not_modify_the_desktop_router(tmp_path, monkeypatch):
    from oceanx.backend.host import OceanBackendHost
    from oceanx.backend.router import OceanRequestRouter
    from oceanx.web.backend import WebBackendHost, WebRequestRouter

    original_schedule = OceanRequestRouter._schedule_research_consolidation
    original_update = OceanRequestRouter._update_library
    desktop = OceanBackendHost(tmp_path / "desktop", write_frame=lambda _: None)
    web = WebBackendHost(tmp_path / "web", write_frame=lambda _: None)
    try:
        assert type(desktop.router) is OceanRequestRouter
        assert isinstance(web.router, WebRequestRouter)
        assert web.stdio.router is web.router
        assert web.router.store is web.store and web.router.event_bus is web.event_bus
        def unexpected(*args, **kwargs):
            raise AssertionError("Web task must not start meta-agent upkeep")
        monkeypatch.setattr(web.router, "_project_research", unexpected)
        assert web.router._schedule_research_consolidation(None) is None
        assert web.router._maintain_library("ws_desktop") is None
        with pytest.raises(ValueError, match="unavailable"):
            web.router._update_library("ws_desktop", review=True)
        assert OceanRequestRouter._schedule_research_consolidation is original_schedule
        assert OceanRequestRouter._update_library is original_update
    finally:
        await web.close()
        await desktop.close()


def test_large_csv_download_streams_original_and_checks_contents(setup, monkeypatch):
    settings, app, _ = setup
    table = settings.workspace / "tracks.csv"
    data = b"track,note\n" + b"001,observation\n" * 1800000
    table.write_bytes(data)
    grant = grant_for(table)
    grant.update(mime_type="text/csv", purpose="result_file")

    def no_whole_file_read(*_):
        raise AssertionError("Downloads must not load the whole file into memory")

    monkeypatch.setattr(Path, "read_bytes", no_whole_file_read)
    app.state.grants.capture(grant)
    assert "resource_token" in grant
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.get("/api/resources/res_test123")
        assert response.status_code == 200
        assert response.content == data
        assert response.headers["content-disposition"].startswith("attachment;")
        assert int(response.headers["content-length"]) == len(data)
        with table.open("r+b") as stream:
            stream.write(b"other")  # same length, different contents
        assert client.get("/api/resources/res_test123").status_code == 404
