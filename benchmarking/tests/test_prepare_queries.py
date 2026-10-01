"""Shared data root to the real OceanX query schema; no model or download calls."""
import json

import download_data as download
import prepare_queries as prepare
import pytest

from oceanx.batch import load_queries


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "shared"
    control = root / "_download_all"
    control.mkdir(parents=True)
    manifest = json.loads(prepare.MANIFEST.read_text())
    for key, group in manifest["groups"].items():
        # Path-only fixtures; this test makes no scientific-data validity claim.
        base = root / "_evaluator_only" if group.get("evaluator_only") else root
        for folder in group["folders"]:
            target = base / group["data_type"] / folder / "2011" / "test.nc"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"path fixture")
        download.write_json(control / f"{key}.report.json", {
            "group_sha256": download.fingerprint(group), "complete": True,
            "completed_files": 1, "expected_files": 1,
        })
    download.write_json(control / "coverage.json", {
        "catalogue": manifest["version"],
        "tasks": {task: {"numerical_inputs_complete": True, "missing_groups": []} for task in manifest["tasks"]},
    })
    return root


@pytest.mark.parametrize("suite,count", [("test", 30), ("evolution", 24)])
def test_suite_produces_loadable_cases_without_data_copy(archive, tmp_path, suite, count):
    output = tmp_path / f"inputs/{suite}.jsonl"
    before = sorted(p.relative_to(archive) for p in archive.rglob("*.nc"))
    assert prepare.main(["--data-root", str(archive), "--suite", suite, "--output", str(output)]) == 0
    cases = load_queries(output)
    assert len(cases) == count
    for case in cases:
        original = json.loads(prepare.task_file(case.id).read_text())
        assert case.query == original["query"] and case.workflow_mode == "research"
        assert all(p.is_dir() and p.is_relative_to(archive.resolve()) for p in case.datasets)
        assert not any("_evaluator_only" in p.parts for p in case.datasets)
        diagnostics = {p.name for p in case.datasets if "CMOMS_DIA" in p.parts}
        assert diagnostics == {"Q14": {"P_Production", "NO3_uptake"},
                               "Q16": {"CO2_airsea", "pCO2"}}.get(case.id, set())
    assert sorted(p.relative_to(archive) for p in archive.rglob("*.nc")) == before
    assert not list(output.parent.rglob("*.nc"))


def test_subset_and_wrong_suite(archive, tmp_path):
    output = tmp_path / "subset.jsonl"
    assert prepare.main(["--data-root", str(archive), "--suite", "test", "--tasks", "Q09", "Q22",
                         "--output", str(output)]) == 0
    assert [c.id for c in load_queries(output)] == ["Q09", "Q22"]
    with pytest.raises(ValueError, match="evolution suite"):
        prepare.main(["--data-root", str(archive), "--suite", "evolution", "--tasks", "Q01",
                      "--output", str(tmp_path / "x.jsonl")])


def test_each_evolution_set_is_prepared_on_its_own(archive, tmp_path):
    for name, expected in (("A", [f"E{i:02}" for i in range(1, 13)]),
                           ("B", [f"E{i:02}" for i in range(13, 25)])):
        output = tmp_path / f"set-{name}.jsonl"
        assert prepare.main(["--data-root", str(archive), "--suite", "evolution", "--set", name,
                             "--output", str(output)]) == 0
        assert [case.id for case in load_queries(output)] == expected
    with pytest.raises(ValueError, match="evolution suite only"):
        prepare.main(["--data-root", str(archive), "--suite", "test", "--set", "A",
                      "--output", str(tmp_path / "x.jsonl")])
    with pytest.raises(ValueError, match="evolution suite"):
        prepare.main(["--data-root", str(archive), "--suite", "evolution", "--set", "A", "--tasks", "E13",
                      "--output", str(tmp_path / "y.jsonl")])


@pytest.mark.parametrize("task,group", [("Q14", "C_PRODUCTION"), ("Q16", "C_CARBON")])
def test_missing_requested_diagnostics_prevent_query_preparation(archive, tmp_path, task, group):
    path = archive / "_download_all" / f"{group}.report.json"
    report = json.loads(path.read_text())
    report["complete"] = False
    download.write_json(path, report)
    output = tmp_path / "blocked.jsonl"
    with pytest.raises(ValueError, match=group):
        prepare.main(["--data-root", str(archive), "--suite", "test", "--tasks", task,
                      "--output", str(output)])
    assert not output.exists()


@pytest.mark.parametrize("fault", ["old_version", "incomplete", "missing_report", "empty_data", "task_incomplete"])
def test_rejects_bad_archive_before_writing(archive, tmp_path, fault):
    control = archive / "_download_all"
    if fault == "old_version":
        doc = json.loads((control / "coverage.json").read_text())
        doc["catalogue"] = "old"
        download.write_json(control / "coverage.json", doc)
    elif fault == "incomplete":
        doc = json.loads((control / "C_CORE.report.json").read_text())
        doc["complete"] = False
        download.write_json(control / "C_CORE.report.json", doc)
    elif fault == "missing_report":
        (control / "C_CORE.report.json").unlink()
    elif fault == "empty_data":
        (archive / "CMOMS/temp/2011/test.nc").unlink()
    else:
        doc = json.loads((control / "coverage.json").read_text())
        doc["tasks"]["Q22"]["numerical_inputs_complete"] = False
        download.write_json(control / "coverage.json", doc)
    output = tmp_path / "blocked.jsonl"
    with pytest.raises((ValueError, OSError)):
        prepare.main(["--data-root", str(archive), "--suite", "test", "--output", str(output)])
    assert not output.exists()


@pytest.mark.parametrize("path", ["_evaluator_only/CMOMS_DIA/temp_rate", "evaluator", "rubric.json"])
def test_evaluator_material_is_never_an_agent_input(archive, tmp_path, path):
    target = archive / path
    if not target.exists():
        target.mkdir(parents=True) if "." not in path else target.write_text("{}")
        if target.is_dir():
            (target / "x.nc").write_bytes(b"x")
    bindings = tmp_path / "bindings.json"
    bindings.write_text(json.dumps({"Q01": {"datasets": ["CMOMS/temp", path]}}))
    with pytest.raises(ValueError, match="[Ee]valuator"):
        prepare.main(["--data-root", str(archive), "--suite", "test", "--tasks", "Q01",
                      "--bindings", str(bindings), "--output", str(tmp_path / "blocked.jsonl")])


def test_output_must_stay_outside_the_data_root(archive):
    with pytest.raises(ValueError, match="outside"):
        prepare.main(["--data-root", str(archive), "--suite", "test", "--tasks", "Q01",
                      "--output", str(archive / "inputs.jsonl")])
