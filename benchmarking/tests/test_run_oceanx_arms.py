"""Arms: a frozen library copied into each attempt, recorded and checked; no backend or model."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import run_oceanx

FIXTURE = Path(__file__).parent / "fixtures"
FILES = ("lessons.json", "tools.json")


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    folder = tmp_path / "L1"
    folder.mkdir()
    for name in FILES:
        (folder / name).write_text((FIXTURE / name).read_text())
    monkeypatch.setattr(run_oceanx, "LIBRARY", folder)
    return folder


def test_the_library_is_installed_into_the_attempt_state(tmp_path, snapshot):
    attempt = tmp_path / "out" / "Q01" / "attempt-1"
    record = run_oceanx.install_library(attempt)
    research = attempt / "state" / "research"
    assert (research / "lessons" / "lessons.json").read_text() == (snapshot / "lessons.json").read_text()
    assert (research / "tools" / "tools.json").read_text() == (snapshot / "tools.json").read_text()
    assert record == {"snapshot": str(snapshot), "sha256_before": {
        name: run_oceanx.file_sha256(snapshot / name) for name in FILES}}
    # What the attempt's agents will read: each lesson in the region of its skill, retired ones nowhere.
    project = run_oceanx.project_library(attempt / "state")
    skills = project.skills(research=True)
    planning = skills["research-trajectory-planning"]
    assert planning.rstrip().endswith("(L001)") and "Learned from past OceanX tasks" in planning
    physics = skills["ocean-physical-consistency-review"]
    assert (physics.index("The existence of additional possible checks") < physics.index("(L002)")
            < physics.index("## relevant_references"))
    assert all("(L003)" not in text and "oceanx:" not in text for text in skills.values())
    # The tools of the snapshot: the learned function is listed and importable, the unused one is not listed.
    helpers = skills["xarray-array-ops"]
    assert "- `ao.anomaly(array, baseline, *, dim)`: Difference between" in helpers
    assert "small_sample" not in helpers
    module = project.tools.module_source()
    assert "def anomaly(array, baseline, *, dim)" in module and "def small_sample(" in module
    # The skills are also exported for reading.
    assert (research / "lessons" / "skills" / "research-trajectory-planning" / "SKILL.md").read_text() == planning


def test_the_library_version_matches_oceanx_and_ignores_the_folder_name(tmp_path, snapshot):
    from oceanx.research.review import ProjectResearch
    project = ProjectResearch(SimpleNamespace(root=tmp_path / "elsewhere"))
    project.install(snapshot)
    expected = project.version()
    assert expected.startswith("lessons@") and "+tools@" in expected
    assert run_oceanx.snapshot_version(snapshot) == expected
    # A snapshot of lessons only, as made before tools were learned, is a different library.
    (snapshot / "tools.json").unlink()
    assert run_oceanx.snapshot_version(snapshot) == expected.split("+")[0]


def test_a_snapshot_freezes_what_the_evolution_project_learned(tmp_path, snapshot):
    from oceanx.research.review import ProjectResearch
    project = ProjectResearch(SimpleNamespace(root=tmp_path / "evolution" / ".oceanx"))
    project.install(snapshot)
    project.mark("lesson", "L002", "wrong", reviewer="owner")
    record = project.snapshot(tmp_path / "L2")
    assert record["version"] == project.version() == run_oceanx.snapshot_version(tmp_path / "L2")
    assert record["lessons"] == ["L001"] and "anomaly" in record["tools"] and "small_sample" not in record["tools"]
    assert record["sha256"] == {name: run_oceanx.file_sha256(tmp_path / "L2" / name) for name in FILES}
    assert json.loads((tmp_path / "L2" / "snapshot.json").read_text()) == record
    # The change log travels with the snapshot: it says how the library came about.
    [change] = [json.loads(line) for line in (tmp_path / "L2" / "lessons-changes.jsonl").read_text().splitlines()]
    assert (change["lesson"], change["change"], change["by"]) == ("L002", "retired", "owner")
    with pytest.raises(ValueError, match="never edited"):
        project.snapshot(tmp_path / "L2")


def test_an_attempt_records_whether_its_library_changed(tmp_path, snapshot):
    attempt = tmp_path / "out" / "Q01" / "attempt-1"
    before = run_oceanx.install_library(attempt)["sha256_before"]
    project = run_oceanx.project_library(attempt / "state")
    assert project.library_hashes() == before
    project.mark("tool", "anomaly", "wrong", reviewer="someone")
    after = project.library_hashes()
    assert after["lessons.json"] == before["lessons.json"] and after["tools.json"] != before["tools.json"]
    # An arm without tools: a tools file that appears during the run is a change too.
    (snapshot / "tools.json").unlink()
    lessons_only = run_oceanx.install_library(tmp_path / "out" / "Q02" / "attempt-1")["sha256_before"]
    assert lessons_only["tools.json"] is None


def test_arm_record_written_once_and_resume_must_match(tmp_path, monkeypatch):
    monkeypatch.setattr(run_oceanx, "ARM", {"arm": "B", "policy": "v2-nested", "library": None, "commit": "c"})
    attempt = tmp_path / "out" / "Q01" / "attempt-1"
    attempt.mkdir(parents=True)
    run_oceanx.write_arm(attempt)
    written = json.loads((tmp_path / "out" / "arm.json").read_text())
    assert written["arm"] == "B" and "started_utc" in written
    run_oceanx.check_arm(tmp_path / "out")
    monkeypatch.setattr(run_oceanx, "ARM", {"arm": "C", "policy": "v2-nested", "library": {"version": "x"}})
    with pytest.raises(SystemExit):
        run_oceanx.check_arm(tmp_path / "out")


def test_arm_record_names_the_policy_and_the_library(snapshot, monkeypatch):
    monkeypatch.setattr(run_oceanx, "git_identity", lambda: {"commit": "c", "dirty": False})
    monkeypatch.delenv("OCEANX_RESEARCH_POLICY", raising=False)
    record = run_oceanx.arm_record(SimpleNamespace(arm="C1", queries=None))
    assert record["policy"] == "v2-nested"  # nothing passed: the default policy, by name
    assert record["library"] == {"snapshot": str(snapshot), "version": run_oceanx.snapshot_version(snapshot),
                                 "sha256": {name: run_oceanx.file_sha256(snapshot / name) for name in FILES}}
    monkeypatch.setattr(run_oceanx, "LIBRARY", None)
    assert run_oceanx.arm_record(SimpleNamespace(arm="B", queries=None))["library"] is None
    # --policy sets the environment for every backend subprocess; the record follows it.
    monkeypatch.setenv("OCEANX_RESEARCH_POLICY", "v0-coordinator-bfs")
    assert run_oceanx.arm_record(SimpleNamespace(arm="paired", queries=None))["policy"] == "v0-coordinator-bfs"
