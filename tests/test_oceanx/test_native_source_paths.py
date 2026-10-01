"""Import via the real task protocol, then use only the model-visible path."""

import json
import shlex
import sys

import pytest
import xarray as xr
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from oceanx.backend.host import OceanBackendHost
from oceanx.research import graphs
from tests.test_oceanx.test_dataset_import_router import _open_workspace
from tests.test_oceanx.test_deep_agent_runtime import _BoundFakeModel


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", ["coordinator", "ocean_process_expert", "scientific_discussion_partner"]
)
@pytest.mark.parametrize("import_kind", ["dataset.import", "source.import"])
async def test_imported_source_path_reaches_native_graph(
    tmp_path, monkeypatch, role, import_kind
):
    from types import SimpleNamespace

    from langchain_core.callbacks import BaseCallbackHandler

    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "outside workspace" / "temperature" / "2025"
    source.mkdir(parents=True)
    xr.Dataset({"temperature": ("time", [20.0, 21.0], {"units": "degC"})}).to_netcdf(
        source / "ocean.nc"
    )
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _: None)
    try:
        client, recorder, context = await _open_workspace(host, workspace)
        task = host.store.create_research_task(
            workspace_id=context["workspace_id"], title="Source paths"
        )
        context["task_id"] = task.task_id
        await host.router.handle_payload(
            client,
            {
                "protocol_version": 2,
                "request_id": "req_import_paths",
                "type": import_kind,
                "payload": (
                    {"local_path": str(source), "materialization_level": "local_reference"}
                    if import_kind == "dataset.import"
                    else {"local_path": str(source), "title": "Unclassified source folder"}
                ),
                "context": context,
                "expected_workspace_revision": 1,
            },
        )
        assert recorder.latest("request.completed").request_id == "req_import_paths"
        task_root = host.task_workspace_projector.ensure_task_root(task.task_id)
        assert {path.name for path in task_root.iterdir() if path.is_dir()} == {
            "agents", "sources"
        }
        config = {
            "configurable": {
                "workspace_id": context["workspace_id"],
                "workspace_path": str(workspace),
                "task_id": task.task_id,
                "thread_id": "source_paths",
                "request_id": "req_read_paths",
            }
        }
        monkeypatch.setattr(graphs, "host", lambda: host)
        monkeypatch.setattr(
            graphs, "load_model_profile", lambda _: SimpleNamespace(provider="openai")
        )
        monkeypatch.setattr(
            "oceanx.research.metering.CallMeter", lambda *args: BaseCallbackHandler()
        )
        original = graphs.build_deep_agent_graph

        async def capture(**kwargs):
            data_context = json.loads(
                kwargs["system_prompt"].split("Dataset and workspace context:\n", 1)[1]
            )
            item = (
                data_context["dataset_context"]["sources"][0]
                if import_kind == "dataset.import"
                else data_context["task_sources"][0]
            )
            assert item["path"] == str(source.resolve()) and item["access"] == "read_only"
            if import_kind == "dataset.import":
                assert item["handle"] == "source_1"
            else:
                assert item["kind"] == "directory"
            # A data Expert starts after the task's one-time data check; the Coordinator and
            # text-only agents never wait for Python, and see the description once it exists.
            if role in graphs.DATA_EXPERT_ROLES:
                assert item["inspection"] == "ready"
                assert {(v["name"], v.get("units")) for v in item["data_variables"]} == {
                    ("temperature", "degC")}
            else:
                assert item.get("inspection") != "ready"
            assert "reuse them rather than re-inspecting" in kwargs["system_prompt"]
            responses = [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "ls", "args": {"path": item["path"]}, "id": "list"}],
                )
            ]
            if role not in {"coordinator", "scientific_discussion_partner"}:
                code = f"import xarray as xr; ds=xr.open_dataset({item['path']!r}+'/ocean.nc'); print(dict(ds.sizes)); print(ds.temperature.attrs['units'])"
                responses.append(
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "execute",
                                "args": {"command": "python -c " + shlex.quote(code)},
                                "id": "inspect",
                            }
                        ],
                    )
                )
            if role == "coordinator":
                assert "execute" not in kwargs["filesystem_tools"]
                assert set(kwargs["filesystem_tools"]) == {
                    "ls", "glob", "grep", "read_file", "write_file", "edit_file",
                }
            elif role == "scientific_discussion_partner":
                assert kwargs["filesystem_tools"] == ["ls", "glob", "grep", "read_file"]
            else:
                assert kwargs["filesystem_tools"] == "all"
            if role == "coordinator":
                responses.append(
                    AIMessage(
                        content="",
                        tool_calls=[{"name": "ocean_resources", "args": {}, "id": "resources"}],
                    )
                )
            responses.append(AIMessage(content="Observed existing source."))
            monkeypatch.setattr(
                "oceanx.deep_runtime.create_chat_model",
                lambda _: _BoundFakeModel(responses=responses),
            )
            return await original(**kwargs)

        monkeypatch.setattr(graphs, "build_deep_agent_graph", capture)
        graph = await graphs.build(config, role)
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Inspect the supplied source.")]}
        )
        receipts = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert all(m.status != "error" for m in receipts), [m.text for m in receipts]
        assert "ocean.nc" in receipts[0].text
        if role not in {"coordinator", "scientific_discussion_partner"}:
            assert "degC" in receipts[1].text and "'time': 2" in receipts[1].text
        if role == "coordinator":
            assert json.loads(receipts[-1].text)["task_sources"][0]["path"] == str(source.resolve())
    finally:
        await host.close()
