"""An Expert is told what the folders it continues from already hold, without opening them."""

import asyncio
import contextlib
import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
import xarray as xr
from langchain_core.callbacks import BaseCallbackHandler

from oceanx import analysis_probe, expert_execution
from oceanx.backend.host import OceanBackendHost
from oceanx.context import ModelDataDisclosurePolicy, OceanContextBuilder
from oceanx.expert_execution import ExpertCodeExecutionError
from oceanx.research import graphs
from oceanx.research.services import AgentRun
from oceanx.sandbox import SandboxUnavailableError
from tests.test_oceanx.test_dataset_import_router import _open_workspace


def _netcdf(path: Path, **attrs) -> None:
    xr.Dataset(
        {"mld": (("time", "lat"), np.zeros((12, 3)), {"units": "m", "long_name": "mixed layer depth"}),
         "plain": (("time",), np.zeros(12))},
        attrs=attrs,
    ).to_netcdf(path)


def _touch(path: Path, age: int) -> None:
    """Set a file's modification time ``age`` seconds in the past, so the order is not a race."""
    stamp = 1_700_000_000 - age
    os.utime(path, (stamp, stamp))


def test_the_probe_describes_netcdf_csv_and_npz_files_in_one_folder(tmp_path):
    _netcdf(tmp_path / "mld.nc", title="Annual MLD")
    (tmp_path / "table.csv").write_text("year,mld_mean\n2000,10\n2001,11")  # no final newline
    np.savez(tmp_path / "arrays.npz", x=np.zeros((4, 5), dtype="float32"), flag=np.ones(3, dtype=bool),
             labels=np.array([{"a": 1}], dtype=object))
    (tmp_path / "broken.nc").write_text("not netcdf")
    (tmp_path / "notes.txt").write_text("not data")

    described = {name: analysis_probe.describe_saved_file(tmp_path / name) for name in (
        "mld.nc", "table.csv", "arrays.npz", "broken.nc", "notes.txt")}

    assert described["mld.nc"] == {
        "inspection": "ready", "kind": "array", "dimensions": {"time": 12, "lat": 3},
        "variables": [
            {"name": "mld", "dims": ["time", "lat"], "units": "m", "long_name": "mixed layer depth"},
            {"name": "plain", "dims": ["time"]},
        ],
        "variable_count": 2, "title": "Annual MLD",
    }
    assert described["table.csv"] == {"inspection": "ready", "kind": "table",
                                      "columns": ["year", "mld_mean"], "column_count": 2, "rows": 2}
    assert described["arrays.npz"] == {"inspection": "ready", "kind": "arrays", "array_count": 3, "arrays": [
        {"name": "x", "shape": [4, 5], "dtype": "float32"},
        {"name": "flag", "shape": [3], "dtype": "bool"},
        {"name": "labels", "shape": [1], "dtype": "object", "needs_allow_pickle": True},
    ]}
    assert described["broken.nc"]["inspection"] == "unavailable" and described["broken.nc"]["error"]
    assert described["notes.txt"] == {"inspection": "not_a_dataset"}


def test_an_npz_is_described_from_its_headers_without_loading_an_array(tmp_path, monkeypatch):
    np.savez(tmp_path / "big.npz", field=np.zeros((50, 60, 70)))

    def refuse(*_args, **_kwargs):
        raise AssertionError("an array was loaded")

    monkeypatch.setattr(np, "load", refuse)
    assert analysis_probe.describe_saved_file(tmp_path / "big.npz")["arrays"] == [
        {"name": "field", "shape": [50, 60, 70], "dtype": "float64"}]


def test_csv_rows_count_records_not_newlines_inside_quoted_fields(tmp_path):
    path = tmp_path / "notes.csv"
    path.write_text('year,note\n2020,"first line\nsecond line"\n\n2021,last')
    assert analysis_probe.describe_saved_file(path)["rows"] == 2


def test_large_csv_keeps_columns_without_scanning_rows(tmp_path, monkeypatch):
    path = tmp_path / "large.csv"
    path.write_text("year,note\n2020,first\n2021,last\n")
    monkeypatch.setattr(analysis_probe, "_SAVED_CSV_ROW_MAX_BYTES", 16, raising=False)

    def refuse(_path):
        raise AssertionError("Large CSV rows must not be scanned")

    monkeypatch.setattr(analysis_probe, "_data_rows", refuse)
    described = analysis_probe.describe_saved_file(path)
    assert described == {"inspection": "ready", "kind": "table",
                         "columns": ["year", "note"], "column_count": 2}
    line = graphs._saved_file_line({"path": "outputs/large.csv", **described})
    assert line == "outputs/large.csv: rows not counted; columns year, note"


