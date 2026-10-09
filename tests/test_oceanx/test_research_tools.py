"""Skill regions, the helper functions a task mounts, call counts, and tools learned from tasks."""
import json
import os
import re
import subprocess
import sys

import pytest

from oceanx.expert_execution import read_tool_log
from oceanx.research import toolbook
from oceanx.research.memory import ResearchMemory, build_digest, task_key
from oceanx.research.outcomes import record_task_outcomes
from oceanx.research.toolbook import ToolBook, check_test_code, check_tool_code, repeated_functions
from oceanx.research.tree import ResearchTree
from oceanx.skill_regions import SkillRegionError, describe_functions, fill_regions, find_regions

PACKAGED = ["check_dims", "exact_align", "column_take", "masked_values", "small_sample",
            "weighted_mean", "rate_per_day", "angular_gradient_per_metre"]


@pytest.mark.parametrize("statement", [
    "from numpy import load as reader; return reader(path)",
    "from pandas import read_csv as reader; return reader(path)",
    "import numpy as numbers; return numbers.load(path)",
    "from numpy.ctypeslib import load_library as reader; return reader(path, '.')",
])
def test_file_readers_cannot_bypass_pure_tool_checks_with_aliases(statement):
    code = f'def reader_tool(path):\n    """Compute on arrays only."""\n    {statement}\n'
    with pytest.raises(ValueError):
        check_tool_code(code, name="reader_tool")

SKILL = """\
---
name: demo
---
# Demo
Packaged advice.

<!-- oceanx:lessons max=2 for="coordinator" about="what to ask first" -->
<!-- /oceanx:lessons -->

## References
Read a.md.

<!-- oceanx:tools max=3 -->
- a line the packaged file left between the markers
<!-- /oceanx:tools -->
"""


@pytest.fixture
def book(tmp_path):
    return ToolBook(ResearchMemory(tmp_path / ".oceanx" / "research"))


def test_a_region_is_the_only_part_of_a_skill_that_changes():
    regions = find_regions(SKILL)
    lessons, tools = regions["lessons"], regions["tools"]
    assert (lessons.limit, lessons.reader, lessons.about) == (2, "coordinator", "what to ask first")
    assert (tools.limit, tools.reader, tools.about) == (3, None, "")
    filled = fill_regions(SKILL, {"lessons": "Learned:\n- Ask the budget first. (L001)",
                                  "tools": "- `ao.f(x)`: Does f."})
    assert filled == SKILL.replace(
        '<!-- oceanx:lessons max=2 for="coordinator" about="what to ask first" -->\n<!-- /oceanx:lessons -->',
        "Learned:\n- Ask the budget first. (L001)").replace(
        "<!-- oceanx:tools max=3 -->\n- a line the packaged file left between the markers\n<!-- /oceanx:tools -->",
        "- `ao.f(x)`: Does f.")
    # With nothing learned the regions vanish and leave no gap; no marker ever reaches a reader.
    assert fill_regions(SKILL) == ("---\nname: demo\n---\n# Demo\nPackaged advice.\n\n"
                                   "## References\nRead a.md.\n")
    # A skill without regions is returned byte for byte.
    plain = "# Plain\r\nno trailing newline"
    assert fill_regions(plain, {"lessons": "- ignored"}) == plain and find_regions(plain) == {}


@pytest.mark.parametrize("document, problem", [
    ("<!-- oceanx:notes max=2 -->\n<!-- /oceanx:notes -->", "Unknown region marker"),
    ("<!-- oceanx:lessons -->\n<!-- /oceanx:lessons -->", "needs max=<positive number>"),
    ("<!-- oceanx:lessons max=0 -->\n<!-- /oceanx:lessons -->", "needs max=<positive number>"),
    ("<!-- oceanx:lessons max=2 -->\ntext", "is not closed"),
    ("<!-- /oceanx:lessons -->", "without its opening marker"),
    ("<!-- oceanx:lessons max=2 -->\n<!-- oceanx:tools max=2 -->\n<!-- /oceanx:tools -->", "not nested"),
    ("<!-- oceanx:tools max=2 -->\n<!-- /oceanx:tools -->\n<!-- oceanx:tools max=2 -->\n<!-- /oceanx:tools -->",
     "at most one tools region"),
])
def test_malformed_region_markers_are_refused(document, problem):
    with pytest.raises(SkillRegionError, match=problem):
        find_regions(document)


