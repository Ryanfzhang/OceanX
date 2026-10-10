"""Helper functions Experts call in their code, and how often they call them.

A tool is the executable part of a skill: a Python function in the skill's script, listed in
the skill's tools region. The packaged functions always exist. A project can add functions
learned from its own tasks; each task's helper module is the packaged file plus the project's
learned functions, so the packaged file is never changed.

Every call made from analysis code is logged per execution (the mounted module appends the
function's name to the file named by ``OCEAN_TOOL_LOG``). Calls are the evidence for keeping
a tool on the list: one that no task has called for ``IDLE_TASKS`` tasks is taken off it. A
learned tool is then retired; a packaged one stays importable but is no longer listed. The
owner can mark any tool right (it stays) or wrong (it goes).

A learned tool starts as code that Experts wrote again and again, in one task or in several.
Experts name one calculation differently from task to task, so repeated code is collected per
task and the meta-agent matches it across tasks by what it computes. It turns such code into one
general function with a test; the function is mounted only if a static check, its test in the
sandbox and an independent review all pass. Admission is easy on purpose (repeated code from two
questions in everyday use, from one in a benchmark's learning step): whether a tool stays is
decided by whether tasks call it.

Layout under ``<project>/.oceanx/research/tools/``::

    tools.json     state of every tool: status, call counts, the owner's mark, learned code
    changes.jsonl  every change, with its reason
    learn_state.json  the tasks whose code the learning step has read
    learned/       the learned functions and their tests, exported for reading
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import tempfile
import textwrap
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from oceanx.research.llm import parse_json_object
from oceanx.research.memory import ResearchMemory, task_key
from oceanx.research.tree_store import atomic_write_text
from oceanx.skill_regions import TOOL_ALIAS, describe_functions, find_regions, tools_block

SKILL = "xarray-array-ops"  # the skill whose tools region lists the helper functions
MODULE = "oceanx_array_ops"
TOOL_LOG_ENV = "OCEAN_TOOL_LOG"
PROBATION_TASKS = 10  # a new tool is listed ahead of the others until this many tasks could call it
IDLE_TASKS = 20  # tasks in a row without a call before a tool leaves the list
MAX_NEW_PER_REVIEW = 5  # tools one review may mount
MAX_PROPOSALS = 8  # proposals one review tries, in the meta-agent's order, until that many passed
MAX_TOOL_LINES = 60
MAX_CANDIDATES = 96  # functions shown to the meta-agent, the most rewritten first
MAX_PER_TASK = 8  # of them from one task, so that one long task does not fill the list
REPLY_KEPT = 2000  # characters kept of a reply that could not be read, for the owner to see
# Questions whose repeated code a learned tool must replace: two in everyday use. A benchmark's
# learning step has one review of a dozen tasks, so it sets one (Owner, 2026-10-10: with three
# required, 12 tasks gave no tool). A tool no task calls is retired after IDLE_TASKS.
MIN_SUPPORT_ENV = "OCEANX_TOOL_MIN_SUPPORT"
DEFAULT_MIN_SUPPORT = 2
ALLOWED_IMPORTS = frozenset({"math", "numpy", "xarray", "pandas", "scipy", "gsw"})
FORBIDDEN_CALLS = frozenset({"open", "eval", "exec", "compile", "__import__", "input", "print",
                             "globals", "locals", "getattr", "setattr", "delattr", "vars"})
# Methods that read or write files: a tool computes on arrays it is given.
_FILE_METHOD = re.compile(r"open\w*|load\w+|read\w*|save\w*|write\w*|dump\w*|genfromtxt|fromfile|tofile"
                          r"|to_(?:netcdf|zarr|csv|pickle|parquet|json|hdf|excel)|url\w+")
VERDICTS = ("right", "wrong")
_NAME = re.compile(r"[a-z][a-z0-9_]{2,39}")
_FILE_PATH = re.compile(r"^(?:~|/|\.{1,2}/)\S|\.(?:nc|npz|npy|csv|zarr|json|txt|parquet|grib)\b")

# Appended to the mounted module. It counts calls made by analysis code: a helper called by
# another helper, or by self_test, is not a call an Expert made.
TRACKER = '''

def _oceanx_count_calls():
    import functools
    import os

    depth, written = [0], {}

    def counted(name, function, logged):
        @functools.wraps(function)
        def call(*args, **kwargs):
            outermost = depth[0] == 0
            depth[0] += 1
            try:
                return function(*args, **kwargs)
            finally:
                depth[0] -= 1
                path = os.environ.get("OCEAN_TOOL_LOG")
                # A helper called in a long loop is still one use: stop writing after 1000 calls.
                if outermost and logged and path and written.get((path, name), 0) < 1000:
                    written[(path, name)] = written.get((path, name), 0) + 1
                    try:
                        with open(path, "a", encoding="utf-8") as stream:
                            stream.write(name + "\\n")
                    except OSError:
                        pass
        return call

    for name, value in list(globals().items()):
        if (not name.startswith("_") and getattr(value, "__module__", None) == __name__
                and type(value).__name__ == "function"):
            globals()[name] = counted(name, value, name != "self_test")


_oceanx_count_calls()
'''

WRITING_INSTRUCTIONS = """\
You maintain the helper functions of OceanX, an ocean-science research system. Its Experts analyse
ocean data with Python. The helper module below is imported in their code as `{alias}`. Past tasks
show which small functions the Experts wrote again and again instead.

