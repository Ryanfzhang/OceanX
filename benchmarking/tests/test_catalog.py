"""The catalogue: allocation, rubric integrity, verified papers, answer keys and suite isolation."""
import hashlib
import json
from collections import Counter
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
    assert TEST == [f"Q{i:02}" for i in range(1, 31)] and EVOLUTION == [f"E{i:02}" for i in range(1, 25)]
    assert [info(t)["type"] for t in TEST] == ["paper_reproduction"] * 10 + ["open_problem"] * 20
    assert {info(t)["open_kind"] for t in OPEN} == {"checkable", "disagreement"}
    assert all(info(t)["suite"] == "test" for t in TEST) and all(info(e)["suite"] == "evolution" for e in EVOLUTION)


def test_south_china_sea_uses_cmoms_and_few_multi_dataset_queries():
    for task in TEST:
        scs = info(task)["region"]["code"] == "SCS"
        assert scs == ("C_CORE" in info(task)["data_groups"]), task
        groups = info(task)["data_groups"]
        access = info(task)["data_access"]
        private = [MANIFEST["groups"][g]["phase"] == "private" for g in groups]
        assert access == ("private" if all(private) else "private+public" if any(private) else "public")
    def product(group):
        data_type = MANIFEST["groups"][group]["data_type"]
        return "CMOMS" if data_type.startswith("CMOMS") else data_type
    multi = [t for t in TEST if len({product(g) for g in info(t)["data_groups"]}) > 1]
    assert multi == ["Q10", "Q19", "Q22"]
    assert {info(t)["region"]["code"] for t in OPEN} == {"SCS", "ARAB", "GULF", "ECS"}
    # Fewer than half of the open problems use CMOMS.
    assert sum("C_CORE" in info(t)["data_groups"] for t in OPEN) == 7


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


def coverage(group):
    """First and last month a manifest group covers."""
    if "years" in group:
        return f"{min(group['years'])}-01", f"{max(group['years'])}-12"
    return group["start"][:7], group["end"][:7]


def test_paper_data_cover_each_papers_study_period():
    for task in PAPERS:
        match = info(task)["period_match"]
        assert rubric(task)["period_match"] == match
        assert match["paper_period"] and match["paper_data"] and match["supplied_data"]
        start, end = match["paper_window"]
        assert match["supplied_window"][0] <= start <= end <= match["supplied_window"][1], task
        windows = [coverage(MANIFEST["groups"][g]) for g in info(task)["data_groups"]]
        assert min(w[0] for w in windows) <= start and end <= max(w[1] for w in windows), task


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
        # The evolution suite has open problems only.
        assert info(task)["scored"] is False and info(task)["type"] == "open_problem" and "paper" not in info(task)
        assert not (BENCH / "evolution" / task / "evaluator").exists()


def test_evolution_has_two_sets_on_different_waters():
    sets = {e: info(e)["evolution_set"] for e in EVOLUTION}
    members = {name: [e for e in EVOLUTION if sets[e] == name] for name in "AB"}
    assert members == {"A": [f"E{i:02}" for i in range(1, 13)], "B": [f"E{i:02}" for i in range(13, 25)]}
    assert {name: {info(e)["region"]["code"] for e in tasks} for name, tasks in members.items()} == {
        "A": {"CCS"}, "B": {"TAS"}}
    # Each set has its own data, so the second round of lessons is not learned on the first set's waters.
    groups = {name: {g for e in tasks for g in info(e)["data_groups"]} for name, tasks in members.items()}
    assert not groups["A"] & groups["B"]
    for tasks in members.values():
        kinds = [info(e)["open_kind"] for e in tasks]
        assert (kinds.count("checkable"), kinds.count("disagreement")) == (10, 2)
        assert len({info(e)["query"] for e in tasks}) == 12


def test_evolution_asks_other_kinds_of_problems_than_the_test_suite():
    kinds = {e: info(e)["topic"] for e in EVOLUTION}
    # A lesson or a tool needs support from three different questions. With at most two evolution
    # questions on one kind of problem, what is admitted has to hold across kinds of problems.
    assert max(Counter(kinds.values()).values()) <= 2
    # And none of those kinds is what a test question is about, so a recipe cannot be practised here.
    assert not set(kinds.values()) & {info(t)["topic"] for t in TEST}
    subjects = ("heatwave", "upwelling", "hypox", "oxygen minimum", "bloom", "front", "boundary current",
                "kuroshio", "loop current", "intrusion", "salinification", "plume", "heat content", "carbon",
                "ventilation", "typhoon")
    for task in EVOLUTION:
        title = info(task)["title"].lower()
        assert not any(subject in title for subject in subjects), task


def test_evolution_questions_keep_their_data_groups():
    # The evolution data are downloaded and verified; a question may change, its inputs may not.
    assert {e: info(e)["data_groups"] for e in EVOLUTION} == {
        "E01": ["P_CCS_PHY"], "E02": ["P_CCS_SURF"], "E03": ["P_CCS_BGC"], "E04": ["P_CCS_SURF", "P_CCS_BGC"],
        "E05": ["P_CCS_SURF"], "E06": ["P_CCS_PHY"], "E07": ["P_CCS_BGC"], "E08": ["P_CCS_BGC"],
        "E09": ["P_CCS_PHY"], "E10": ["P_CCS_PHY"], "E11": ["P_CCS_SURF"], "E12": ["P_CCS_PHY", "P_CCS_BGC"],
        "E13": ["P_TAS_PHY"], "E14": ["P_TAS_PHY"], "E15": ["P_TAS_PHY"], "E16": ["P_TAS_PHY"],
        "E17": ["P_TAS_PHY"], "E18": ["P_TAS_PHY"], "E19": ["P_TAS_SURF"], "E20": ["P_TAS_SURF", "P_TAS_BGC"],
        "E21": ["P_TAS_SURF"], "E22": ["P_TAS_BGC"], "E23": ["P_TAS_BGC"], "E24": ["P_TAS_PHY", "P_TAS_BGC"]}
    assert all(MANIFEST["tasks"][e] == info(e)["data_groups"] for e in EVOLUTION)


def test_design_document_lists_every_task():
    design = (BENCH / "DESIGN.md").read_text()
    for task in TEST + EVOLUTION:
        assert f"| {task} | " in design and info(task)["title"] in design


def test_summary_has_three_columns_and_every_query_once():
    summary = (BENCH / "summary.md").read_text()
    rows = [line for line in summary.splitlines() if line.startswith("| **[")]
    assert len(rows) == len(TEST + EVOLUTION)
    for task in TEST + EVOLUTION:
        matched = [line for line in rows if line.startswith(f"| **[{task} · ")]
        assert len(matched) == 1
        row = matched[0]
        assert row.count("|") == 4 and info(task)["title"] in row
        suite = "tasks" if task.startswith("Q") else "evolution"
        assert f"({suite}/{task}/task_info.json)" in row
        if "paper" in info(task):
            assert info(task)["paper"]["doi"] in row