def test_the_tools_region_is_written_from_the_code(book):
    described = describe_functions(toolbook.packaged_source())
    assert [f["name"] for f in described] == PACKAGED  # self_test is not a tool
    assert all(f["summary"] for f in described)  # every function says what it does
    assert describe_functions("def _hidden(x):\n    return x\n\ndef shown(x, *, dim):\n    '''One.\n\n    Two.'''\n") == [
        {"name": "shown", "signature": "shown(x, *, dim)", "summary": "One."}]
    assert book.limit() == 40 and [t["name"] for t in book.mounted()] == PACKAGED
    block = book.block().splitlines()
    assert len(block) == 8 and block[5] == (
        "- `ao.weighted_mean(array, weights, *, dims)`: Named-dimension mean with a validity-matched "
        "denominator; no silent alignment.")
    assert book.version() is None  # no tool history: the project runs exactly the packaged library
    assert book.source() == toolbook.packaged_source()


SCRIPT = """\
import numpy as np
import xarray as xr
import oceanx_array_ops as ao

assert ao.self_test() == "Array helper self-test passed"
field = xr.DataArray(np.ones((2, 3)), dims=("lat", "lon"))
weights = xr.DataArray(np.ones(2), dims=("lat",))
for _ in range(2):
    assert float(ao.weighted_mean(field, weights, dims=("lat", "lon"))) == 1.0
assert ao.rate_per_day(1.0, input_unit="per_second") == 86400.0
for _ in range(1500):
    ao.check_dims(field, ("lat", "lon"))
try:
    ao.rate_per_day(1.0, input_unit="per_hour")
except ValueError:
    pass
assert ao.weighted_mean.__name__ == "weighted_mean" and "Named-dimension" in ao.weighted_mean.__doc__
"""


def test_the_mounted_module_logs_the_calls_analysis_code_makes(tmp_path, book):
    (tmp_path / "oceanx_array_ops.py").write_text(book.module_source())
    (tmp_path / "analysis.py").write_text(SCRIPT)
    log = tmp_path / "tool-calls.log"

    def run(**environment):
        env = {k: v for k, v in os.environ.items() if k != toolbook.TOOL_LOG_ENV}
        done = subprocess.run([sys.executable, "analysis.py"], cwd=tmp_path, env={**env, **environment},
                              capture_output=True, text=True, timeout=120, check=False)
        assert done.returncode == 0, done.stderr

    run()  # without a log file the functions simply work
    assert not log.exists() and read_tool_log(log) == {}
    run(**{toolbook.TOOL_LOG_ENV: str(log)})
    # Only what the analysis code called: not self_test, and not exact_align, which weighted_mean
    # calls itself. A call the function refused is still a call. A helper called in a long loop
    # stops being written after 1000 calls, so the log stays small.
    assert read_tool_log(log) == {"check_dims": 1000, "rate_per_day": 2, "weighted_mean": 2}


def finished_task(root, name, *, library=None, executions=(), code=None):
    tree = ResearchTree(root / name / "agents" / "coordinator" / "research_tree.json")
    tree.update([
        {"action": "add", "target": "ROOT", "question": f"Why is {name} warm?"},
        {"action": "add", "target": "B1", "question": "Heat budget?", "status": "selected"},
    ])
    tree.attach_result("B1.1", summary="Result: Flux.\nEvidence and limitations: One year.\nFurther analysis: None",
                       agent_key="p", report_path="/r", attempt_id="a")
    record_task_outcomes(tree, final_report="## Summary\nB1.1 decides it.", model_calls=[],
                         code_executions=list(executions), library=library)
    if code is not None:
        path = root / name / "agents" / "physics" / ".runtime" / "executions" / "e1" / "code" / "analysis.py"
        path.parent.mkdir(parents=True)
        path.write_text(code)
    return tree


def test_a_task_records_which_tools_it_could_call_and_did(tmp_path):
    runs = [{"agent_thread_id": "p", "state": "succeeded", "tool_calls": {"weighted_mean": 2}},
            {"agent_thread_id": "p", "state": "failed", "tool_calls": {"weighted_mean": 1, "rate_per_day": 1}},
            {"agent_thread_id": "p", "state": "succeeded", "tool_calls": None}]  # recorded before the log
    tree = finished_task(tmp_path, "new", executions=runs, library={
        "lessons_shown": [], "lessons_cited": [], "tools_mounted": PACKAGED})
    digest = build_digest(tree.store.path)
    assert digest["tools_mounted"] == PACKAGED
    assert digest["tool_calls"] == {"rate_per_day": 1, "weighted_mean": 3}
    # A task recorded before this was logged does not read as "nothing was called".
    older = build_digest(finished_task(tmp_path, "old").store.path)
    assert older["tools_mounted"] is None and older["tool_calls"] is None