Propose at most {max_new} new helper functions that would replace such repeated code, the most
useful first. The same
calculation carries different names from task to task (`amean`, `wm`, `area_avg`): match the
entries by what they compute, not by their names. A function is worth adding only when calling
it is shorter and safer than writing the calculation again. Prefer no function over a weak one.

Each function must:
- be one pure function: it computes on its arguments and returns a value. No file, network or
  printing, no global state;
- take every scientific choice as an explicit argument: dimensions, units, weights, thresholds,
  reference levels. It guesses nothing from a name or a shape, and raises ValueError on input
  it cannot handle;
- work on labeled (xarray) arrays where the repeated code did;
- import only {imports}, inside the function;
- be at most {max_lines} lines, with a docstring whose first paragraph says in one sentence
  what it computes, in which units and under which assumption.

Each function needs a test: plain `assert` statements that call `{alias}.<name>` on small arrays
with a known answer, and one input the function must refuse. At least one case must use values
that differ from one another, with the expected result worked out by hand, so that a wrong
weight, grouping, axis or sign would fail it. A constant field that gives back the constant may
be added, but proves little by itself. `np` and `{alias}` are already imported in the test. It
may not print and cannot import pytest: check the refused input with try/except.

Do not propose: a function the module already has, even under another name; anything specific to
one region, dataset or variable name; plotting; reading or writing files.

The "replaces" line lists the ids (such as C07) of every entry the function replaces, from all
tasks. Together they must come from {min_support} or more research questions; a calculation that
several tasks needed is the better choice.

Reply with one section per function in exactly this form and nothing else. The first code block
of a section is the function, the second is its test. Do not put code in JSON.

### tool: <name>
replaces: C03, C17
rationale: <one sentence>
```python
def <name>(...):
    ...
```
```python
assert ...
```

If no function is worth adding, reply with the two words: no tools
"""

REVISION_INSTRUCTIONS = """\

# Refused
The proposals below were refused, each for the reason given. Return a corrected version of those
that can be corrected, under the same name and in the same form, and leave the others out. Do
not return a proposal that was accepted, and do not add a new one. If none can be corrected,
reply with the two words: no tools
"""

REVIEW_INSTRUCTIONS = """\
You review one helper function before ocean scientists' analysis code may call it. You did not
write it. Its test has been run and passes. Look for a numerical or scientific error: a wrong
formula, a wrong unit conversion, a mask or weight applied to the wrong values, a denominator
that counts invalid cells, a silent assumption the docstring does not state, or a test that
would pass even if the function were wrong. Reject only for such a defect, and name it; a
missing feature, a point of style or an input the function already refuses is not one.

Reply with JSON only: {{"verdict": "accept" | "reject", "reason": "<one sentence>"}}

Function:
{code}

