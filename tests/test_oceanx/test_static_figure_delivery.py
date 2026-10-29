"""Saved image files are delivered figures; a static-delivery run also describes no plotting interface."""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage

from oceanx.backend.host import OceanBackendHost
from oceanx.cache_cleanup import TaskCacheCleaner
from oceanx.figure_delivery import (
    FIGURE_DELIVERY_ENV,
    figure_delivery,
    static_figure_files,
    static_figures,
)
from oceanx.native_skills import prepare_skill_library
from oceanx.research import graphs, services
from oceanx.research.services import (
    ResearchServices,
    expert_agent_key,
    format_expert_receipt,
    parse_expert_receipt,
)
from oceanx.task_results import TaskResultStore
from oceanx.tools import OceanExpertRunCodeTool, OceanToolServices
from tests.test_oceanx.test_cache_cleanup import _managed_agent, _task
from tests.test_oceanx.test_cache_cleanup import _Projector as _CleanupProjector
from tests.test_oceanx.test_cache_cleanup import _Store as _CleanupStore
from tests.test_oceanx.test_dataset_import_router import _open_workspace

PNG = b"\x89PNG\r\n\x1a\nfixture"
# What a static run must never show a model: the plotting interface and how it is published.
INTERFACE_NAMES = (
    "ScientificFigure", "Figure API", "result-api", "Published results", "bracket", "Workbench",
    ".preview.png",
)


class _Store:
    @staticmethod
    def get_research_task(_task_id):
        return SimpleNamespace(workspace_id="workspace")

    @staticmethod
    def list_task_code_executions(*, workspace_id, task_id):
        return ()


class _Projector:
    def __init__(self, root: Path):
        self.root = root
        self.store = _Store()

    def ensure_task_root(self, _task_id):
        return self.root

    def expert_session_root(self, _task_id, agent_key):
        path = self.root / "agents" / agent_key
        path.mkdir(parents=True, exist_ok=True)
        return path


def _config(mode="research"):
    return {"configurable": {
        "workspace_id": "ws", "task_id": "task", "request_id": "request",
        "thread_id": "coordinator", "ls_agent_type": "subagent",
        "request_options": {"workflow_mode": mode},
    }}


def test_the_delivery_mode_is_interactive_unless_the_environment_says_static(monkeypatch):
    monkeypatch.delenv(FIGURE_DELIVERY_ENV, raising=False)
    assert figure_delivery() == "interactive" and not static_figures()
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, " Static ")
    assert figure_delivery() == "static" and static_figures()
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, "")
    assert figure_delivery() == "interactive"
    # A misspelling must not quietly fall back to describing the plotting interface.
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, "statik")
    with pytest.raises(ValueError, match="interactive, static"):
        figure_delivery()


def test_delivered_images_are_images_of_any_depth_without_drafts_or_links(tmp_path):
    agent = tmp_path / "agents" / "ocean-process-a"
    outputs = agent / "outputs"
    (outputs / "maps").mkdir(parents=True)
    (agent / "scratch").mkdir()
    for name in ("map.png", "photo.jpg", "photo2.jpeg", "chart.svg", "paper.pdf", "maps/mld.PNG",
                 "_draft.png", ".hidden.png", "maps/_draft.png", "table.csv", "data.nc",
                 "front.preview.png"):  # an interactive figure's own preview
        (outputs / name).write_bytes(PNG)
    (agent / "scratch" / "explore.png").write_bytes(PNG)  # exploratory plots live in scratch
    (outputs / "link.png").symlink_to(outputs / "map.png")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "outside.png").write_bytes(PNG)
    (outputs / "linked-folder").symlink_to(elsewhere)  # never followed
    (tmp_path / "agents" / "ocean-process-b").mkdir()
    (tmp_path / "agents" / "ocean-process-b" / "outputs").symlink_to(elsewhere)  # never followed

    found = [(key, path.relative_to(outputs).as_posix()) for key, path in static_figure_files(tmp_path)]
    assert found == [
        ("ocean-process-a", name)
        for name in ("chart.svg", "map.png", "paper.pdf", "photo.jpg", "photo2.jpeg", "maps/mld.PNG")
    ]
    assert list(static_figure_files(tmp_path / "no-such-task")) == []