def usage(index, calls, mounted=PACKAGED, **changes):
    return {"task_key": f"k{index:02d}", "finished": True, "started_at": f"2026-01-{index + 1:02d}",
            "tools_mounted": mounted, "tool_calls": calls, **changes}


def test_tools_nobody_calls_leave_the_list_and_the_owner_overrules(book, monkeypatch):
    monkeypatch.setattr(toolbook, "PROBATION_TASKS", 2)
    monkeypatch.setattr(toolbook, "IDLE_TASKS", 3)
    digests = [usage(0, {"weighted_mean": 4, "rate_per_day": 1}), usage(1, {"weighted_mean": 1}),
               usage(2, None), usage(3, {}, finished=False)]
    assert book.record_usage(digests) == {"tasks_counted": 2, "removed": []}
    stats = {tool["name"]: tool["stats"] for tool in book.tools()}
    assert stats["weighted_mean"] == {"tasks": 2, "tasks_called": 2, "calls": 5, "idle": 0}
    assert stats["rate_per_day"] == {"tasks": 2, "tasks_called": 1, "calls": 1, "idle": 1}
    assert stats["check_dims"] == {"tasks": 2, "tasks_called": 0, "calls": 0, "idle": 2}
    assert book.record_usage(digests)["tasks_counted"] == 0  # each task is counted once
    # Past the trial, the list is ordered by the share of tasks that called a tool.
    assert [t["name"] for t in book.mounted()][:2] == ["weighted_mean", "rate_per_day"]
    version = book.version()
    assert version.startswith("tools@")

    book.mark("check_dims", "right", reviewer="owner")
    result = book.record_usage([usage(4, {"weighted_mean": 1})])
    assert result == {"tasks_counted": 1, "removed": [
        "exact_align", "column_take", "masked_values", "small_sample", "angular_gradient_per_metre"]}
    by_name = {tool["name"]: tool for tool in book.overview()}
    assert by_name["small_sample"]["status"] == "unlisted" and not by_name["small_sample"]["shown"]
    assert by_name["small_sample"]["reason"] == "not called in 3 tasks"
    # The owner's choice stays whatever the counts say, and is listed first.
    assert [t["name"] for t in book.mounted()] == ["check_dims", "weighted_mean", "rate_per_day"]
    assert book.block().count("\n") == 2 and book.version() != version
    # A packaged function that left the list is still importable: old code keeps working.
    assert "def small_sample(" in book.module_source()

    book.mark("weighted_mean", "wrong", reviewer="owner")
    assert [t["name"] for t in book.mounted()] == ["check_dims", "rate_per_day"]
    book.mark("small_sample", "right", reviewer="")
    assert [t["name"] for t in book.mounted()] == ["check_dims", "small_sample", "rate_per_day"]
    for name, verdict, problem in (("nope", "right", "Unknown tool"), ("check_dims", "maybe", "right or wrong")):
        with pytest.raises(ValueError, match=problem):
            book.mark(name, verdict, reviewer="owner")
    changes = [(c["tool"], c["change"], c["by"]) for c in book.changes()]
    assert changes[0] == ("check_dims", "marked right", "owner") and changes[1][1:] == ("unlisted", "rule")
    assert changes[-2:] == [("weighted_mean", "marked wrong", "owner"), ("small_sample", "marked right", "owner")]


ANOMALY = '''def anomaly(array, baseline, *, dim):
    """Difference between an array and the mean of a baseline along a named dimension, in the array's units."""
    if dim not in array.dims or dim not in baseline.dims:
        raise ValueError("dim must name an axis of the array and of the baseline")
    return array - baseline.mean(dim)
'''
ANOMALY_TEST = '''import xarray as xr
field = xr.DataArray(np.full((4, 2), 3.0), dims=("time", "lat"))
assert float(abs(ao.anomaly(field, field, dim="time")).max()) == 0.0
try:
    ao.anomaly(field, field, dim="depth")
    raise AssertionError("an unknown dimension must be refused")
except ValueError:
    pass
'''