Its test:
{test}
"""


def min_support() -> int:
    """How many questions' repeated code a learned tool must replace (see MIN_SUPPORT_ENV)."""
    try:
        return max(1, int(os.environ.get(MIN_SUPPORT_ENV) or DEFAULT_MIN_SUPPORT))
    except ValueError:
        return DEFAULT_MIN_SUPPORT


# A heading as asked for, or as models vary it ("## Tool 2: `name`", "**tool:** name"). Two or
# more "#": a single one starts a comment in the code a reply carries.
_SECTION = re.compile(r"^[ \t]*(?:#{2,6}[ \t]*|\*\*)tool(?:[ \t]*\d+)?[ \t]*:\W{0,3}([A-Za-z_]\w*).*$",
                      re.MULTILINE | re.IGNORECASE)
_BLOCK = re.compile(r"^[ \t]*```[^\n`]*\n(.*?)^[ \t]*```[ \t]*$", re.MULTILINE | re.DOTALL)
_FIELD = re.compile(r"^[ \t>*-]*(replaces|rationale)\**[ \t]*:\**[ \t]*(.*)$",
                    re.MULTILINE | re.IGNORECASE)


def read_proposals(reply: str) -> list[dict]:
    """The functions one reply proposes: per function a heading, what it replaces, and two
    fenced code blocks, the function and then its test.

    Code is not carried in JSON strings. There every quote and line break must be escaped, and
    one slip made a whole reply of proposals unreadable (server review of 2026-10-10). Here a
    section that is incomplete is still returned, so that it is refused by itself."""
    reply = reply.replace("\r\n", "\n")
    marks = list(_SECTION.finditer(reply))
    if not marks:
        if re.search(r"\bno tools\b", reply, re.IGNORECASE):
            return []
        raise ValueError("it has no section that starts with '### tool: <name>'.")
    proposals = []
    for mark, following in zip(marks, [*marks[1:], None], strict=True):
        body = reply[mark.end():following.start() if following else len(reply)]
        blocks = [textwrap.dedent(block).strip("\n") for block in _BLOCK.findall(body)]
        fields = {key.lower(): value.strip() for key, value in _FIELD.findall(body.split("```", 1)[0])}
        proposals.append({"name": mark.group(1), "code": blocks[0] if blocks else "",
                          "test": blocks[1] if len(blocks) > 1 else "",
                          "replaces": re.findall(r"[A-Za-z_]\w*", fields.get("replaces", "")),
                          "rationale": fields.get("rationale", "")})
    return proposals


def packaged_source() -> str:
    from oceanx.skills import ocean_skill_dirs
    return (ocean_skill_dirs()[0] / SKILL / "scripts" / f"{MODULE}.py").read_text(encoding="utf-8")


def _check_statements(tree: ast.AST, *, extra_imports: frozenset[str] = frozenset()) -> None:
    numpy_aliases = {"np", "numpy"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            numpy_aliases.update(alias.asname or alias.name for alias in node.names
                                 if alias.name == "numpy")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                       else [node.module or ""])
            for module in modules:
                if module.split(".")[0] not in ALLOWED_IMPORTS | extra_imports:
                    raise ValueError(f"Only {', '.join(sorted(ALLOWED_IMPORTS))} may be imported; "
                                     f"not {module}.")
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if (_FILE_METHOD.fullmatch(alias.name)
                            or (alias.name == "load" and (node.module or "").split(".")[0] == "numpy")
                            or alias.name == "*"):
                        raise ValueError(f"Importing {alias.name} can bypass the file-access checks.")
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in FORBIDDEN_CALLS):
            raise ValueError(f"{node.func.id}() is not allowed.")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and (
                _FILE_METHOD.fullmatch(node.func.attr)
                # ``array.load()`` computes a lazy array; ``np.load(path)`` reads a file.
                or (node.func.attr == "load" and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in numpy_aliases)):
            raise ValueError(f"{node.func.attr}() reads or writes a file, which a tool may not do.")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            raise ValueError("No state outside the function may be changed.")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("Double-underscore attributes are not allowed.")


