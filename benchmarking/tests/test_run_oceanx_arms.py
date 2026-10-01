"""Arms: frozen lessons copied into each attempt, recorded and checked; no backend or model."""
import json
from pathlib import Path

import pytest
import run_oceanx

FIXTURE = Path(__file__).parent / "fixtures"


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    folder = tmp_path / "L1"
    folder.mkdir()
    (folder / "lessons.json").write_text((FIXTURE / "lessons.json").read_text())
    monkeypatch.setattr(run_oceanx, "LESSONS", folder)
    return folder


def test_lessons_are_installed_into_the_attempt_state(tmp_path, snapshot):
    attempt = tmp_path / "out" / "Q01" / "attempt-1"
    record = run_oceanx.install_lessons(attempt)
    installed = attempt / "state" / "research" / "lessons"
    assert json.loads((installed / "lessons.json").read_text()) == json.loads((snapshot / "lessons.json").read_text())
    # The lessons are written into the skills each role already reads (exported here for reading).
    planning = (installed / "skills" / "research-trajectory-planning" / "SKILL.md").read_text()
    assert "## Order of questions" in planning and "(lesson_fixture01; seen in 3 tasks" in planning
    physics = (installed / "skills" / "ocean-physical-consistency-review" / "SKILL.md").read_text()
    assert (physics.index("## Heat budgets") < physics.index("(lesson_fixture02;")
            < physics.index("## Transport and advection"))
    assert record["sha256_before"] == run_oceanx.file_sha256(snapshot / "lessons.json")


def test_lessons_version_matches_oceanx_and_ignores_the_folder_name(tmp_path, snapshot):
    from oceanx.research.lessons import LessonBook
    from oceanx.research.memory import ResearchMemory
    research = tmp_path / "research"
    (research / "lessons").mkdir(parents=True)
    (research / "lessons" / "lessons.json").write_text((snapshot / "lessons.json").read_text())
    expected = LessonBook(ResearchMemory(research)).version()
    assert expected and run_oceanx.lessons_version(snapshot) == expected


def test_arm_record_written_once_and_resume_must_match(tmp_path, monkeypatch):
    monkeypatch.setattr(run_oceanx, "ARM", {"arm": "B", "policy": "v2-nested", "lessons": None, "commit": "c"})
    attempt = tmp_path / "out" / "Q01" / "attempt-1"
    attempt.mkdir(parents=True)
    run_oceanx.write_arm(attempt)
    written = json.loads((tmp_path / "out" / "arm.json").read_text())
    assert written["arm"] == "B" and "started_utc" in written
    run_oceanx.check_arm(tmp_path / "out")
    monkeypatch.setattr(run_oceanx, "ARM", {"arm": "C", "policy": "v2-nested", "lessons": {"version": "x"}})
    with pytest.raises(SystemExit):
        run_oceanx.check_arm(tmp_path / "out")