@pytest.mark.parametrize("delivery", ["interactive", "static"])
def test_images_are_listed_as_file_results_in_either_delivery_mode(monkeypatch, tmp_path, delivery):
    key = "ocean-process-a"
    outputs = tmp_path / "agents" / key / "outputs"
    (outputs / "maps").mkdir(parents=True)
    figure = outputs / "maps" / "mld_anomaly.png"
    figure.write_bytes(PNG)
    (outputs / "_probe.png").write_bytes(PNG)
    (outputs / "data.nc").write_bytes(b"not a figure")
    (outputs / "data.preview.png").write_bytes(PNG)  # owned by an interactive figure, never its own result
    store = TaskResultStore(task_workspaces=_Projector(tmp_path))

    monkeypatch.setenv(FIGURE_DELIVERY_ENV, delivery)
    (record,) = store.list(task_id="task")
    relative = f"agents/{key}/outputs/maps/mld_anomaly.png"
    assert record.kind == "file" and record.title == "mld anomaly" and record.agent_run_id == key
    assert re.fullmatch(r"figure_[0-9a-f]{32}", record.ref.result_id)
    assert record.content == {
        "agent_key": key, "result_key": f"{key}/maps/mld_anomaly.png", "output_path": relative,
        "render_status": "static", "figure_file": "mld_anomaly.png", "preview_file": "mld_anomaly.png",
        "workspace_files": {"mld_anomaly.png": relative},
    }
    (declared,) = record.files
    assert (declared.path, declared.mime_type, declared.size) == ("mld_anomaly.png", "image/png", len(PNG))
    import hashlib
    assert declared.sha256 == hashlib.sha256(PNG).hexdigest()
    # The same record is found again, and its file opens through the store.
    assert store.list(task_id="task") == (record,) and store.get(record.ref) == record
    assert store.file_path(ref=record.ref, relative_path="mld_anomaly.png") == figure.resolve()
    assert record.as_payload()["result_ref"]["task_id"] == "task"
    # A figure saved again under the same name is the same result with the new content.
    figure.write_bytes(PNG + b"revised")
    (revised,) = store.list(task_id="task")
    assert revised.ref == record.ref and revised.files[0].sha256 != declared.sha256