@pytest.mark.parametrize("change, problem", [
    (lambda code: code.replace("    if dim", "    import os\n    if dim"), "may be imported; not os"),
    (lambda code: code.replace("    if dim", "    open('x')\n    if dim"), r"open\(\) is not allowed"),
    (lambda code: code.replace("    if dim", "    print(dim)\n    if dim"), r"print\(\) is not allowed"),
    (lambda code: code.replace("    if dim", "    global seen\n    if dim"), "No state outside the function"),
    (lambda code: code.replace("baseline.mean(dim)", "xr.open_dataset(baseline).mean(dim)"), r"open_dataset\(\) reads or writes"),
    (lambda code: code.replace("    if dim", "    array.to_netcdf(dim)\n    if dim"), r"to_netcdf\(\) reads or writes"),
    (lambda code: code.replace("baseline.mean(dim)", "np.load(baseline).mean(dim)"), r"load\(\) reads or writes"),
    (lambda code: code.replace("baseline.mean(dim)", "scipy.io.loadmat(baseline).mean(dim)"), r"loadmat\(\) reads or writes"),
    (lambda code: code.replace("array.dims", "array.__dict__"), "Double-underscore attributes"),
    (lambda code: code.replace('"dim must name', '"/data/sst.nc must name'), "may not contain a file path"),
    (lambda code: "\n".join(line for line in code.splitlines() if '"""' not in line), "needs a docstring"),
    (lambda code: code + "\n\ndef other(x):\n    return x\n", "exactly one function named anomaly"),
    (lambda code: code.replace("def anomaly", "def departure"), "exactly one function named anomaly"),
    (lambda code: code + "    pass\n" * 60, "at most 60 lines"),
    (lambda code: code.replace("return array", "return (array"), "does not parse"),
])
def test_a_learned_function_may_only_compute_on_its_arguments(change, problem):
    check_tool_code(ANOMALY, name="anomaly")
    check_tool_code(ANOMALY.replace("baseline.mean(dim)", "baseline.load().mean(dim)"), name="anomaly")  # no file
    with pytest.raises(ValueError, match=problem):
        check_tool_code(change(ANOMALY), name="anomaly")


def test_a_tool_test_must_assert_and_stay_inside_the_helper_module():
    check_test_code(ANOMALY_TEST)
    check_test_code("import oceanx_array_ops\nassert oceanx_array_ops.rate_per_day(1, input_unit='per_day') == 1")
    for test, problem in (("ao.anomaly(1, 2, dim='t')", "at least one assert"),
                          ("import subprocess\nassert True", "may be imported; not subprocess"),
                          ("assert open('/etc/passwd')", r"open\(\) is not allowed"),
                          ("assert (", "does not parse")):
        with pytest.raises(ValueError, match=problem):
            check_test_code(test)


AREA_MEAN = '''import xarray as xr

def area_mean(field, lat):
    weights = np.cos(np.deg2rad(lat)){variant}
    return (field * weights).sum() / weights.sum()

def one_liner(x): return x

def main():
    data = xr.open_dataset("sst.nc")
    print(area_mean(data.sst, data.lat))
'''


def project_with_repeated_code(tmp_path, tasks=4):
    memory = ResearchMemory(tmp_path / ".oceanx" / "research")
    stores = []
    for index in range(tasks):
        tree = finished_task(tmp_path, f"t{index}", code=AREA_MEAN.format(variant=f"  # task {index}" * (index % 2)))
        memory.digest(tree.store.path)
        stores.append(tree.store.path)
    return ToolBook(memory), stores


