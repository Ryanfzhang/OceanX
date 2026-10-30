"""Contracts survive real middleware compaction; comparison notes do not gate delivery."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from oceanx.reproduction import ReproductionMiddleware, SUMMARY_PROMPT, reproduction_tools
from oceanx.reproduction_state import (
    FigureSpec, PanelSpec, ReproductionStore, TermEvidence,
)
from oceanx.task_results import TaskResultStore
from tests.test_oceanx.test_deep_agent_runtime import _BoundFakeModel
from tests.test_oceanx.test_static_figure_delivery import _Projector


def spec(reference="/paper/page.png", terms=None):
    return FigureSpec(figure_id="figure-3", output_file="figure.png", reference_image=reference,
        caption="Circulation and planetary vorticity flux over time",
        panels=[PanelSpec(panel="b", plot_type="time series", x_axis="time (years)",
            y_axes=["circulation", "planetary vorticity flux"],
            quantities=["C", "xi_cor"], units_scales="m/s and m/s2",
            layout_overlays="two y axes; trend lines; upper layer")],
        budget_terms=terms or [])


def test_spec_revisions_preserve_original_and_terms_require_evidence(tmp_path):
    store = ReproductionStore(tmp_path)
    original = store.register(spec(terms=["pressure", "stress"]))
    original_bytes = original.read_bytes()
    assert store.pending("figure-3") == ["pressure", "stress"]
    changed = spec(terms=["pressure", "stress", "advection"])
    with pytest.raises(ValueError, match="immutable"):
        store.register(changed)
    store.register(changed, "Original caption also lists advection; checked page 5")
    assert original.read_bytes() == original_bytes
    assert len(list(original.parent.glob("spec-*.json"))) == 2
    with pytest.raises(ValidationError, match="checked files"):
        TermEvidence(term="stress", status="not_computable", evidence="not found")
    store.record_term("figure-3", TermEvidence(term="stress", status="not_computable",
        evidence="Inspected archive inventory", checked_sources=["inventory.json"],
        missing_inputs=["wind stress"], derivation_checked="No stress or wind forcing stored"))
    assert store.pending("figure-3") == ["pressure", "advection"]
    assert ReproductionStore(tmp_path).context() == store.context()
    assert "time (years)" in store.context()


def test_figures_remain_visible_with_pending_terms_and_old_rejections(tmp_path):
    import json
    agent = tmp_path / "agents" / "worker"
    outputs = agent / "outputs"
    outputs.mkdir(parents=True)
    output = outputs / "figure.png"
    output.write_bytes(b"first-version")
    results = TaskResultStore(task_workspaces=_Projector(tmp_path))
    store = ReproductionStore(agent)
    store.register(spec(terms=["pressure"]))
    assert store.pending("figure-3") == ["pressure"]
    assert len(results._static_figures(task_id="task")) == 1
    # Old approval/rejection records must not keep existing figures hidden.
    (store.directory("figure-3") / "review.json").write_text(json.dumps({"review": {"passed": False}}))
    store.record_check("figure-3", {"status": "completed", "accepted": False,
        "review": {"findings": [{"category": "structure", "detail": "Missing pressure series"}]}})
    assert len(results._static_figures(task_id="task")) == 1
    output.write_bytes(b"second-version")
    assert len(results._static_figures(task_id="task")) == 1
    with pytest.raises((ValueError, OSError)):
        store.output("../../unrelated.png")


@pytest.mark.asyncio
async def test_real_compaction_reinjects_verbatim_specs_without_polluting_history(tmp_path):
    store = ReproductionStore(tmp_path)
    path = store.register(spec())
    worker = _BoundFakeModel(responses=[AIMessage(content="done")])
    summarizer = _BoundFakeModel(responses=[AIMessage(content="Draw C vs xi as a scatterplot")])
    backend = StateBackend()
    summary = SummarizationMiddleware(model=summarizer, backend=backend,
        trigger=("messages", 4), keep=("messages", 2), summary_prompt=SUMMARY_PROMPT)
    graph = create_deep_agent(model=worker, backend=backend, middleware=[
        summary, ReproductionMiddleware(tmp_path)], system_prompt="test")
    history = []
    for i in range(4):
        history += [HumanMessage(content=f"step {i}"), AIMessage(content=f"response {i}")]
    history += [HumanMessage(content="finish")]
    result = await graph.ainvoke({"messages": history})
    assert summarizer.seen_messages  # actual compaction, not just a string assertion
    sent = worker.seen_messages[-1]
    assert "Draw C vs xi as a scatterplot" in "\n".join(m.text for m in sent)
    assert path.read_text() in sent[-1].text
    assert "time (years)" in sent[-1].text
    assert not any("Persistent reproduction contracts" in m.text for m in result["messages"])
    # A restarted middleware re-reads the file, not an in-memory cached summary.
    restarted = ReproductionMiddleware(tmp_path)
    assert restarted.store.context() == store.context()


class DownloadBackend:
    async def adownload_files(self, paths):
        return [SimpleNamespace(content=Path(p).read_bytes(), error=None) for p in paths]


def image(path):
    from PIL import Image
    Image.new("RGB", (24, 24), "white").save(path)


@pytest.mark.asyncio
async def test_production_factory_registers_tools_and_skill_read_activates_continuity(tmp_path, monkeypatch):
    from oceanx import deep_runtime
    from oceanx.agent_tools import ToolRegistry
    model = _BoundFakeModel(responses=[
        AIMessage(content="", tool_calls=[{"name": "read_file", "id": "read-skill",
            "args": {"file_path": "/skills/paper-reproduction/SKILL.md"}}]),
        AIMessage(content="done"),
    ])
    monkeypatch.setattr(deep_runtime, "create_chat_model", lambda _: model)
    graph = await deep_runtime.build_deep_agent_graph(
        profile=None, tools=ToolRegistry(), system_prompt="test", cwd=tmp_path,
        operation_id_factory=lambda *args: "operation", reproduction_root=tmp_path,
        filesystem_backend=StateBackend())
    result = await graph.ainvoke({"messages": [HumanMessage(content="reproduce paper")]})
    assert ReproductionStore(tmp_path).active
    assert "No specs registered" in model.seen_messages[-1][-1].text
    assert {"record_reproduction_spec", "record_reproduction_term", "review_reproduction_figure"} <= set(model.bound_tool_names[-1])
    assert "Durable paper reproduction" in model.seen_messages[0][0].text
    assert not any("Persistent reproduction contracts" in m.text for m in result["messages"])


@pytest.mark.asyncio
@pytest.mark.parametrize('reproduction', [False, True])
async def test_summary_policy_changes_only_after_entering_reproduction(tmp_path, reproduction):
    from oceanx.reproduction import ReproductionSummarizationMiddleware
    from deepagents.middleware.summarization import DEEPAGENTS_DEFAULT_SUMMARY_PROMPT
    worker = _BoundFakeModel(responses=[AIMessage(content='done')])
    summarizer = _BoundFakeModel(responses=[AIMessage(content='Compact record')])
    if reproduction:
        ReproductionStore(tmp_path).register(spec())
    def factory(model, backend, summary_prompt=DEEPAGENTS_DEFAULT_SUMMARY_PROMPT):
        return SummarizationMiddleware(model=summarizer, backend=backend,
            trigger=('messages', 4), keep=('messages', 2), summary_prompt=summary_prompt)
    backend = StateBackend()
    middleware = ReproductionSummarizationMiddleware(worker, backend, tmp_path, factory=factory)
    graph = create_deep_agent(model=worker, backend=backend, middleware=[middleware])
    history=[]
    for i in range(4):
        history.extend([HumanMessage(content=f'Step {i}'), AIMessage(content=f'Result {i}')])
    history.append(HumanMessage(content='continue'))
    await graph.ainvoke({'messages':history})
    assert summarizer.seen_messages
    actual='\n'.join(m.text for m in summarizer.seen_messages[-1])
    assert ('For paper-reproduction sessions only' in actual) == reproduction


@pytest.mark.asyncio
async def test_factory_without_reproduction_has_no_review_tools_or_policy(tmp_path, monkeypatch):
    from oceanx import deep_runtime
    from oceanx.agent_tools import ToolRegistry
    model = _BoundFakeModel(responses=[AIMessage(content="done")])
    monkeypatch.setattr(deep_runtime, "create_chat_model", lambda _: model)
    graph = await deep_runtime.build_deep_agent_graph(profile=None, tools=ToolRegistry(),
        system_prompt="Research coordinator", cwd=tmp_path, operation_id_factory=lambda *args: "op",
        filesystem_backend=StateBackend())
    await graph.ainvoke({"messages": [HumanMessage(content="Investigate mechanisms")]})
    assert "review_reproduction_figure" not in model.bound_tool_names[-1]
    assert "Durable paper reproduction" not in model.seen_messages[0][0].text
    assert not ReproductionStore(tmp_path).active