def test_csv_with_non_utf8_data_still_has_columns_and_rows(tmp_path):
    path = tmp_path / "legacy.csv"
    path.write_bytes(b'year,note\n2020,"first\n\xffline"\n2021,last\n')
    assert analysis_probe.describe_saved_file(path) == {
        "inspection": "ready", "kind": "table", "columns": ["year", "note"],
        "column_count": 2, "rows": 2}


def test_the_probe_script_answers_a_request_for_files_and_one_bad_file_hides_nothing(tmp_path, monkeypatch):
    _netcdf(tmp_path / "ok.nc")
    (tmp_path / "bad.csv").write_bytes(b"")
    request, answer = tmp_path / "input.json", tmp_path / "output.json"
    request.write_text(json.dumps({"files": [
        {"key": "outputs/ok.nc", "path": str(tmp_path / "ok.nc")},
        {"key": "scratch/bad.csv", "path": str(tmp_path / "bad.csv")},
    ]}))
    monkeypatch.setattr(sys, "argv", ["analysis_probe.py", str(request), str(answer)])
    analysis_probe.main()
    files = {item["key"]: item for item in json.loads(answer.read_text())["files"]}
    assert files["outputs/ok.nc"]["inspection"] == "ready"
    assert files["scratch/bad.csv"]["inspection"] == "unavailable"


@contextlib.asynccontextmanager
async def _backend(tmp_path, monkeypatch):
    """A real backend host with one task; building an Expert prompt is captured, not run."""
    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _: None)
    try:
        _client, _recorder, context = await _open_workspace(host, workspace)
        task = host.store.create_research_task(workspace_id=context["workspace_id"], title="Saved data")
        monkeypatch.setattr(graphs, "host", lambda: host)
        monkeypatch.setattr(graphs, "load_model_profile", lambda _: SimpleNamespace(provider="openai"))
        monkeypatch.setattr("oceanx.research.metering.CallMeter", lambda *args: BaseCallbackHandler())
        seen = {}

        async def capture(**kwargs):
            seen.update(kwargs)
            return SimpleNamespace(with_config=lambda **_: "graph")

        monkeypatch.setattr(graphs, "build_deep_agent_graph", capture)
        config = {"configurable": {
            "workspace_id": context["workspace_id"], "workspace_path": str(workspace),
            "task_id": task.task_id, "thread_id": "saved_data", "request_id": "req_saved",
            "ls_agent_type": "subagent",
        }}
        yield host, task, config, seen
    finally:
        await host.close()


def _fill(root: Path) -> None:
    """outputs: table.csv (older), mld.nc (newer); scratch: arrays.npz (newest), old.csv; plus noise."""
    outputs, scratch = root / "outputs", root / "scratch"
    _netcdf(outputs / "mld.nc", title="Annual MLD")
    (outputs / "table.csv").write_text("year,mld_mean\n2000,10\n2001,11\n")
    np.savez(scratch / "arrays.npz", x=np.zeros((2, 3)))
    (scratch / "old.csv").write_text("a\n1\n")
    (scratch / "notes.txt").write_text("not data")
    (scratch / "link.csv").symlink_to(outputs / "table.csv")  # never followed
    for path, age in ((outputs / "table.csv", 400), (outputs / "mld.nc", 300),
                      (scratch / "arrays.npz", 100), (scratch / "old.csv", 200)):
        _touch(path, age)


@pytest.mark.asyncio
async def test_the_service_lists_outputs_first_then_the_newest_scratch_and_counts_the_rest(tmp_path, monkeypatch):
    async with _backend(tmp_path, monkeypatch) as (host, task, _config, _seen):
        root = host.task_workspace_projector.expert_session_root(task.task_id, "ocean-process-a")
        _fill(root)
        service = host.expert_code_execution
        index = await service.describe_saved_data(task_id=task.task_id, agent_thread_id="ocean-process-a")
        assert [item["path"] for item in index["files"]] == [
            "outputs/mld.nc", "outputs/table.csv", "scratch/arrays.npz", "scratch/old.csv"]
        assert index["omitted"] == 0
        assert index["files"][0]["title"] == "Annual MLD" and index["files"][1]["rows"] == 2
        assert index["files"][2]["arrays"][0]["shape"] == [2, 3]
        # Only the first `limit` files are described; the others are only counted.
        limited = await service.describe_saved_data(
            task_id=task.task_id, agent_thread_id="ocean-process-a", limit=3)
        assert [item["path"] for item in limited["files"]] == [
            "outputs/mld.nc", "outputs/table.csv", "scratch/arrays.npz"]
        assert limited["omitted"] == 1


