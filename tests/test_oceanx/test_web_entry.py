"""The web adapter must not widen file access or change Desktop cleanup policy."""
import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

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
