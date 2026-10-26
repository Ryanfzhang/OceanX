"""The code every agent ran for one request, joined into the notebook listed after its answer."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from oceanx.request_notebook import MAX_OUTPUT_CHARACTERS, request_notebook


def _run(agents: Path, agent: str, execution: str, started: str, *, request: str = "req_1",
         purpose: str = "Compute", code: str = "x = 1\n", stdout: str = "", command: str | None = None):
    """An execution record and the files expert_execution.py leaves for it."""

    code_root = agents / agent / ".runtime" / "executions" / execution / "code"
    code_root.mkdir(parents=True)
    outputs = [{"name": "stdout", "output_type": "stream", "text": stdout.splitlines(keepends=True)}] if stdout else []
    (code_root / "analysis.ipynb").write_text(json.dumps({"cells": [
        {"cell_type": "markdown", "metadata": {}, "source": ["# OceanX Expert analysis\n"]},
        {"cell_type": "code", "metadata": {}, "outputs": [], "source": ["import setup\n"]},
        {"cell_type": "code", "metadata": {}, "outputs": outputs, "source": code.splitlines(keepends=True)},
    ]}), encoding="utf-8")
    if command is not None:
        (code_root / "command.sh").write_text(command, encoding="utf-8")
    return SimpleNamespace(execution_id=execution, agent_thread_id=agent, state="completed",
                           request={"purpose": purpose, "origin_request_id": request},
                           started_at=started, ended_at=started.replace(":00+", ":30+"))


def test_one_request_becomes_one_notebook_with_a_section_per_agent(tmp_path):
    agents = tmp_path / "agents"
    records = [
        _run(agents, "ocean-process-aaaaaaaaaa", "codeexec_3", "2026-10-26T10:03:00+00:00",
             purpose="Layer vorticity", code="gamma = 4.1e-5\nprint(gamma)\n", stdout="4.1e-05\n"),
        _run(agents, "single-agent-bbbbbbbbbb", "codeexec_1", "2026-10-26T10:01:00+00:00",
             purpose="Inspect the data", code="import xarray as xr\n"),
        _run(agents, "single-agent-bbbbbbbbbb", "codeexec_2", "2026-10-26T10:02:00+00:00",
             purpose="Shell command", command="ncdump -h data.nc", stdout="x" * (MAX_OUTPUT_CHARACTERS + 50)),
        _run(agents, "single-agent-bbbbbbbbbb", "codeexec_0", "2026-10-26T09:00:00+00:00", request="req_0"),
    ]

    data, runs = request_notebook(records, lambda key: agents / key, request_id="req_1")
    notebook = json.loads(data)

    assert runs == 3 and notebook["nbformat"] == 4
    texts = ["".join(cell["source"]) for cell in notebook["cells"]]
    # The first agent to run comes first, and runs of another request are left out.
    assert [text.splitlines()[0] for text in texts if text.startswith("## ")] == [
        "## OceanX", "## Ocean process Expert"]
    assert "### Run 1: Inspect the data" in texts[2] and "import xarray as xr\n" == texts[3]
    # A shell run shows its command, and a long output keeps its head and tail.
    shell = notebook["cells"][5]
    assert shell["source"] == ["%%bash\n", "ncdump -h data.nc"] and shell["execution_count"] == 2
    printed = "".join(shell["outputs"][0]["text"])
    assert "50 characters left out" in printed and len(printed) < MAX_OUTPUT_CHARACTERS + 100
    expert = notebook["cells"][-1]
    assert "".join(expert["outputs"][0]["text"]) == "4.1e-05\n" and expert["execution_count"] == 3
    assert "completed, 30 s" in texts[-2]


def test_a_request_without_code_has_no_notebook_and_a_lost_run_is_named(tmp_path):
    agents = tmp_path / "agents"
    assert request_notebook([], lambda key: agents / key, request_id="req_1") is None
    lost = SimpleNamespace(execution_id="codeexec_9", agent_thread_id="helper-cccccccccc", state="failed",
                           request={"purpose": "Gone", "origin_request_id": "req_1"},
                           started_at="2026-10-26T10:00:00+00:00", ended_at=None)
    data, runs = request_notebook([lost], lambda key: agents / key, request_id="req_1")
    notebook = json.loads(data)
    assert runs == 1 and "## Helper" in "".join(notebook["cells"][1]["source"])
    assert "no longer in the task folder" in "".join(notebook["cells"][-1]["source"])


async def test_the_router_lists_one_notebook_per_request_and_announces_it(tmp_path):
    from oceanx.backend.router import OceanRequestRouter
    from oceanx.task_results import TaskResultStore

    agents = tmp_path / "agents"
    record = _run(agents, "single-agent-bbbbbbbbbb", "codeexec_1", "2026-10-26T10:01:00+00:00")

    class Projector:
        store = SimpleNamespace(get_research_task=lambda _task: SimpleNamespace(workspace_id="ws"),
                                list_task_code_executions=lambda **_: ())

        def ensure_task_root(self, _task):
            return tmp_path

        def expert_session_root(self, _task, key):
            return agents / key

    events = []

    async def emit(event):
        events.append(event)

    router = SimpleNamespace(task_results=TaskResultStore(task_workspaces=Projector()),
                             store=SimpleNamespace(list_task_code_executions=lambda **_: (record,)),
                             event_bus=SimpleNamespace(emit_workspace=emit))
    session = SimpleNamespace(task_id="task_1", workspace_id="ws")
    for _ in range(2):  # a request has one notebook however often it is published
        await OceanRequestRouter._publish_request_notebook(router, session, "req_1")
    (notebook,) = [result for result in router.task_results.list(task_id="task_1")
                   if result.content.get("role") == "analysis_notebook"]
    assert notebook.origin_request_id == "req_1" and notebook.content["runs"] == 1
    assert [(file.path, file.mime_type) for file in notebook.files] == [("analysis.ipynb", "application/x-ipynb+json")]
    assert events[0].type == "task.results.changed" and events[0].request_id == "req_1"
    await OceanRequestRouter._publish_request_notebook(router, session, "req_2")  # no code ran for it
    assert len(events) == 2