def _vector_pdf(path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(figsize=(7, 3.5))
    axes.plot([0, 1, 2], [1, 3, 2])
    axes.set_xlabel("Day")
    figure.savefig(path, bbox_inches="tight")
    plt.close(figure)


def test_a_pdf_figure_is_shown_through_a_drawing_of_its_first_page(tmp_path):
    """The desktop and the browser show images: a vector PDF is shown as a PNG of its first page,
    and Download still returns the PDF."""
    from PIL import Image

    from oceanx.figure_delivery import PDF_PREVIEW_EDGE
    key = "single-agent-x"
    outputs = tmp_path / "agents" / key / "outputs"
    outputs.mkdir(parents=True)
    figure = outputs / "sst_response.pdf"
    _vector_pdf(figure)
    store = TaskResultStore(task_workspaces=_Projector(tmp_path))
    (record,) = store.list(task_id="task")
    assert [(item.path, item.mime_type) for item in record.files] == [
        ("sst_response.pdf", "application/pdf"), ("preview.png", "image/png")]
    assert (record.content["figure_file"], record.content["preview_file"]) == ("sst_response.pdf", "preview.png")
    assert store.file_path(ref=record.ref, relative_path="sst_response.pdf") == figure.resolve()
    preview = store.file_path(ref=record.ref, relative_path="preview.png")
    assert preview.parent == (tmp_path / ".runtime" / "figure-previews").resolve()
    with Image.open(preview) as image:
        assert image.format == "PNG" and max(image.size) == PDF_PREVIEW_EDGE
    # The preview is not a figure of its own, and one that was cleaned up is drawn again.
    assert len(store.list(task_id="task")) == 1
    preview.unlink()
    (again,) = store.list(task_id="task")
    assert store.file_path(ref=again.ref, relative_path="preview.png").is_file()
    # A PDF that cannot be drawn is still delivered, as its file alone.
    (outputs / "broken.pdf").write_bytes(b"%PDF-1.7 not really")
    broken = next(item for item in store.list(task_id="task") if item.content["figure_file"] == "broken.pdf")
    assert [item.path for item in broken.files] == ["broken.pdf"] and broken.content["preview_file"] == "broken.pdf"


def test_the_figure_rules_ask_for_a_vector_pdf_in_the_desktop_and_keep_png_in_static_runs():
    from oceanx.runtime import OCEAN_EXPERT_WORKSTREAM_POLICY, STATIC_EXPERT_WORKSTREAM_POLICY
    from oceanx.skills import ocean_reference_root
    interactive = " ".join(OCEAN_EXPERT_WORKSTREAM_POLICY.split())
    assert "save it as a vector PDF under OCEAN_OUTPUT_DIR" in interactive and "'concise-name.pdf'" in interactive
    assert "Save a PNG instead only when the figure is itself a picture" in interactive
    # Benchmark runs (static delivery) keep the image every arm delivers, so runs stay comparable.
    static = " ".join(STATIC_EXPERT_WORKSTREAM_POLICY.split())
    assert "save it as a PNG under OCEAN_OUTPUT_DIR" in static and "vector PDF" not in static
    reference = " ".join((ocean_reference_root() / "coding" / "matplotlib.md").read_text(encoding="utf-8").split())
    assert "Save a vector PDF" in reference and "pdf.fonttype=42" in reference
    assert "save the same figure also as a draft PNG, whose name starts with `_`" in reference


def test_a_static_receipt_names_saved_figures_and_no_published_results():
    figures = (("/task/agents/a/outputs/map.png", "mld map"), ("/task/agents/a/outputs/ts.pdf", "ts"))
    receipt = format_expert_receipt("Result: shown.", Path("/task/report.md"), saved_figures=figures)
    assert ("Saved figures (cite these paths):\n- /task/agents/a/outputs/map.png — mld map\n"
            "- /task/agents/a/outputs/ts.pdf — ts\n\nReport: /task/report.md") in receipt
    assert "Published results" not in receipt and "bracket" not in receipt
    assert parse_expert_receipt(receipt)[1] == "/task/report.md"
    assert "Saved figures (cite these paths):\n- None" in format_expert_receipt(
        "Result: none.", None, saved_figures=())
    # Without saved_figures the receipt is the interactive one.
    assert "Published results (only these bracket bindings open in the desktop):" in format_expert_receipt(
        "Result: shown.", None)


@pytest.mark.asyncio
async def test_an_interactive_expert_receipt_publishes_a_saved_image_as_a_binding(monkeypatch, tmp_path):
    monkeypatch.delenv(FIGURE_DELIVERY_ENV, raising=False)
    role, question = "ocean_process_expert", "B1.2: reproduce the stippled trend map"
    key = expert_agent_key("task", role, question, node_id="B1.2")
    projector = _Projector(tmp_path)
    fake_host = SimpleNamespace(
        research=ResearchServices(SimpleNamespace(task_workspace_projector=projector,
                                                  expert_code_execution=None)),
        task_workspace_projector=projector, expert_code_execution=None,
        task_results=TaskResultStore(task_workspaces=projector))
    monkeypatch.setattr(services, "current_delegation", lambda: SimpleNamespace(
        node_id="B1.2", delegation_id="delegation", attempt_id="attempt", started_at=None))
    attached = []

    def attach_result(node_id, **kwargs):
        attached.append(kwargs)
        return {"projection": {"nodes": [{"id": node_id, "result": {}}]}}

    root = tmp_path / "agents" / key
    report = root / "reports" / "B1.2" / "report.md"

    class Author:
        async def ainvoke(self, state, config):
            (root / "outputs").mkdir(parents=True)
            (root / "outputs" / "trend_map.png").write_bytes(PNG)
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("## Summary\nResult: the trend is significant.\n", encoding="utf-8")
            return {"messages": [*state["messages"], AIMessage(content="Done.")]}

    async def fake_build(*_args, **_kwargs):
        return Author()

    monkeypatch.setattr(graphs, "host", lambda: fake_host)
    monkeypatch.setattr(graphs, "build", fake_build)
    monkeypatch.setattr(graphs, "research_tree", lambda _task: SimpleNamespace(attach_result=attach_result))
    graph = await graphs.expert(_config(), role)
    result = await graph.ainvoke({"messages": [HumanMessage(content=question)]}, _config())

    receipt = result["messages"][-1].text
    assert (f"Published results (only these bracket bindings open in the desktop):\n"
            f"- [{key}/trend_map.png] — trend map") in receipt
    assert "Saved figures" not in receipt
    assert attached[0]["output_refs"] == (f"{key}/trend_map.png",)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_figure", [True, False])
async def test_a_static_expert_receipt_lists_its_own_saved_figures(monkeypatch, tmp_path, with_figure):
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, "static")
    role, question = "ocean_process_expert", "B1.2: test transport"
    key = expert_agent_key("task", role, question, node_id="B1.2")
    other = expert_agent_key("task", role, "B1.3: another node", node_id="B1.3")
    projector = _Projector(tmp_path)
    fake_host = SimpleNamespace(
        research=ResearchServices(SimpleNamespace(task_workspace_projector=projector,
                                                  expert_code_execution=None)),
        task_workspace_projector=projector, expert_code_execution=None,
        task_results=TaskResultStore(task_workspaces=projector))
    monkeypatch.setattr(services, "current_delegation", lambda: SimpleNamespace(
        node_id="B1.2", delegation_id="delegation", attempt_id="attempt", started_at=None))
    attached = []

    def attach_result(node_id, **kwargs):
        attached.append(kwargs)
        return {"projection": {"nodes": [{"id": node_id, "result": {}}]}}

    root = tmp_path / "agents" / key
    report = root / "reports" / "B1.2" / "report.md"

    class Author:
        async def ainvoke(self, state, config):
            if with_figure:
                (root / "outputs" / "maps").mkdir(parents=True)
                (root / "outputs" / "maps" / "mld_anomaly.png").write_bytes(PNG)
                (root / "outputs" / "_probe.png").write_bytes(PNG)  # a draft is not delivered
            (tmp_path / "agents" / other / "outputs").mkdir(parents=True)
            (tmp_path / "agents" / other / "outputs" / "elsewhere.png").write_bytes(PNG)
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("## Summary\nResult: transport is weak.\n", encoding="utf-8")
            return {"messages": [*state["messages"], AIMessage(content="Done.")]}

    async def fake_build(*_args, **_kwargs):
        return Author()

    monkeypatch.setattr(graphs, "host", lambda: fake_host)
    monkeypatch.setattr(graphs, "build", fake_build)
    monkeypatch.setattr(graphs, "research_tree", lambda _task: SimpleNamespace(attach_result=attach_result))
    graph = await graphs.expert(_config(), role)
    result = await graph.ainvoke({"messages": [HumanMessage(content=question)]}, _config())

    receipt = result["messages"][-1].text
    figure = (root / "outputs" / "maps" / "mld_anomaly.png").resolve()
    if with_figure:
        assert f"Saved figures (cite these paths):\n- {figure} — mld anomaly" in receipt
        assert attached[0]["output_refs"] == (f"{key}/maps/mld_anomaly.png",)
    else:
        assert "Saved figures (cite these paths):\n- None" in receipt
        assert attached[0]["output_refs"] == ()
    assert "elsewhere.png" not in receipt and "_probe.png" not in receipt
    assert "Published results" not in receipt
    assert parse_expert_receipt(receipt)[1] == str(report)


