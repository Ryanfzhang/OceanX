import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from oceanx.agent_tools import ToolRegistry
from oceanx.deep_runtime import build_deep_agent_graph
from oceanx.native_skills import prepare_skill_library, skill_backend, skill_permissions
from tests.test_oceanx.test_deep_agent_runtime import _BoundFakeModel, _IncrementTool


def library(tmp_path, role="ocean_process_expert"):
    return prepare_skill_library(tmp_path / role, role=role, capabilities=("literature.read",))


def test_role_library_has_support_files_without_other_role_skills(tmp_path):
    root = library(tmp_path)
    assert (root / "skills/xarray-array-ops/scripts/oceanx_array_ops.py").is_file()
    assert not (root / "skills/paper-navigator").exists()
    lit = library(tmp_path, "literature_reproduction_expert")
    assert (lit / "skills/paper-navigator/SKILL.md").is_file()
    assert not (lit / "skills/xarray-array-ops").exists()
    assert (root / "references/methods/transport.md").is_file()


def test_current_bundle_replaces_stale_discovery_without_deleting_old_snapshots(tmp_path, monkeypatch):
    from oceanx import native_skills
    bundle = tmp_path / "bundle"
    skill = bundle / "method"
    skill.mkdir(parents=True)
    body = skill / "SKILL.md"
    body.write_text("current v1")
    references = tmp_path / "references"
    references.mkdir()
    monkeypatch.setattr(native_skills, "ocean_skill_dirs", lambda **_: (bundle,))
    monkeypatch.setattr(native_skills, "ocean_reference_root", lambda: references)
    monkeypatch.setattr(native_skills, "ocean_skill_metadata", lambda **_: (SimpleNamespace(name="method"),))
    root = tmp_path / "task" / "physics"
    stale = root / "skills" / "old-framing" / "SKILL.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("legacy procedure")
    first = native_skills.prepare_skill_library(root, role="physics")
    assert (first / "skills/method/SKILL.md").read_text() == "current v1"
    assert not (first / "skills/old-framing").exists()
    assert native_skills.prepare_skill_library(root, role="physics") == first
    body.write_text("current v2")
    second = native_skills.prepare_skill_library(root, role="physics")
    assert second != first
    assert (second / "skills/method/SKILL.md").read_text() == "current v2"
    assert (first / "skills/method/SKILL.md").read_text() == "current v1"
    assert stale.read_text() == "legacy procedure"
    monkeypatch.setattr(native_skills, "ocean_skill_metadata", lambda **_: ())
    third = native_skills.prepare_skill_library(root, role="physics")
    assert not (third / "skills/method").exists()


@pytest.mark.asyncio
async def test_native_discovery_then_body_read_and_checkpoint_followup(tmp_path, monkeypatch):
    path = "/skills/xarray-array-ops/SKILL.md"
    model = _BoundFakeModel(responses=[
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"file_path": path}, "id": "skill-1"}]),
        AIMessage(content="Read the selected array guide."),
        AIMessage(content="Continued."),
    ])
    monkeypatch.setattr("oceanx.deep_runtime.create_chat_model", lambda _: model)
    graph = await build_deep_agent_graph(profile=None, tools=ToolRegistry(), system_prompt="Fixture",
        cwd=tmp_path, operation_id_factory=lambda *args: "operation", checkpointer=MemorySaver(),
        skill_library=library(tmp_path))
    config = {"configurable": {"thread_id": "native-skills"}}
    state = await graph.ainvoke({"messages": [HumanMessage(content="Check multidimensional arrays")]}, config)
    initial = "\n".join(m.text for m in model.seen_messages[0])
    assert "xarray-array-ops" in initial and "broadcasting" in initial
    assert "ao.self_test()" not in initial  # body has not been injected at startup
    reads = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    assert len(reads) == 1 and "ao.self_test()" in reads[0].text
    assert not {"ocean_list_skills", "ocean_load_skill", "task"} & set(model.bound_tool_names[0])
    assert {"ls", "glob", "grep", "write_file", "edit_file"} <= set(model.bound_tool_names[0])
    assert "read_file" in model.bound_tool_names[0]
    metadata = (await graph.aget_state(config)).values["skills_metadata"]
    state = await graph.ainvoke({"messages": [HumanMessage(content="Follow up")]}, config)
    assert (await graph.aget_state(config)).values["skills_metadata"] == metadata
    assert sum(isinstance(m, ToolMessage) for m in state["messages"]) == 1


@pytest.mark.asyncio
async def test_native_permissions_deny_skill_write_and_filesystem_escape(tmp_path):
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from langchain.agents import create_agent
    root = library(tmp_path)
    original = (root / "skills/xarray-array-ops/SKILL.md").read_bytes()
    model = _BoundFakeModel(responses=[
        AIMessage(content="", tool_calls=[{"name": "write_file", "args": {
            "file_path": "/skills/new/SKILL.md", "content": "overwrite"}, "id": "write-1"}]),
        AIMessage(content="Done"),
    ])
    backend = skill_backend(root)
    graph = create_agent(model=model, middleware=[FilesystemMiddleware(backend=backend,
        tools=["read_file", "write_file"], _permissions=skill_permissions())])
    result = await graph.ainvoke({"messages": [HumanMessage(content="try a write")]})
    receipt = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert "denied" in receipt.text.lower()
    assert not (root / "skills/new/SKILL.md").exists()
    assert (root / "skills/xarray-array-ops/SKILL.md").read_bytes() == original
    try:
        escaped = await backend.aread("/skills/../../private.txt")
    except ValueError:
        pass
    else:
        assert escaped.error


