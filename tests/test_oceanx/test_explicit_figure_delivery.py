"""Only explicitly saved ScientificFigure outputs become desktop results."""

from pathlib import Path
from types import SimpleNamespace

import xarray as xr

from oceanx.scientific_view import ScientificFigure
from oceanx.task_results import TaskResultStore


class _Store:
    def __init__(self, execution):
        self.execution = execution

    @staticmethod
    def get_research_task(_task_id):
        return SimpleNamespace(workspace_id="workspace")

    def list_task_code_executions(self, *, workspace_id, task_id):
        assert workspace_id == "workspace"
        assert task_id == "task"
        return (self.execution,)


class _Projector:
    def __init__(self, root: Path, execution):
        self.root = root
        self.store = _Store(execution)

    def ensure_task_root(self, _task_id):
        return self.root


def test_only_explicit_scientific_figure_event_is_exposed(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    agent_key = "ocean-process-test"
    work_root = task_root / "agents" / agent_key
    outputs = work_root / "outputs"
    outputs.mkdir(parents=True)

    xr.Dataset({"intermediate": ("sample", [1.0, 2.0, 3.0])}).to_netcdf(
        outputs / "intermediate.nc"
    )
    (outputs / "orphan-preview.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    figure = ScientificFigure(
        plot_kind="time_series",
        title="Explicit temperature figure",
        caption="The declared figure is visible; the ordinary NetCDF is not.",
    )
    figure.panel(
        x=[1, 2, 3],
        y=[4.0, 5.0, 6.0],
        x_label="Month",
        y_label="Temperature",
        y_units="degC",
    ).line(label="Temperature")
    figure.save(outputs / "temperature.nc")

    execution = SimpleNamespace(
        state="succeeded",
        result={
            "work_root": str(work_root),
            "discovered_results": [
                {
                    "schema_version": "ocean-result-event/v1",
                    "kind": "interactive_view",
                    "data_output": "temperature.nc",
                    "preview_output": "temperature.preview.png",
                    "title": "Explicit temperature figure",
                    "summary": "Declared by ScientificFigure.save().",
                }
            ],
        },
        request={"origin_request_id": "request"},
        agent_thread_id=agent_key,
        execution_id="execution",
        ended_at="2026-09-19T00:00:00+00:00",
    )
    records = TaskResultStore(
        task_workspaces=_Projector(task_root, execution)
    ).list(task_id="task")

    assert len(records) == 1
    assert records[0].title == "Explicit temperature figure"
    assert records[0].content["output_path"].endswith("/temperature.nc")
    assert all("intermediate.nc" not in name for name in records[0].execution_output_names)
    assert all("orphan-preview.png" not in name for name in records[0].execution_output_names)
    assert records[0].content["render_status"] == "interactive"


def test_self_describing_file_without_save_event_is_not_exposed(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    agent_key = "statistics-test"
    work_root = task_root / "agents" / agent_key
    outputs = work_root / "outputs"
    outputs.mkdir(parents=True)

    figure = ScientificFigure(plot_kind="scatter", title="Unannounced figure")
    figure.panel(x=[1, 2], y=[2, 3]).scatter()
    figure.save(outputs / "unannounced.nc")

    execution = SimpleNamespace(
        state="succeeded",
        result={"work_root": str(work_root), "discovered_results": []},
        request={},
        agent_thread_id=agent_key,
        execution_id="execution",
        ended_at="2026-09-19T00:00:00+00:00",
    )
    records = TaskResultStore(
        task_workspaces=_Projector(task_root, execution)
    ).list(task_id="task")

    assert records == ()


def test_saved_figure_survives_a_later_execution_failure(tmp_path: Path) -> None:
    task_root = tmp_path / "task"
    agent_key = "ocean-process-failed"
    work_root = task_root / "agents" / agent_key
    outputs = work_root / "outputs"
    outputs.mkdir(parents=True)

    figure = ScientificFigure(plot_kind="scatter", title="Saved before failure")
    figure.panel(x=[1, 2], y=[2, 3]).scatter()
    figure.save(outputs / "saved.nc")

    execution = SimpleNamespace(
        state="failed",
        result={
            "work_root": str(work_root),
            "discovered_results": [
                {
                    "schema_version": "ocean-result-event/v1",
                    "kind": "interactive_view",
                    "data_output": "saved.nc",
                    "preview_output": "saved.preview.png",
                    "title": "Saved before failure",
                }
            ],
        },
        request={},
        agent_thread_id=agent_key,
        execution_id="execution-failed",
        ended_at="2026-09-19T00:00:00+00:00",
    )
    records = TaskResultStore(
        task_workspaces=_Projector(task_root, execution)
    ).list(task_id="task")

    assert len(records) == 1
    assert records[0].title == "Saved before failure"