@pytest.mark.parametrize("delivery", ["interactive", "static"])
def test_cache_cleanup_keeps_delivered_images_in_either_delivery_mode(monkeypatch, tmp_path, delivery):
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, delivery)
    now = datetime(2026, 9, 24, tzinfo=UTC)
    agent = _managed_agent(tmp_path)
    for name in ("figure.png", "_draft.png", "data.nc"):
        (agent / "outputs" / name).write_bytes(b"x")
    (agent / "scratch" / "explore.png").write_bytes(b"x")
    TaskCacheCleaner(
        store=_CleanupStore(_task(now)), task_workspaces=_CleanupProjector(tmp_path),
    ).clean_task("task", now=now)
    assert (agent / "outputs" / "figure.png").exists()
    assert not (agent / "outputs" / "_draft.png").exists()
    assert not (agent / "outputs" / "data.nc").exists()
    assert not (agent / "scratch" / "explore.png").exists()


def test_a_static_skill_library_has_no_plotting_skill(monkeypatch, tmp_path):
    monkeypatch.delenv(FIGURE_DELIVERY_ENV, raising=False)
    interactive = prepare_skill_library(tmp_path / "interactive", role="ocean_process_expert")
    assert (interactive / "skills" / "scientific-figure-design" / "SKILL.md").is_file()
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, "static")
    static = prepare_skill_library(tmp_path / "static", role="ocean_process_expert")
    assert static != interactive
    assert not (static / "skills" / "scientific-figure-design").exists()
    others = {path.name for path in (interactive / "skills").iterdir()} - {"scientific-figure-design"}
    assert others and others == {path.name for path in (static / "skills").iterdir()}


@pytest.mark.parametrize("delivery, names_the_interface", [("interactive", True), ("static", False)])
def test_the_run_code_tool_describes_figure_delivery_for_its_mode(monkeypatch, delivery, names_the_interface):
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, delivery)
    tool = OceanExpertRunCodeTool(OceanToolServices(
        workspace_id="ws", provider_id="p", store=SimpleNamespace(), task_id="t",
        agent_thread_id="a", server_run_id="r", expert_code_execution=SimpleNamespace()))
    assert ("ScientificFigure" in tool.description) is names_the_interface
    assert ("PNG" in tool.description) is not names_the_interface
    assert "OCEAN_OUTPUT_DIR" in tool.to_api_schema()["description"]