@pytest.fixture
def ao():
    path = Path(__file__).parents[2] / "src/oceanx/resources/skills/core/xarray-array-ops/scripts/oceanx_array_ops.py"
    spec = importlib.util.spec_from_file_location("array_helper_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_array_helper_values_and_invalid_shapes(ao):
    assert "passed" in ao.self_test()
    array = np.arange(24).reshape(2, 3, 4)
    for indices in (np.zeros((2, 3), dtype=int), np.full((2, 4), -1),
                    np.full((2, 4), 3), np.zeros((2, 4), dtype=float)):
        with pytest.raises(ValueError):
            ao.column_take(array, indices, axis=1)
    with pytest.raises(ValueError):
        ao.masked_values(np.ones((2, 3)), np.ones(6, dtype=bool))
    a = xr.DataArray([1, 2], dims="lat", coords={"lat": [1, 2]})
    b = xr.DataArray([3, 4], dims="lat", coords={"lat": [2, 3]})
    with pytest.raises(ValueError):
        ao.exact_align(a, b)
    with pytest.raises(ValueError):
        ao.check_dims(a, ("lon",))
    with pytest.raises(ValueError):
        ao.small_sample(a, 0)


def test_validity_matched_weights_and_declared_units(ao):
    data = xr.DataArray([[2., np.nan], [2., 4.]], dims=("time", "lat"),
        coords={"lat": [10, 20]}, attrs={"units": "degC"})
    weights = xr.DataArray([1., 3.], dims="lat", coords={"lat": [10, 20]})
    np.testing.assert_allclose(ao.weighted_mean(data, weights, dims="lat"), [2, 3.5])
    with pytest.raises(ValueError):
        ao.weighted_mean(data, weights.rename(lat="lon"), dims="lat")
    with pytest.raises(ValueError):
        ao.weighted_mean(data * np.nan, weights, dims="lat")
    with pytest.raises(ValueError):
        ao.weighted_mean(data, weights.assign_coords(lat=[20, 30]), dims="lat")
    assert ao.rate_per_day(1, input_unit="per_second") == 86400
    assert ao.rate_per_day(1, input_unit="per_day") == 1
    with pytest.raises(ValueError):
        ao.rate_per_day(1, input_unit="unknown")
    # A temperature gradient of 1 K/degree must agree with 180/pi K/radian.
    g = ao.angular_gradient_per_metre(1., latitude=30, angle_unit="degrees", direction="zonal")
    r = ao.angular_gradient_per_metre(180/np.pi, latitude=30, angle_unit="radians", direction="zonal")
    np.testing.assert_allclose(g, r)
    np.testing.assert_allclose(g, 1/(6371000*np.cos(np.pi/6)*np.pi/180))
    with pytest.raises(ValueError):
        ao.angular_gradient_per_metre(np.ones((2, 3)), latitude=np.array([10, 20]),
            angle_unit="degrees", direction="zonal")


@pytest.mark.asyncio
async def test_native_retry_two_503s_do_not_repeat_completed_tool(tmp_path, monkeypatch):
    from oceanx.provider_retry import provider_retry_middleware

    class UnavailableModel(_BoundFakeModel):
        failures: int = 0

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if any(isinstance(m, ToolMessage) for m in messages) and self.failures < 2:
                self.failures += 1
                error = RuntimeError("temporary provider failure")
                error.status_code = 503
                raise error
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def immediate_retry():
        middleware = provider_retry_middleware()
        middleware.initial_delay = 0
        middleware.jitter = False
        return middleware

    model = UnavailableModel(responses=[
        AIMessage(content="", tool_calls=[{"name": "ocean_increment", "args": {"value": 1}, "id": "once"}]),
        AIMessage(content="Result: 2"),
    ])
    monkeypatch.setattr("oceanx.deep_runtime.create_chat_model", lambda _: model)
    monkeypatch.setattr("oceanx.provider_retry.provider_retry_middleware", immediate_retry)
    registry = ToolRegistry()
    increment = _IncrementTool()
    registry.register(increment)
    graph = await build_deep_agent_graph(profile=None, tools=registry, system_prompt="Fixture",
        cwd=tmp_path, operation_id_factory=lambda *args: "operation", skill_library=library(tmp_path))
    state = await graph.ainvoke({"messages": [HumanMessage(content="Increment once")]})
    assert model.failures == 2
    assert len(increment.contexts) == 1
    assert sum(isinstance(m, ToolMessage) for m in state["messages"]) == 1
    assert [m.content for m in state["messages"] if isinstance(m, AIMessage) and not m.tool_calls] == ["Result: 2"]