@pytest.mark.asyncio
async def test_an_unchanged_folder_is_not_probed_again_and_a_changed_file_is_probed_alone(tmp_path, monkeypatch):
    probed = []
    real = expert_execution.run_sandboxed_command

    async def spy(command, **kwargs):
        probed.append([item["key"] for item in json.loads(Path(command[2]).read_text())["files"]])
        return await real(command, **kwargs)

    monkeypatch.setattr(expert_execution, "run_sandboxed_command", spy)
    async with _backend(tmp_path, monkeypatch) as (host, task, _config, _seen):
        root = host.task_workspace_projector.expert_session_root(task.task_id, "ocean-process-a")
        _fill(root)
        ask = lambda: host.expert_code_execution.describe_saved_data(
            task_id=task.task_id, agent_thread_id="ocean-process-a")
        first = await ask()
        assert len(probed) == 1 and sorted(probed[0]) == sorted(item["path"] for item in first["files"])
        cache = json.loads((root / ".runtime" / "data-index.json").read_text())
        assert cache["schema_version"] == "ocean-saved-data-index/v1"
        assert set(cache["files"]) == {item["path"] for item in first["files"]}
        assert await ask() == first and len(probed) == 1  # the cache is reused

        (root / "outputs" / "table.csv").write_text("year,mld_mean,mld_std\n2000,10,1\n")
        (root / "scratch" / "arrays.npz").unlink()
        changed = await ask()
        assert probed[1] == ["outputs/table.csv"]  # only the changed file went to the probe
        assert next(item for item in changed["files"] if item["path"] == "outputs/table.csv")["column_count"] == 3
        assert "scratch/arrays.npz" not in {item["path"] for item in changed["files"]}
        assert "scratch/arrays.npz" not in json.loads(
            (root / ".runtime" / "data-index.json").read_text())["files"]  # a vanished file is dropped


@pytest.mark.asyncio
async def test_a_file_that_cannot_be_read_is_described_once_and_the_cache_survives_bad_content(tmp_path, monkeypatch):
    probed = []
    real = expert_execution.run_sandboxed_command

    async def spy(command, **kwargs):
        probed.append(1)
        return await real(command, **kwargs)

    monkeypatch.setattr(expert_execution, "run_sandboxed_command", spy)
    async with _backend(tmp_path, monkeypatch) as (host, task, _config, _seen):
        root = host.task_workspace_projector.expert_session_root(task.task_id, "ocean-process-a")
        (root / "outputs" / "broken.nc").write_text("not netcdf")
        ask = lambda: host.expert_code_execution.describe_saved_data(
            task_id=task.task_id, agent_thread_id="ocean-process-a")
        first = await ask()
        assert first["files"][0]["inspection"] == "unavailable"
        await ask()
        assert len(probed) == 1  # the same unreadable file is not tried again
        (root / ".runtime" / "data-index.json").write_text("{not json")  # a damaged cache is rebuilt
        assert (await ask())["files"][0]["inspection"] == "unavailable" and len(probed) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("remove_all", [False, True])
async def test_deleted_files_leave_the_cache_even_when_no_file_needs_reprobing(tmp_path, monkeypatch, remove_all):
    async with _backend(tmp_path, monkeypatch) as (host, task, _config, _seen):
        root = host.task_workspace_projector.expert_session_root(task.task_id, "ocean-process-a")
        _fill(root)
        service = host.expert_code_execution
        first = await service.describe_saved_data(task_id=task.task_id, agent_thread_id="ocean-process-a")
        removed = first["files"] if remove_all else first["files"][:1]
        for item in removed:
            (root / item["path"]).unlink()

        async def refuse(*_args, **_kwargs):
            pytest.fail("unchanged remaining files must not be probed again")

        monkeypatch.setattr(service, "_probe_saved_files", refuse)
        result = await service.describe_saved_data(task_id=task.task_id, agent_thread_id="ocean-process-a")
        expected = {item["path"] for item in first["files"]} - {item["path"] for item in removed}
        assert {item["path"] for item in result["files"]} == expected
        assert set(json.loads((root / ".runtime" / "data-index.json").read_text())["files"]) == expected


