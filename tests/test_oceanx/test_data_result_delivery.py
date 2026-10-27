from pathlib import Path
from types import SimpleNamespace

import pytest
import xarray as xr

from oceanx.task_results import TaskResultStore


class Projector:
    def __init__(self, root):
        self.root = root
        self.store = SimpleNamespace(
            get_research_task=lambda _: SimpleNamespace(workspace_id="workspace"),
            list_task_code_executions=lambda **_: (),
        )

    def ensure_task_root(self, _):
        return self.root


def test_saved_data_is_linked_with_csv_preview_and_original_download(tmp_path: Path):
    outputs = tmp_path / "agents/single/outputs"
    outputs.mkdir(parents=True)
    table = outputs / "metrics.csv"
    table.write_text('\ufeffsite,value,note\r\n"a,b",001,"first\nsecond"\r\n', encoding="utf-8")
    xr.Dataset({"temperature": ("time", [1., 2.], {"units": "degC"})}).to_netcdf(outputs / "response.nc")
    (outputs / "_draft.csv").write_text("x\n1")
    (outputs / "link.csv").symlink_to(table)
    (outputs / ".private").mkdir()
    (outputs / ".private/hidden.csv").write_text("x\n1")
    store = TaskResultStore(task_workspaces=Projector(tmp_path))
    records = store.list(task_id="task")
    assert len(records) == 2
    csv_result = next(r for r in records if r.kind == "table")
    assert csv_result.content["columns"] == ["site", "value", "note"]
    assert csv_result.content["rows"] == [["a,b", "001", "first\nsecond"]]
    assert csv_result.content["truncated"] is False
    assert "single/metrics.csv" in csv_result.execution_output_names
    assert store.get(csv_result.ref) == csv_result
    assert store.file_path(ref=csv_result.ref, relative_path="metrics.csv") == table
    data = next(r for r in records if r.kind == "file")
    assert "single/response" in data.execution_output_names
    assert "single/response.nc" in data.execution_output_names
    assert data.content["preview_kind"] == "netcdf_metadata"
    assert data.content["rows"] == [["temperature", "time", "2", "float64", "degC"]]


def test_table_preview_is_bounded_and_refreshes_when_file_changes(tmp_path: Path):
    outputs = tmp_path / "agents/single/outputs"
    outputs.mkdir(parents=True)
    table = outputs / "metrics.csv"
    table.write_text("value\n" + "\n".join(str(i) for i in range(250)))
    store = TaskResultStore(task_workspaces=Projector(tmp_path))
    first, = store.list(task_id="task")
    assert len(first.content["rows"]) == 200
    assert first.content["truncated"] is True
    assert store.file_path(ref=first.ref, relative_path="metrics.csv").read_text().endswith("249")
    table.write_text("value\nchanged\n")
    revised, = store.list(task_id="task")
    assert revised.ref == first.ref
    assert revised.content["rows"] == [["changed"]]
    assert revised.files[0].sha256 != first.files[0].sha256


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["result_file", "interactive_view_preview"])
async def test_netcdf_cannot_be_granted_as_a_download(tmp_path, purpose):
    from oceanx.backend.router import OceanRequestRouter
    from oceanx.backend.store import RequestStoreError

    outputs = tmp_path / "agents/single/outputs"
    outputs.mkdir(parents=True)
    xr.Dataset({"x": ("sample", [1.])}).to_netcdf(outputs / "data.nc")
    store = TaskResultStore(task_workspaces=Projector(tmp_path))
    record, = store.list(task_id="task")
    router = SimpleNamespace(task_results=store, _task_in_workspace=lambda *_: None,
                             _workspace_id=lambda _: "workspace")
    request = SimpleNamespace(context=SimpleNamespace(task_id="task"),
                              payload=SimpleNamespace(result_ref=record.ref, file_name="data.nc", purpose=purpose))
    with pytest.raises(RequestStoreError, match="preview only, not download"):
        await OceanRequestRouter._task_result_resource_grant(router, None, request)