def test_code_written_again_in_several_tasks_is_the_material_for_a_tool(tmp_path):
    book, stores = project_with_repeated_code(tmp_path)
    scratch = tmp_path / "t0" / "agents" / "physics" / "scratch" / "deep" / "helper.py"
    scratch.parent.mkdir(parents=True)
    scratch.write_text("def area_mean(field, lat):\n    w = np.cos(lat)\n    return (field * w).mean()\n\n"
                       "def only_here(x):\n    y = x\n    return y\n")
    (tmp_path / "t1" / "agents" / "physics" / "scratch").mkdir(parents=True)
    (tmp_path / "t1" / "agents" / "physics" / "scratch" / "broken.py").write_text("def broken(:\n")
    # Another task wrote the same calculation twice under a name of its own.
    for run in ("e2", "e3"):
        other = tmp_path / "t2" / "agents" / "physics" / ".runtime" / "executions" / run / "code" / "analysis.py"
        other.parent.mkdir(parents=True)
        other.write_text("def wm(x, lat):\n    w = np.cos(np.deg2rad(lat))\n    return (x * w).sum() / w.sum()\n")
    questions = {d["task_key"]: d["question"] for d in book.memory.load_digests()}
    found = repeated_functions(stores, questions)  # one_liner, main and only_here are not repeats
    # One entry per task and name: the meta-agent, not the name, matches them across tasks.
    assert [(c["id"], c["name"]) for c in found] == [
        ("C01", "area_mean"), ("C02", "area_mean"), ("C03", "area_mean"), ("C04", "area_mean"), ("C05", "wm")]
    first = found[0]  # the task that wrote it twice
    assert (first["task_keys"], first["uses"], first["other_tasks"]) == ([task_key(stores[0])], 2, 3)
    assert first["examples"] == ["def area_mean(field, lat):\n    w = np.cos(lat)\n    return (field * w).mean()"]
    assert all((c["uses"], c["other_tasks"], len(c["question_set"])) == (1, 3, 1) for c in found[1:4])
    assert sorted(c["task_keys"][0] for c in found[:4]) == sorted(task_key(store) for store in stores)
    assert (found[4]["task_keys"], found[4]["uses"], found[4]["other_tasks"]) == ([task_key(stores[2])], 2, 0)
    # Repeated runs of one question are one piece of evidence: every entry then has the same question.
    same = repeated_functions(stores, dict.fromkeys(questions, "Same question?"))
    assert {q for c in same for q in c["question_set"]} == {"same question?"}
    # One long task does not fill the list.
    busy = tmp_path / "t3" / "agents" / "physics" / "scratch"
    busy.mkdir(parents=True)
    for index in range(2):
        (busy / f"many{index}.py").write_text("\n".join(
            f"def helper_{n}(x):\n    y = x + {n}\n    return y\n" for n in range(20)))
    crowded = repeated_functions(stores, questions)
    assert sum(c["task_keys"] == [task_key(stores[3])] for c in crowded) == toolbook.MAX_PER_TASK


def test_a_proposed_tool_is_mounted_only_through_every_gate(tmp_path):
    book, stores = project_with_repeated_code(tmp_path)
    proposal = {"name": "anomaly", "code": ANOMALY, "test": ANOMALY_TEST, "replaces": ["area_mean"],
                "rationale": "Written again in four tasks."}
    prompts, tested, reviewed = [], [], []

    def llm(prompt):
        prompts.append(prompt)
        return json.dumps({"tools": [
            proposal, {**proposal, "name": "weighted_mean"}, {**proposal, "name": "departure", "replaces": []},
            {**proposal, "name": "fourth"}]})  # more than one review may add

    def run_test(module, test):
        tested.append((module, test))

    def reviewer(prompt):
        reviewed.append(prompt)
        return json.dumps({"verdict": "accept", "reason": "Correct."})

    result = book.learn(llm, stores, reviewer=reviewer, run_test=run_test)
    assert result["created"] == ["anomaly"] and result["candidates"] == 4
    assert [(r["name"], r["reason"].split(";")[0][:60]) for r in result["rejected"]] == [
        ("weighted_mean", "The helper module already has, or once had, weighted_mean."),
        ("departure", "The code must be exactly one function named departure.")]
    # The meta-agent saw the module as it is and the repeated code, without the call counter.
    assert "# The helper module now" in prompts[0] and "def weighted_mean(" in prompts[0]
    assert re.search(r'## C01 `area_mean`: defined in 1 code runs of the task on "why is t\d warm\?"; '
                     "the same name in 3 other tasks", prompts[0])
    assert "match the\nentries by what they compute, not by their names" in prompts[0]
    assert "_oceanx_count_calls" not in prompts[0]
    # The test ran against the module the function would be mounted in; the reviewer saw both.
    [(module, test)] = tested
    assert "def weighted_mean(" in module and "def anomaly(" in module and test == ANOMALY_TEST.strip()
    assert ANOMALY.strip() in reviewed[0] and ANOMALY_TEST.strip() in reviewed[0]
    # Mounted at once: in the module tasks import, in the skill's list, and in the version.
    learned = next(tool for tool in book.tools() if tool["name"] == "anomaly")
    assert (learned["source"], learned["status"], learned["signature"]) == (
        "learned", "listed", "anomaly(array, baseline, *, dim)")
    assert learned["evidence"]["questions"] == 4 and len(learned["evidence"]["tasks"]) == 4
    assert (learned["code"], learned["test"]) == (ANOMALY.strip(), ANOMALY_TEST.strip())  # for the owner to read
    assert "def anomaly(" in book.source() and "_oceanx_count_calls" not in book.source()
    assert book.module_source().startswith(book.source())
    assert book.block().splitlines()[-1].startswith("- `ao.anomaly(array, baseline, *, dim)`: Difference between")
    assert book.version().startswith("tools@")
    assert (book.root / "learned" / "anomaly.py").read_text() == ANOMALY
    assert (book.root / "learned" / "test_anomaly.py").read_text() == ANOMALY_TEST
    [change] = book.changes()
    assert (change["tool"], change["change"], change["by"], change["reason"]) == (
        "anomaly", "added", "meta-agent", "Written again in four tasks.")