def check_tool_code(code: str, *, name: str) -> None:
    """Refuse a learned function that does more than compute on its arguments."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"The function does not parse: {exc.msg}.") from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef) or tree.body[0].name != name:
        raise ValueError(f"The code must be exactly one function named {name}.")
    function = tree.body[0]
    if not ast.get_docstring(function):
        raise ValueError("The function needs a docstring that states units and assumptions.")
    if len(code.strip().splitlines()) > MAX_TOOL_LINES:
        raise ValueError(f"A tool has at most {MAX_TOOL_LINES} lines.")
    _check_statements(tree)
    docstring = function.body[0].value
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and node is not docstring
                and _FILE_PATH.search(node.value)):
            raise ValueError("A tool may not contain a file path.")


def check_test_code(test: str) -> None:
    """A test only calls the helper module on small arrays it builds itself."""
    try:
        tree = ast.parse(test)
    except SyntaxError as exc:
        raise ValueError(f"The test does not parse: {exc.msg}.") from exc
    if not any(isinstance(node, ast.Assert) for node in ast.walk(tree)):
        raise ValueError("The test needs at least one assert.")
    _check_statements(tree, extra_imports=frozenset({MODULE}))


def run_tool_test(module_source: str, test: str, *, timeout: int = 120) -> str | None:
    """Run a tool's test in the sandbox against the module it would be mounted in.
    None when it passes, otherwise why it failed."""
    import asyncio

    from oceanx.sandbox.execution import (
        ResourceLimits,
        SandboxExecutionPolicy,
        SandboxUnavailableError,
        current_python_runtime,
        run_sandboxed_command,
    )
    with tempfile.TemporaryDirectory(prefix="oceanx-tool-test-") as directory:
        root = Path(directory).resolve()
        (root / "tmp").mkdir()
        (root / f"{MODULE}.py").write_text(module_source, encoding="utf-8")
        (root / "tool_test.py").write_text(
            f"import numpy as np\nimport {MODULE} as {TOOL_ALIAS}\n\n{test}\n", encoding="utf-8")
        try:
            runtime = current_python_runtime()
            policy = SandboxExecutionPolicy(
                read_only_roots=(), runtime_read_roots=runtime.read_roots, writable_roots=(root,),
                output_root=root, temporary_root=root / "tmp",
                limits=ResourceLimits(wall_time_seconds=timeout, cpu_time_seconds=timeout))
            result = asyncio.run(run_sandboxed_command(
                (str(runtime.executable), "tool_test.py"), policy=policy, cwd=root,
                environment={"PYTHONPATH": str(root), "PYTHONNOUSERSITE": "1"}))
        except SandboxUnavailableError as exc:  # untested code is never mounted
            return f"The sandbox is not available: {exc}"[:300]
    if result.status.value != "succeeded":
        lines = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        return (lines[-1] if lines else f"The test ended as {result.status.value}.")[:300]
    return None


def repeated_functions(stores: list[Path], questions: dict[str, str]) -> list[dict]:
    """Functions the Experts of a task wrote again: the raw material for a learned tool.

    A function is grouped by its name inside one task only, because the same calculation is
    called ``amean`` in one task and ``wm`` in the next. An entry is kept when the task defined
    the function at least twice, or another task defined one of the same name. ``questions``
    maps a task key to its research question, because repeats of one question are one piece of
    evidence. No model is involved; the meta-agent matches the entries across tasks."""
    by_task: dict[str, dict[str, dict]] = {}
    for store in stores:
        task_root, key = Path(store).parents[2], task_key(Path(store))
        files = [*task_root.glob("agents/*/.runtime/executions/*/code/analysis.py"),
                 *task_root.glob("agents/*/scratch/**/*.py")]
        for path in files:
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source)
            except (OSError, SyntaxError, ValueError):
                continue
            for node in tree.body:
                if not isinstance(node, ast.FunctionDef) or node.name in {"main", "self_test"}:
                    continue
                body = ast.get_source_segment(source, node) or ""
                if not 2 <= len(body.splitlines()) <= MAX_TOOL_LINES:
                    continue
                group = by_task.setdefault(key, {}).setdefault(node.name, {"uses": 0, "bodies": {}})
                group["uses"] += 1
                group["bodies"].setdefault(ast.dump(node), [0, body])[0] += 1
    named_in: dict[str, set[str]] = {}
    for key, groups in by_task.items():
        for name in groups:
            named_in.setdefault(name, set()).add(key)
    found = []
    for key, groups in by_task.items():
        question = " ".join((questions.get(key) or key).lower().split())
        kept = [{"name": name, "uses": group["uses"], "other_tasks": len(named_in[name]) - 1,
                 "task_keys": [key], "question_set": [question],
                 # The form the task wrote most often; the shorter one when two are as common.
                 "examples": [min(group["bodies"].values(), key=lambda b: (-b[0], len(b[1])))[1]]}
                for name, group in groups.items()
                if group["uses"] >= 2 or len(named_in[name]) > 1]
        kept.sort(key=lambda c: (-(c["uses"] + c["other_tasks"]), c["name"]))
        found += kept[:MAX_PER_TASK]
    found.sort(key=lambda c: (-(c["uses"] + c["other_tasks"]), c["name"], c["task_keys"]))
    found = found[:MAX_CANDIDATES]
    for index, candidate in enumerate(found, 1):
        candidate["id"] = f"C{index:02d}"
    return found


def _usage_rate(stats: dict) -> float:
    return stats["tasks_called"] / stats["tasks"] if stats["tasks"] else 0.0


class ToolBook:
    def __init__(self, memory: ResearchMemory):
        self.memory = memory
        self.root = memory.root / "tools"

    # --- state -------------------------------------------------------------------
    def _path(self) -> Path:
        return self.root / "tools.json"

    def _load(self) -> dict:
        path = self._path()
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        return {"tools": data.get("tools", {}), "counted": data.get("counted", [])}

    def _save(self, data: dict) -> None:
        atomic_write_text(self._path(), json.dumps(data, ensure_ascii=False, indent=2))
        folder = self.root / "learned"  # readable copies; tasks do not load these files
        shutil.rmtree(folder, ignore_errors=True)
        for name, tool in data["tools"].items():
            if tool.get("source") == "learned" and tool.get("status") == "listed":
                atomic_write_text(folder / f"{name}.py", tool["code"].rstrip() + "\n")
                atomic_write_text(folder / f"test_{name}.py", tool["test"].rstrip() + "\n")

    def _log(self, change: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "changes.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), **change},
                                    ensure_ascii=False) + "\n")

    def changes(self, limit: int = 30) -> list[dict]:
        path = self.root / "changes.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        return [json.loads(line) for line in lines[-limit:]]

    @staticmethod
    def _entry(saved: dict | None, described: dict, source: str) -> dict:
        saved = saved or {}
        return {**described, "source": source, "status": saved.get("status", "listed"),
                "human": saved.get("human"),
                "stats": {"tasks": 0, "tasks_called": 0, "calls": 0, "idle": 0, **saved.get("stats", {})},
                # A learned tool carries its code and test, so the owner can judge it.
                **{key: saved[key] for key in ("created_at", "evidence", "reason", "code", "test")
                   if key in saved}}

    def tools(self) -> list[dict]:
        """Every tool the project knows: the packaged functions and the learned ones."""
        saved = self._load()["tools"]
        known = [self._entry(saved.get(item["name"]), item, "packaged")
                 for item in describe_functions(packaged_source())]
        packaged = {tool["name"] for tool in known}
        for name, tool in saved.items():
            if tool.get("source") == "learned" and name not in packaged:
                known.append(self._entry(tool, {"name": name, "signature": tool["signature"],
                                                "summary": tool["summary"]}, "learned"))
        return known

    @staticmethod
    def limit() -> int:
        from oceanx.skills import load_ocean_skill
        return find_regions(load_ocean_skill(SKILL)[0])["tools"].limit

    def mounted(self) -> list[dict]:
        """The tools the skill lists, best first: the owner's choices, then tools still on
        trial, then by the share of tasks that called them."""
        listed = [tool for tool in self.tools() if tool["status"] == "listed"]
        order = {tool["name"]: index for index, tool in enumerate(listed)}
        listed.sort(key=lambda tool: (tool["human"] != "right",
                                      tool["stats"]["tasks"] >= PROBATION_TASKS,
                                      -_usage_rate(tool["stats"]), order[tool["name"]]))
        return listed[:self.limit()]

    def block(self) -> str:
        return tools_block(self.mounted(), alias=TOOL_ALIAS)

    def source(self) -> str:
        """The helper functions as code: the packaged file, then the functions the project learned.
        Equal to the packaged file while nothing is learned."""
        learned = [tool for tool in self._load()["tools"].values()
                   if tool.get("source") == "learned" and tool.get("status") == "listed"]
        if not learned:
            return packaged_source()
        return "\n\n\n".join([packaged_source().rstrip(), *(tool["code"].strip() for tool in learned)]) + "\n"

    def module_source(self) -> str:
        """The helper module a task imports: those functions and the call counter."""
        return self.source().rstrip() + "\n" + TRACKER

    def version(self) -> str | None:
        """Names what a task can call and what its skill lists. None while the project has no
        tool history, so such a project runs exactly the packaged library."""
        if not self._path().is_file():
            return None
        content = self.block() + "\0" + self.module_source()
        return "tools@" + hashlib.sha256(content.encode()).hexdigest()[:12]

    # --- use ---------------------------------------------------------------------
    def record_usage(self, digests: list[dict]) -> dict:
        """Count each finished task once, then take unused tools off the list."""
        data = self._load()
        counted, known = set(data["counted"]), {tool["name"]: tool for tool in self.tools()}
        new = 0
        for digest in sorted(digests, key=lambda d: d.get("started_at") or ""):
            calls, available = digest.get("tool_calls"), digest.get("tools_mounted")
            if (not digest.get("finished") or digest["task_key"] in counted or calls is None
                    or available is None):
                continue  # a task recorded before calls were logged says nothing about use
            new += 1
            counted.add(digest["task_key"])
            for name in available:
                if name not in known:
                    continue
                entry = data["tools"].setdefault(name, {"source": known[name]["source"], "status": "listed"})
                stats = entry.setdefault("stats", {"tasks": 0, "tasks_called": 0, "calls": 0, "idle": 0})
                used = int(calls.get(name, 0))
                stats["tasks"] += 1
                stats["calls"] += used
                stats["tasks_called"] += bool(used)
                stats["idle"] = 0 if used else stats["idle"] + 1
        removed = []
        for name, entry in data["tools"].items():
            stats = entry.get("stats") or {}
            if (entry.get("status", "listed") == "listed" and entry.get("human") != "right"
                    and stats.get("idle", 0) >= IDLE_TASKS):
                entry["status"] = "retired" if entry.get("source") == "learned" else "unlisted"
                entry["reason"] = f"not called in {stats['idle']} tasks"
                removed.append(name)
                self._log({"tool": name, "change": entry["status"], "by": "rule", "reason": entry["reason"]})
        if new or removed:
            data["counted"] = sorted(counted)
            self._save(data)
        return {"tasks_counted": new, "removed": removed}

    def mark(self, name: str, verdict: str, *, reviewer: str) -> dict:
        """The owner's view of one tool: right keeps it listed, wrong takes it away."""
        if verdict not in VERDICTS:
            raise ValueError("verdict must be right or wrong.")
        known = {tool["name"]: tool for tool in self.tools()}
        if name not in known:
            raise ValueError("Unknown tool.")
        data = self._load()
        entry = data["tools"].setdefault(name, {"source": known[name]["source"], "status": "listed"})
        entry["human"] = verdict
        if verdict == "right":
            entry["status"] = "listed"
            entry.pop("reason", None)
        else:
            entry["status"] = "retired" if entry.get("source") == "learned" else "unlisted"
            entry["reason"] = "marked wrong by the owner"
        self._save(data)
        self._log({"tool": name, "change": f"marked {verdict}", "by": reviewer.strip() or "owner"})
        return entry

    def overview(self) -> list[dict]:
        listed = {tool["name"] for tool in self.mounted()}
        return [{**tool, "shown": tool["name"] in listed} for tool in self.tools()]

    # --- learning ----------------------------------------------------------------
    def writing_prompt(self, candidates: list[dict]) -> str:
        groups = "\n\n".join(
            f"## {c['id']} `{c['name']}`: defined in {c['uses']} code runs of the task on "
            f"\"{c['question_set'][0][:120]}\""
            + (f"; the same name in {c['other_tasks']} other tasks" if c["other_tasks"] else "")
            + "\n" + "\n\n".join(f"```python\n{example}\n```" for example in c["examples"])
            for c in candidates)
        return (WRITING_INSTRUCTIONS.format(
            alias=TOOL_ALIAS, max_new=MAX_PROPOSALS, imports=", ".join(sorted(ALLOWED_IMPORTS)),
            max_lines=MAX_TOOL_LINES, min_support=min_support())
            + "\n# The helper module now\n```python\n" + self.source().rstrip()
            + "\n```\n\n# Code the Experts wrote repeatedly\nEach entry is one function as the Experts of "
            "one task wrote it.\n\n" + groups
            + "\n\n# Your reply\nOne `### tool: <name>` section per function in the form given above, or "
            "the two words: no tools\n")

    def admit(self, raw: dict, candidates: list[dict], *, reviewer: Callable[[str], str] | None = None,
              run_test: Callable[[str, str], str | None] | None = None) -> dict:
        """Mount one proposed function, or say why not. Every gate must pass. ``run_test``
        replaces the sandboxed test run (``run_tool_test``)."""
        name, code, test = (str(raw.get(key) or "").strip() for key in ("name", "code", "test"))
        if not _NAME.fullmatch(name):
            raise ValueError("A tool needs a lower-case name of 3 to 40 letters, digits or underscores.")
        if not code or not test:
            raise ValueError("A proposal needs its function and its test, each in a code block of its own.")
        saved = self._load()
        taken = {tool["name"] for tool in describe_functions(packaged_source())} | set(saved["tools"])
        if name in taken:
            raise ValueError(f"The helper module already has, or once had, {name}.")
        check_tool_code(code, name=name)
        check_test_code(test)
        # An id names one entry; a name stands for every entry that carries it.
        named = [str(reference) for reference in dict.fromkeys(raw.get("replaces") or [])]
        replaced = [c for c in candidates if c["id"] in named or c["name"] in named]
        questions = {q for c in replaced for q in c["question_set"]}
        if len(questions) < min_support():
            raise ValueError(f"A tool must replace repeated code from {min_support()} or more questions; "
                             f"the entries it names come from {len(questions)}.")
        module = self.source().rstrip() + "\n\n\n" + code + "\n" + TRACKER
        failure = (run_test or run_tool_test)(module, test)
        if failure:
            raise ValueError(f"Its test failed: {failure}")
        if reviewer is not None:
            review = self._verdict(reviewer, REVIEW_INSTRUCTIONS.format(code=code, test=test))
            if review.get("verdict") != "accept":
                raise ValueError(f"The reviewer refused it: {str(review.get('reason') or '')[:300]}")
        described = describe_functions(code)[0]
        entry = {"source": "learned", "status": "listed", "human": None, "code": code, "test": test,
                 "signature": described["signature"], "summary": described["summary"],
                 "created_at": datetime.now(UTC).isoformat(),
                 "evidence": {"replaces": list(dict.fromkeys(c["name"] for c in replaced)),
                              "questions": len(questions),
                              "tasks": sorted({k for c in replaced for k in c["task_keys"]})},
                 "stats": {"tasks": 0, "tasks_called": 0, "calls": 0, "idle": 0}}
        saved["tools"][name] = entry
        self._save(saved)
        self._log({"tool": name, "change": "added", "by": "meta-agent",
                   "reason": str(raw.get("rationale") or "")[:600]})
        return {"name": name, **entry}

    @staticmethod
    def _verdict(reviewer: Callable[[str], str], prompt: str) -> dict:
        """The reviewer's verdict. A reply that is not the JSON asked for is asked for once more."""
        for _ in range(2):
            try:
                return parse_json_object(reviewer(prompt))
            except ValueError:
                continue
        raise ValueError("The reviewer's reply could not be read, so the function was not reviewed.")

    @staticmethod
    def _refusal(raw: dict, reason: str, attempt: int) -> dict:
        """One refused proposal as the owner can read it: what was proposed, and why not."""
        return {"name": raw["name"][:60], "reason": reason, "round": attempt, "code": raw["code"][:4000],
                "test": raw["test"][:4000], "replaces": [item[:60] for item in raw["replaces"]][:40]}

    @staticmethod
    def _refused_section(refused: list[dict]) -> str:
        """What the meta-agent is told about the proposals a gate refused, to correct them once."""
        if not refused:
            return ""
        return REVISION_INSTRUCTIONS + "".join(
            f"\n### tool: {r['name']}\nrefused: {r['reason']}\nreplaces: {', '.join(r['replaces'])}\n"
            f"```python\n{r['code']}\n```\n```python\n{r['test']}\n```\n" for r in refused)

    @staticmethod
    def _proposals(llm: Callable[[str], str], prompt: str, rejected: list[dict], attempt: int) -> list[dict] | None:
        """What one round proposes; None when the reply could not be read. Such a reply is asked
        for once more, and the start of each is kept so that the owner can see what came back."""
        for _ in range(2):
            reply = llm(prompt)
            try:
                return read_proposals(reply)
            except ValueError as exc:
                rejected.append({"name": "", "reason": f"The meta-agent's reply could not be read: {exc}",
                                 "round": attempt, "reply": reply[:REPLY_KEPT]})
        return None

    def learn(self, llm: Callable[[str], str], stores: list[Path], *,
              reviewer: Callable[[str], str] | None = None,
              run_test: Callable[[str, str], str | None] | None = None, force: bool = False) -> dict:
        """Ask the meta-agent for functions that replace repeated code; mount those that pass.
        A proposal a gate refuses goes back once with the reason, so that a weak test or an
        incomplete list of what it replaces can be put right; the gates themselves do not move.

        The step keeps its own list of the tasks whose code it has read and runs when a task
        finished since (or with ``force``). The list is not brought up to date when the first
        reply could not be read, so the next update tries again."""
        digests = self.memory.load_digests()
        finished = {d["task_key"] for d in digests if d.get("finished")}
        path = self.root / "learn_state.json"
        seen = set(json.loads(path.read_text(encoding="utf-8")).get("tasks", [])) if path.is_file() else set()
        created, rejected = [], []
        result = {"created": [], "rejected": rejected, "candidates": 0, "new_tasks": len(finished - seen)}
        if not result["new_tasks"] and not force:
            return result
        candidates = repeated_functions(stores, {d["task_key"]: d.get("question") or "" for d in digests})
        result["candidates"], read = len(candidates), True
        # A tool may replace several entries; with code from fewer questions nothing could pass.
        if len({q for c in candidates for q in c["question_set"]}) >= min_support():
            refused: list[dict] = []
            for attempt in (1, 2):
                proposals = self._proposals(
                    llm, self.writing_prompt(candidates) + self._refused_section(refused), rejected, attempt)
                if proposals is None:
                    read = attempt > 1  # nothing came of the first round: the tasks stay unread
                    break
                made = {tool["name"] for tool in created}
                refused = []
                for raw in [raw for raw in proposals if raw["name"] not in made][:MAX_PROPOSALS]:
                    if len(created) >= MAX_NEW_PER_REVIEW:
                        break
                    try:
                        created.append(self.admit(raw, candidates, reviewer=reviewer, run_test=run_test))
                    except ValueError as exc:
                        refused.append(self._refusal(raw, str(exc), attempt))
                rejected += refused
                if not refused or len(created) >= MAX_NEW_PER_REVIEW:
                    break
        if read:
            atomic_write_text(path, json.dumps({"at": datetime.now(UTC).isoformat(), "tasks": sorted(finished)}))
        result["created"] = [tool["name"] for tool in created]
        return result


__all__ = ["IDLE_TASKS", "MODULE", "PROBATION_TASKS", "SKILL", "TOOL_LOG_ENV", "ToolBook",
           "check_test_code", "check_tool_code", "packaged_source", "read_proposals",
           "repeated_functions", "run_tool_test"]