def test_both_visual_follow_up_policies_make_the_same_rule():
    for policy in (graphs.COORDINATOR_VISUAL_DELIVERY_POLICY, graphs.STATIC_COORDINATOR_VISUAL_DELIVERY_POLICY):
        text = " ".join(policy.split())
        assert ("omitted a visual that the user explicitly asked for, you may make one and only one "
                "follow-up task call") in text
        assert "A visual that you added yourself in an Expert assignment does not qualify." in text
        assert "Never make a second visual-delivery follow-up" in text
    static = graphs.STATIC_COORDINATOR_VISUAL_DELIVERY_POLICY
    assert "Saved figures" in static and not [name for name in INTERFACE_NAMES if name in static]


async def _model_visible_text(host, config, role, delivery, monkeypatch, seen):
    """Everything the role's model is shown: system prompt, tool schemas and skill library."""
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, delivery)
    seen.clear()
    if role == "coordinator":
        await graphs._coordinator_agent(config)
        agent_root = host.task_workspace_projector.ensure_task_root(config["configurable"]["task_id"]) \
            / "agents" / "coordinator"
    else:
        run = services.AgentRun.from_config(config, role, question="B1: static figures")
        await graphs.build(config, role, run=run)
        agent_root = host.task_workspace_projector.expert_session_root(run.task_id, run.thread_id)
    texts = [seen["system_prompt"]]
    texts += [json.dumps(tool.to_api_schema(), default=str) for tool in seen["tools"].list_tools()]
    library = seen.get("skill_library")
    if library is not None:
        texts += [path.read_text(encoding="utf-8", errors="replace")
                  for path in Path(library).rglob("*") if path.is_file()]
    return "\n".join(texts), agent_root / ".runtime" / "result-api.md", library


@pytest.mark.asyncio
async def test_a_static_run_shows_no_model_a_plotting_interface(tmp_path, monkeypatch):
    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _: None)
    try:
        _client, _recorder, context = await _open_workspace(host, workspace)
        task = host.store.create_research_task(workspace_id=context["workspace_id"], title="Static figures")
        monkeypatch.setattr(graphs, "host", lambda: host)
        monkeypatch.setattr(graphs, "load_model_profile", lambda _: SimpleNamespace(provider="openai"))
        monkeypatch.setattr("oceanx.model_config.profile_supports_vision", lambda _profile: True)
        monkeypatch.setattr("oceanx.research.metering.CallMeter", lambda *args, **kwargs: BaseCallbackHandler())
        seen = {}

        async def capture(**kwargs):
            seen.update(kwargs)
            return SimpleNamespace(with_config=lambda **_: "graph")

        monkeypatch.setattr(graphs, "build_deep_agent_graph", capture)
        cases = [
            ("coordinator", "research"), ("coordinator", "standard"),
            ("ocean_process_expert", "research"), ("ocean_process_expert", "standard"),
            ("statistical_inference_expert", "research"),
            ("literature_reproduction_expert", "research"),
            ("scientific_discussion_partner", "research"),
        ]
        for delivery in ("interactive", "static"):
            for role, mode in cases:
                config = {"configurable": {
                    "workspace_id": context["workspace_id"], "workspace_path": str(workspace),
                    "task_id": task.task_id, "thread_id": "static_figures", "request_id": "req_static",
                    "ls_agent_type": "subagent", "request_options": {"workflow_mode": mode},
                }}
                text, result_api, library = await _model_visible_text(
                    host, config, role, delivery, monkeypatch, seen)
                label = f"{role} / {mode} / {delivery}"
                leaked = [name for name in INTERFACE_NAMES if name in text]
                if delivery == "static":
                    assert not leaked, f"{label} shows {leaked}"
                    assert not result_api.exists(), label  # not even a stale file from an earlier mode
                    if library is not None:
                        assert not (Path(library) / "skills" / "scientific-figure-design").exists(), label
                    if role in {"ocean_process_expert", "statistical_inference_expert"}:
                        assert "PNG" in text and "OCEAN_OUTPUT_DIR" in text, label
                    if role == "coordinator":
                        assert "Saved figures" in text, label
                elif role == "coordinator":
                    # The interactive prompts still describe the interface, so the check above bites.
                    assert "Published results" in text, label
                elif role != "scientific_discussion_partner":
                    assert "Figure API" in text and result_api.is_file(), label
                    if role in {"ocean_process_expert", "statistical_inference_expert"}:  # the skill's roles
                        assert (Path(library) / "skills" / "scientific-figure-design").is_dir(), label
    finally:
        await host.close()