def test_a_failed_test_or_a_refusing_reviewer_keeps_a_tool_out(tmp_path):
    book, stores = project_with_repeated_code(tmp_path)
    candidates = repeated_functions(stores, {d["task_key"]: d["question"] for d in book.memory.load_digests()})
    proposal = {"name": "anomaly", "code": ANOMALY, "test": ANOMALY_TEST, "replaces": ["area_mean"]}
    with pytest.raises(ValueError, match="Its test failed: AssertionError"):
        book.admit(proposal, candidates, run_test=lambda module, test: "AssertionError")
    with pytest.raises(ValueError, match="The reviewer refused it: Divides by the wrong count."):
        book.admit(proposal, candidates, run_test=lambda module, test: None, reviewer=lambda prompt: json.dumps(
            {"verdict": "reject", "reason": "Divides by the wrong count."}))
    with pytest.raises(ValueError, match="at least 3 different questions; this replaces code from 0"):
        book.admit({**proposal, "replaces": ["never_written"]}, candidates, run_test=lambda module, test: None)
    # An id names one task's entry, so two ids are code from two questions.
    with pytest.raises(ValueError, match="at least 3 different questions; this replaces code from 2"):
        book.admit({**proposal, "replaces": ["C01", "C02"]}, candidates, run_test=lambda module, test: None)
    with pytest.raises(ValueError, match="lower-case name"):
        book.admit({**proposal, "name": "Bad-Name"}, candidates, run_test=lambda module, test: None)
    assert book.version() is None and not (book.root / "learned").exists()  # nothing was mounted
    # With code from fewer than three questions nothing could pass, so the model is not asked.
    few, few_stores = project_with_repeated_code(tmp_path / "few", tasks=2)
    result = few.learn(lambda prompt: pytest.fail("the model must not be asked"), few_stores)
    assert result == {"created": [], "rejected": [], "candidates": 2}
    # A reply that cannot be read adds nothing and does not stop the update.
    unreadable = book.learn(lambda prompt: "I could not decide.", stores)
    assert unreadable["created"] == [] and "could not be read" in unreadable["rejected"][0]["reason"]


def test_a_learned_tool_nobody_calls_is_retired(tmp_path, monkeypatch):
    monkeypatch.setattr(toolbook, "PROBATION_TASKS", 2)
    monkeypatch.setattr(toolbook, "IDLE_TASKS", 2)
    book, stores = project_with_repeated_code(tmp_path)
    candidates = repeated_functions(stores, {d["task_key"]: d["question"] for d in book.memory.load_digests()})
    proposal = {"name": "anomaly", "code": ANOMALY, "test": ANOMALY_TEST, "replaces": ["C01", "C02", "C04"]}
    book.admit(proposal, candidates, run_test=lambda module, test: None)
    book.mark("weighted_mean", "right", reviewer="owner")
    mounted = [*PACKAGED, "anomaly"]
    result = book.record_usage([usage(i, {"weighted_mean": 1}, mounted=mounted) for i in range(2)])
    assert "anomaly" in result["removed"]
    retired = next(tool for tool in book.overview() if tool["name"] == "anomaly")
    assert (retired["status"], retired["shown"], retired["reason"]) == ("retired", False, "not called in 2 tasks")
    # A retired learned function is gone from the module, and its name is not used again.
    assert "def anomaly(" not in book.module_source() and not (book.root / "learned" / "anomaly.py").exists()
    with pytest.raises(ValueError, match="already has, or once had, anomaly"):
        book.admit(proposal, candidates, run_test=lambda module, test: None)
    # The owner can bring it back.
    book.mark("anomaly", "right", reviewer="owner")
    assert "def anomaly(" in book.module_source() and (book.root / "learned" / "anomaly.py").is_file()