@pytest.mark.asyncio
async def test_a_probe_that_cannot_run_raises_and_caches_nothing(tmp_path, monkeypatch):
    async def unavailable(command, **kwargs):
        raise SandboxUnavailableError("no sandbox")

    monkeypatch.setattr(expert_execution, "run_sandboxed_command", unavailable)
    async with _backend(tmp_path, monkeypatch) as (host, task, _config, _seen):
        root = host.task_workspace_projector.expert_session_root(task.task_id, "ocean-process-a")
        _fill(root)
        with pytest.raises(ExpertCodeExecutionError, match="could not run"):
            await host.expert_code_execution.describe_saved_data(
                task_id=task.task_id, agent_thread_id="ocean-process-a")
        assert not (root / ".runtime" / "data-index.json").exists()
        # A folder with no data files needs no probe at all.
        empty = host.task_workspace_projector.expert_session_root(task.task_id, "ocean-process-empty")
        assert await host.expert_code_execution.describe_saved_data(
            task_id=task.task_id, agent_thread_id="ocean-process-empty") == {"files": [], "omitted": 0}
        assert not (empty / ".runtime" / "data-index.json").exists()


def test_a_file_line_names_what_it_holds_in_few_words():
    array = {"path": "outputs/mld.nc", "inspection": "ready", "kind": "array", "title": "Annual MLD",
             "dimensions": {"time": 12, "lat": 3}, "variable_count": 2,
             "variables": [{"name": "mld", "dims": ["time", "lat"], "units": "m", "long_name": "mixed layer depth"},
                           {"name": "plain", "dims": ["time"]}]}
    assert graphs._saved_file_line(array) == (
        'outputs/mld.nc ("Annual MLD"): mld(time=12, lat=3) [m] "mixed layer depth"; plain(time=12)')
    table = {"path": "outputs/t.csv", "inspection": "ready", "kind": "table", "rows": 1240,
             "columns": ["year", "mld_mean"], "column_count": 2}
    assert graphs._saved_file_line(table) == "outputs/t.csv: 1,240 rows; columns year, mld_mean"
    arrays = {"path": "scratch/z.npz", "inspection": "ready", "kind": "arrays", "array_count": 2, "arrays": [
        {"name": "x", "shape": [4, 5], "dtype": "float32"},
        {"name": "labels", "shape": [1], "dtype": "object", "needs_allow_pickle": True}]}
    assert graphs._saved_file_line(arrays) == (
        "scratch/z.npz: x float32 (4, 5); labels object (1,) (needs allow_pickle)")
    assert graphs._saved_file_line({"path": "outputs/bad.nc", "inspection": "unavailable",
                                    "error": "ValueError: bad"}) == "outputs/bad.nc: could not be read (ValueError: bad)"


def test_a_long_file_line_is_cut_to_its_limit_and_counts_what_it_leaves_out():
    variables = [{"name": f"variable_{number}", "dims": ["time", "lat", "lon"], "units": "degC",
                  "long_name": "a long descriptive name " + "x" * 30} for number in range(30)]
    entry = {"path": "outputs/many.nc", "inspection": "ready", "kind": "array", "variables": variables,
             "variable_count": 40, "dimensions": {"time": 12, "lat": 90, "lon": 180}}
    line = graphs._saved_file_line(entry)
    assert len(line) <= graphs.SAVED_DATA_FILE_CHARS and line.startswith("outputs/many.nc: variable_0(")
    hidden = int(line.rsplit("+", 1)[1].split()[0])
    assert line.count("variable_") + hidden == 40  # every variable is either named or counted
    huge = {"path": "outputs/h.nc", "inspection": "ready", "kind": "array", "dimensions": {},
            "variables": [{"name": "v" * 400, "dims": []}], "variable_count": 1}
    assert len(graphs._saved_file_line(huge)) <= graphs.SAVED_DATA_FILE_CHARS


