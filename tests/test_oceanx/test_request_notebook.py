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


def test_a_run_embeds_the_delivered_images_it_saved(tmp_path, monkeypatch):
    import os

    from oceanx import expert_execution
    from oceanx.expert_execution import _image_outputs, _output_state

    outputs = tmp_path / "outputs"
    (outputs / "maps").mkdir(parents=True)
    kept = outputs / "fig1.png"
    kept.write_bytes(b"old")
    before = _output_state(outputs)
    (outputs / "maps" / "fig2.png").write_bytes(b"\x89PNG new")      # saved by this run, in a subfolder
    (outputs / "_draft.png").write_bytes(b"draft")                   # a draft is not delivered
    (outputs / "view.preview.png").write_bytes(b"preview")           # an interactive view's preview
    (outputs / "field.nc").write_bytes(b"CDF")                       # data are never embedded
    (outputs / "big.jpg").write_bytes(b"x" * 64)
    monkeypatch.setattr(expert_execution, "MAX_NOTEBOOK_IMAGE_BYTES", 32)

    embedded = _image_outputs(outputs, before)

    assert [output.get("data", {}).get("text/plain") or output["text"] for output in embedded] == [
        ["[outputs/big.jpg is too large to show here]\n"], ["outputs/maps/fig2.png"]]
    assert embedded[1]["data"]["image/png"] == "iVBORyBuZXc="  # base64 of the saved bytes
    os.utime(kept, ns=(before["fig1.png"][0] + 10**9,) * 2)            # an image saved again is shown again
    assert [output["data"]["text/plain"] for output in _image_outputs(outputs, before)
            if output["output_type"] == "display_data"] == [["outputs/fig1.png"], ["outputs/maps/fig2.png"]]


def test_a_run_shows_a_pdf_figure_it_saved_through_a_drawing_of_its_first_page(tmp_path):
    import base64

    from oceanx.expert_execution import _image_outputs, _output_state
    from tests.test_oceanx.test_static_figure_delivery import _vector_pdf

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    before = _output_state(outputs)
    _vector_pdf(outputs / "section.pdf")
    (outputs / "broken.pdf").write_bytes(b"%PDF-1.7 not really")
    shown = _image_outputs(outputs, before)
    assert shown[0] == {"name": "stdout", "output_type": "stream",
                        "text": ["[outputs/broken.pdf could not be drawn here]\n"]}
    assert shown[1]["data"]["text/plain"] == ["outputs/section.pdf"]
    assert base64.b64decode(shown[1]["data"]["image/png"]).startswith(b"\x89PNG")


def test_the_request_notebook_keeps_images_within_its_budget(tmp_path, monkeypatch):
    from oceanx import request_notebook as module

    agents = tmp_path / "agents"
    image = {"output_type": "display_data", "metadata": {},
             "data": {"image/png": "QUJD" * 4, "text/plain": ["outputs/fig.png"]}}
    records = [_run(agents, "single-agent-bbbbbbbbbb", f"codeexec_{n}", f"2026-10-26T10:0{n}:00+00:00")
               for n in (1, 2)]
    for record in records:  # each run saved the figure once
        path = agents / record.agent_thread_id / ".runtime" / "executions" / record.execution_id / "code" / "analysis.ipynb"
        notebook = json.loads(path.read_text(encoding="utf-8"))
        notebook["cells"][-1]["outputs"] = [image]
        path.write_text(json.dumps(notebook), encoding="utf-8")
    monkeypatch.setattr(module, "MAX_IMAGE_CHARACTERS", 20)  # room for one of the two

    data, _ = module.request_notebook(records, lambda key: agents / key, request_id="req_1")
    first, second = [cell["outputs"] for cell in json.loads(data)["cells"] if cell["cell_type"] == "code"]
    assert first == [{"output_type": "display_data", "metadata": {},
                      "data": {"image/png": "QUJD" * 4, "text/plain": ["outputs/fig.png"]}}]
    assert second[0]["output_type"] == "stream" and "outputs/fig.png left out" in second[0]["text"][0]