def test_a_tool_test_runs_in_the_sandbox(tmp_path, book, monkeypatch):
    from oceanx.sandbox import get_sandbox_execution_capabilities
    capabilities = get_sandbox_execution_capabilities()
    if not capabilities.available:
        pytest.skip(capabilities.reason or "sandbox backend is unavailable")
    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    module = book.source() + "\n\n" + ANOMALY + toolbook.TRACKER
    assert toolbook.run_tool_test(module, ANOMALY_TEST) is None
    failure = toolbook.run_tool_test(module, "assert ao.rate_per_day(1.0, input_unit='per_second') == 1.0")
    assert failure.startswith("AssertionError")
    # The test cannot read the project it is run for.
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    outside = toolbook.run_tool_test(module, f"assert __builtins__.open({str(secret)!r}).read()")
    assert outside.startswith(("PermissionError", "FileNotFoundError"))


def test_a_task_names_to_each_reader_the_skills_that_hold_what_was_learned(tmp_path):
    """Lessons and tools live only in skills, and an agent opens a skill only when told to:
    unnamed, Experts opened these skills in about 2% of their questions."""
    from pathlib import Path
    from types import SimpleNamespace

    from oceanx.research import graphs
    from oceanx.research.review import ProjectResearch
    project = ProjectResearch(SimpleNamespace(root=tmp_path / ".oceanx"))
    process, statistics = "ocean_process_expert", "statistical_inference_expert"
    # Nothing learned: nobody is told to read anything.
    assert all(project.learned_in(role, research=True) == [] for role in ("coordinator", process, statistics))
    assert graphs.learned_skills_rule([]) == ""

    book, stores = project_with_repeated_code(tmp_path)  # the same project folder
    candidates = repeated_functions(stores, {d["task_key"]: d["question"] for d in book.memory.load_digests()})
    book.admit({"name": "anomaly", "code": ANOMALY, "test": ANOMALY_TEST, "replaces": ["area_mean"]},
               candidates, run_test=lambda module, test: None)
    project.lessons._save([
        {"id": f"L00{index}", "skill": skill, "role": "expert", "text": "Check the mask first.",
         "applies_when": "Always.", "evidence": {"supporting": [], "counter": []}, "status": "active",
         "human": None, "added_by": "meta-agent", "added_at": "2026-01-01T00:00:00+00:00"}
        for index, skill in enumerate(("research-trajectory-planning", "claim-grounded-writing",
                                       "ocean-dataset-diagnosis", "hypothesis-experiment-design"), 1)])
    # Each reader is told of the skills it can open that now hold lessons, and of the learned tool.
    assert set(project.learned_in(process, research=True)) == {
        "claim-grounded-writing", "ocean-dataset-diagnosis", toolbook.SKILL}
    assert set(project.learned_in(statistics, research=True)) == {
        "claim-grounded-writing", "ocean-dataset-diagnosis", "hypothesis-experiment-design", toolbook.SKILL}
    assert set(project.learned_in("coordinator", research=True)) == {
        "research-trajectory-planning", graphs.WRITING_SKILL}
    # Lessons are written only into research tasks; the learned tool is mounted in every task.
    assert project.learned_in(process, research=False) == [toolbook.SKILL]
    rule = graphs.learned_skills_rule(project.learned_in(process, research=True))
    assert "Earlier tasks left lessons in /skills/" in rule and "/skills/ocean-dataset-diagnosis/SKILL.md" in rule
    assert f"/skills/{toolbook.SKILL}/SKILL.md lists tested helper functions, already imported as `ao`" in rule
    assert rule.endswith("Read these files in one step before your first calculation.")
    assert graphs.learned_skills_rule([toolbook.SKILL]).endswith("Read this file before your first calculation.")
    assert f"/skills/{graphs.WRITING_SKILL}/SKILL.md" in graphs.FINAL_ANSWER_SKILL_RULE
    # Both instructions are part of the prompts the research graphs build.
    source = Path(graphs.__file__).read_text(encoding="utf-8")
    assert 'prompt += " " + learned_skills_rule(learned)' in source
    assert 'prompt += "\\n" + FINAL_ANSWER_SKILL_RULE' in source