def _listing(folders: int, files: int, omitted: int = 0):
    entry = lambda n: {"path": f"outputs/file_{n}.csv", "inspection": "ready", "kind": "table",
                       "rows": 10, "columns": [f"column_{n}_{i}" for i in range(40)], "column_count": 40}
    return [(Path(f"/task/agents/ocean-process-{k}"), {"files": [entry(n) for n in range(files)],
                                                       "omitted": omitted}) for k in range(folders)]


def test_the_listing_in_a_prompt_keeps_its_limits_and_counts_what_it_leaves_out():
    one = graphs._saved_data_block(_listing(1, 12))
    assert one.startswith("Saved data in those folders") and one.count("outputs/file_") == 12
    assert "more files not listed" not in one and len(one) <= graphs.SAVED_DATA_TOTAL_CHARS
    # More files than a folder lists: the service says how many it did not describe.
    assert "  (+30 more files not listed)\n" in graphs._saved_data_block(_listing(1, 12, omitted=30))
    # Even a service that returned too many files cannot make a folder list more than twelve.
    thirty = graphs._saved_data_block(_listing(1, 30))
    assert thirty.count("outputs/file_") == graphs.SAVED_DATA_FILES
    assert "  (+18 more files not listed)\n" in thirty
    # Many folders: the total stays within the budget, and the folders left out are counted.
    many = graphs._saved_data_block(_listing(8, 12))
    assert len(many) <= graphs.SAVED_DATA_TOTAL_CHARS
    assert many.splitlines()[-1].startswith("(+") and "more folders not listed)" in many.splitlines()[-1]
    shown = many.count("/task/agents/ocean-process-")
    assert shown + int(many.splitlines()[-1].split("+")[1].split()[0]) == 8
    for line in many.splitlines():
        if line.startswith("  outputs/"):
            assert len(line) <= graphs.SAVED_DATA_FILE_CHARS + 2
    assert graphs._saved_data_block([]) == "" and graphs._saved_data_block(
        [(Path("/task/agents/a"), {"files": [], "omitted": 0})]) == ""


@pytest.mark.asyncio
async def test_a_repeat_attempt_is_shown_what_its_own_folder_holds(tmp_path, monkeypatch):
    async with _backend(tmp_path, monkeypatch) as (host, task, config, seen):
        run = AgentRun.from_config(config, "ocean_process_expert", question="B1: saved data")
        root = host.task_workspace_projector.expert_session_root(task.task_id, run.thread_id)
        assert "Saved data in those folders" not in (await _prompt(config, run, seen))  # a first attempt
        _fill(root)
        prompt = await _prompt(config, run, seen)
        assert "Saved data in those folders (outputs first, then the newest scratch files):" in prompt
        assert f"{root}:\n  outputs/mld.nc (\"Annual MLD\"): mld(time=12, lat=3) [m] \"mixed layer depth\"" in prompt
        assert "  outputs/table.csv: 2 rows; columns year, mld_mean\n" in prompt
        assert "scratch/arrays.npz: x float64 (2, 3)" in prompt and "notes.txt" not in prompt
        assert "Give every variable you save `units` and `long_name` attributes" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["deny", "prompt"])
@pytest.mark.parametrize("delivery", ["interactive", "static"])
@pytest.mark.parametrize("workflow", ["research", "standard"])
async def test_saved_data_listing_respects_metadata_disclosure_before_probe_or_cache(
    tmp_path, monkeypatch, decision, delivery, workflow,
):
    monkeypatch.setenv("OCEANX_FIGURE_DELIVERY", delivery)
    async with _backend(tmp_path, monkeypatch) as (host, task, config, seen):
        c = config["configurable"]
        c["request_options"] = {"workflow_mode": workflow}
        run = AgentRun.from_config(config, "ocean_process_expert", question="B1: saved data privacy")
        root = host.task_workspace_projector.expert_session_root(task.task_id, run.thread_id)
        _fill(root)
        builder = OceanContextBuilder(store=host.store, paths=host.paths)
        provider = graphs.services(config, run.role, run).provider_id
        probe = AsyncMock(wraps=host.expert_code_execution.describe_saved_data)
        monkeypatch.setattr(host.expert_code_execution, "describe_saved_data", probe)
        cache = root / ".runtime/data-index.json"

        def set_metadata(value):
            builder.set_policy(workspace_id=c["workspace_id"], policy=ModelDataDisclosurePolicy(
                provider_id=provider, policy_version=1, metadata=value))

        set_metadata(decision)
        denied = await _prompt(config, run, seen)
        probe.assert_not_called()
        assert not cache.exists()
        assert "Saved data in those folders" not in denied
        assert "Annual MLD" not in denied and "mld(time=12, lat=3)" not in denied
        assert "An earlier attempt at this question left files in" in denied
        assert str(root / "scratch") in denied and str(root / "outputs") in denied

        set_metadata("allow")
        allowed = await _prompt(config, run, seen)
        probe.assert_awaited_once()
        assert "Saved data in those folders" in allowed
        assert 'outputs/mld.nc ("Annual MLD"): mld(time=12, lat=3) [m]' in allowed
        assert cache.is_file()
        previous_cache = cache.read_bytes()

        # Revocation must also bypass a previously populated cache, not just the probe script.
        probe.reset_mock()
        set_metadata(decision)
        revoked = await _prompt(config, run, seen)
        probe.assert_not_called()
        assert "Saved data in those folders" not in revoked and "Annual MLD" not in revoked
        assert cache.read_bytes() == previous_cache  # existing local cache need not be deleted


