"""The catalogue: allocation, rubric integrity, verified papers, answer keys and suite isolation."""
import hashlib
import json
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((BENCH / "download" / "data_manifest.json").read_text())
TEST = sorted(p.name for p in (BENCH / "tasks").iterdir() if p.is_dir())
EVOLUTION = sorted(p.name for p in (BENCH / "evolution").iterdir() if p.is_dir())
PAPERS, OPEN = TEST[:10], TEST[10:]
PAPER_KINDS = {"claim", "method", "differences", "report"}
OPEN_WEIGHTS = {"F": 10, "A": 10, "Q": 20, "M": 20, "R": 15, "B": 15, "I": 10}


def info(task):
    root = BENCH / ("tasks" if task.startswith("Q") else "evolution")
    return json.loads((root / task / "task_info.json").read_text())


def rubric(task):
    return json.loads((BENCH / "tasks" / task / "evaluator" / "rubric.json").read_text())


def test_allocation_ten_papers_twenty_open_problems():
    assert TEST == [f"Q{i:02}" for i in range(1, 31)] and EVOLUTION == [f"E{i:02}" for i in range(1, 13)]
    assert [info(t)["type"] for t in TEST] == ["paper_reproduction"] * 10 + ["open_problem"] * 20
    assert {info(t)["open_kind"] for t in OPEN} == {"checkable", "disagreement"}
    assert all(info(t)["suite"] == "test" for t in TEST) and all(info(e)["suite"] == "evolution" for e in EVOLUTION)


def test_south_china_sea_uses_cmoms_and_few_multi_dataset_queries():
    for task in TEST:
        scs = info(task)["region"]["code"] == "SCS"
        assert scs == ("C_CORE" in info(task)["data_groups"]), task
        groups = info(task)["data_groups"]
        access = info(task)["data_access"]
        assert access == ("private" if groups == ["C_CORE"] else "private+public" if "C_CORE" in groups else "public")
    multi = [t for t in TEST if len(info(t)["data_groups"]) > 1]
    assert len(multi) == 3
    assert {info(t)["region"]["code"] for t in OPEN} == {"SCS", "GULF", "ECS"}


@pytest.mark.parametrize("task", TEST)
def test_rubric_matches_query_and_scores_to_100(task):
    query, ref = info(task)["query"], rubric(task)
    assert ref["task_id"] == task and ref["type"] == info(task)["type"] and ref["status"] == "draft"
    assert ref["schema_version"] == 3 and ref["query_sha256"] == hashlib.sha256(query.encode()).hexdigest()
    assert sum(c["weight"] for c in ref["criteria"]) == 100
    assert all(c["id"].startswith(f"{task}-") and {"0", "2", "4"} <= set(c["anchors"]) for c in ref["criteria"])
    assert ref["gates"] and ref["frozen"] == {"references_sha256": None, "tolerances_frozen_at": None, "frozen_by": None}


@pytest.mark.parametrize("task", TEST)
def test_queries_do_not_leak_evaluator_material(task):
    query = info(task)["query"].lower()
    for word in ("answer key", "rubric", "x_heat", "x_oxy", "_evaluator_only", "temp_vadv", "evaluator"):
        assert word not in query


def test_paper_rubrics_check_each_finding_of_ten_verified_papers():
    dois = []
    for task in PAPERS:
        paper, ref = info(task)["paper"], rubric(task)
        assert paper["doi"] in info(task)["query"] and paper["url"] == f"https://doi.org/{paper['doi']}"
        assert "Crossref" in paper["verification"] and ref["paper"] == paper
        claims = [c for c in ref["criteria"] if c["kind"] == "claim"]
        assert 3 <= len(claims) <= 5 and sum(c["weight"] for c in claims) == 70
        assert {c["kind"] for c in ref["criteria"]} == PAPER_KINDS
        for i, c in enumerate(claims, 1):
            assert c["id"] == f"{task}-K{i}" and f"({i})" in info(task)["query"]
            assert c["testability"] in {"testable", "partly testable", "not testable"}
            assert c["paper_evidence"] and c["how_to_test"]
            assert (c["expected"] == "n/a") == (c["testability"] == "not testable")
        dois.append(paper["doi"])
    assert len(set(dois)) == 10


def test_open_rubrics_are_broad_and_checkable():
    for task in OPEN:
        ref = rubric(task)
        assert {c["id"].split("-")[1]: c["weight"] for c in ref["criteria"]} == OPEN_WEIGHTS
        assert not {c["kind"] for c in ref["criteria"]} & PAPER_KINDS
        items = ref["answer_key"]["items"]
        assert any(i["used_by"] == f"{task}-Q" for i in items)
        assert any(i["used_by"] == f"{task}-M" for i in items) or ref.get("candidate_causes")
        assert all(i["expected"].startswith("to freeze") for i in items)
        assert ref["depth_probes"] and ref["breadth_probes"]
        if ref["open_kind"] == "disagreement":
            assert len(ref["candidate_causes"]) >= 3 and all(c["test"] for c in ref["candidate_causes"])
        for group in ref["evaluator_groups"]:
            assert MANIFEST["groups"][group]["evaluator_only"]


def test_evaluator_groups_agree_with_manifest():
    declared = {t: rubric(t)["evaluator_groups"] for t in TEST if rubric(t)["evaluator_groups"]}
    assert declared == MANIFEST["evaluator_groups"]


def test_pairs_match_a_private_and_a_public_question():
    pairs = {t: info(t)["pair"] for t in TEST if info(t).get("pair")}
    assert len(pairs) == 12
    for task, other in pairs.items():
        assert pairs[other] == task
        assert {info(task)["data_access"], info(other)["data_access"]} == {"private", "public"}


def test_suites_use_disjoint_data_and_evolution_is_unscored():
    test_groups = {g for t in TEST for g in info(t)["data_groups"]}
    evolution_groups = {g for e in EVOLUTION for g in info(e)["data_groups"]}
    assert not test_groups & evolution_groups
    for task in EVOLUTION:
        assert info(task)["scored"] is False and info(task)["type"] in {"paper_reproduction", "open_problem"}
        assert not (BENCH / "evolution" / task / "evaluator").exists()
        if "paper" in info(task):
            assert info(task)["paper"]["doi"] in info(task)["query"]


def test_design_document_lists_every_task():
    design = (BENCH / "DESIGN.md").read_text()
    for task in TEST + EVOLUTION:
        assert f"| {task} | " in design and info(task)["title"] in design


def test_reused_paper_panels_are_intact():
    for figure in rubric("Q01")["context_figures"]:
        path = BENCH / "tasks" / "Q01" / "evaluator" / figure["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == figure["sha256"]