async def _prompt(config, run, seen) -> str:
    await graphs.build(config, run.role, run=run)
    return seen["system_prompt"]


@pytest.mark.asyncio
async def test_a_failed_check_leaves_the_folder_paths_and_never_stops_an_expert_starting(
        tmp_path, monkeypatch, caplog):
    async with _backend(tmp_path, monkeypatch) as (host, task, config, seen):
        run = AgentRun.from_config(config, "ocean_process_expert", question="B1: saved data")
        _fill(host.task_workspace_projector.expert_session_root(task.task_id, run.thread_id))

        async def fails(**_kwargs):
            raise ExpertCodeExecutionError("the probe broke")

        async def hangs(**_kwargs):
            await asyncio.sleep(60)

        for broken, expected in ((fails, "the probe broke"), (hangs, "TimeoutError")):
            monkeypatch.setattr(host.expert_code_execution, "describe_saved_data", broken)
            monkeypatch.setattr(graphs, "SAVED_DATA_TIMEOUT_SECONDS", 0.05)
            caplog.clear()
            with caplog.at_level(logging.WARNING, logger=graphs._LOGGER.name):
                prompt = await _prompt(config, run, seen)
            assert "Saved data in those folders" not in prompt
            assert "An earlier attempt at this question left files in" in prompt  # the path hint remains
            assert any("Could not describe the saved data" in line and expected in line
                       for line in caplog.messages), caplog.messages


@pytest.mark.asyncio
async def test_earlier_nodes_are_listed_nearest_first_with_their_saved_files(tmp_path, monkeypatch):
    async with _backend(tmp_path, monkeypatch) as (host, task, _config, _seen):
        attempts = {"B1.3": [{"agent_key": "ocean-process-old"}, {"agent_key": "ocean-process-new"}],
                    "B1": [{"agent_key": "statistics-b1"}, {"agent_key": "coordinator"}]}
        tree = SimpleNamespace(document=lambda: {"nodes": {"B1.3.1": {"dependencies": []}}},
                               attempts=lambda node: attempts.get(node, []))
        monkeypatch.setattr(graphs, "research_tree", lambda _task: tree)
        root = host.task_workspace_projector.expert_session_root
        for key in ("ocean-process-old", "ocean-process-new", "statistics-b1"):
            root(task.task_id, key)
        (root(task.task_id, "ocean-process-new") / "outputs" / "new.csv").write_text("a,b\n1,2\n")
        (root(task.task_id, "statistics-b1") / "outputs" / "b1.csv").write_text("c\n1\n")
        run = AgentRun("ws", task.task_id, "request", "ocean-process-own", "server",
                       "ocean_process_expert", question="B1.3.1: test the depth", node_id="B1.3.1")
        text = await graphs._saved_data_prompt(run, own=False)
        new, b1 = f"{root(task.task_id, 'ocean-process-new')}:", f"{root(task.task_id, 'statistics-b1')}:"
        assert text.index(new) < text.index("outputs/new.csv") < text.index(b1) < text.index("outputs/b1.csv")
        assert "ocean-process-old" not in text  # nothing saved there, so nothing listed
        assert len(text) <= graphs.SAVED_DATA_TOTAL_CHARS
