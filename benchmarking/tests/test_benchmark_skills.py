"""The figure guidance that only benchmark runs get, installed without changing OceanX itself."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import benchmark_skills
import pytest

from oceanx import native_skills, runtime, skills
from oceanx.native_skills import prepare_skill_library

FIGURE_DELIVERY_ENV = "OCEANX_FIGURE_DELIVERY"
NAME = "scientific-figure-style"
# What a benchmark run must never show a model: OceanX's plotting interface and how it publishes.
INTERFACE_NAMES = ("ScientificFigure", "Figure API", "result-api", "Published results", "bracket", "Workbench",
                   ".preview.png", "oceanx", "OceanX")


@pytest.fixture
def restored(monkeypatch):
    """Whatever a test installs is taken out again."""
    monkeypatch.setattr(skills, "ocean_skill_dirs", skills.ocean_skill_dirs)
    monkeypatch.setattr(native_skills, "ocean_skill_dirs", native_skills.ocean_skill_dirs)
    monkeypatch.setattr(runtime, "STATIC_EXPERT_WORKSTREAM_POLICY", runtime.STATIC_EXPERT_WORKSTREAM_POLICY)
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, "static")


def skill_names(library: Path) -> set[str]:
    return {path.name for path in (library / "skills").iterdir()}


def test_oceanx_itself_has_no_such_skill_and_no_pointer_to_it(restored, tmp_path):
    assert NAME not in {skill.name for skill in skills.ocean_skill_metadata()}
    assert NAME not in skill_names(prepare_skill_library(tmp_path, role="ocean_process_expert"))
    assert NAME not in runtime.STATIC_EXPERT_WORKSTREAM_POLICY


@pytest.mark.parametrize("role, given", [
    ("ocean_process_expert", True), ("statistical_inference_expert", True),
    ("coordinator", False), ("literature_reproduction_expert", False)])
def test_after_install_the_data_experts_of_a_static_run_get_the_skill(restored, tmp_path, role, given):
    before = skill_names(prepare_skill_library(tmp_path / "before", role=role))

    assert benchmark_skills.install_benchmark_skills() == [NAME]

    after = skill_names(prepare_skill_library(tmp_path / "after", role=role))
    assert after == (before | {NAME} if given else before)
    # The interactive plotting skill stays out of a static run, as before.
    assert "scientific-figure-design" not in after


def test_the_skill_names_no_plotting_interface_and_keeps_the_guidance(restored, tmp_path):
    benchmark_skills.install_benchmark_skills()
    library = prepare_skill_library(tmp_path, role="ocean_process_expert")
    text = (library / "skills" / NAME / "SKILL.md").read_text(encoding="utf-8")
    assert not [name for name in INTERFACE_NAMES if name in text]
    # What OceanX's own figure skill says apart from its interface: the figure follows the claim
    # and the colour scale follows the meaning of the variable.
    assert "a map of the field itself" in text and "A relation between two quantities" in text
    assert "limits symmetric about that centre" in text and "Never `jet`" in text
    assert "stay missing" in text and "label with units" in text


def test_the_static_expert_policy_points_to_the_skill_once_and_the_interactive_one_never(restored):
    interactive = runtime.OCEAN_EXPERT_WORKSTREAM_POLICY
    original = runtime.STATIC_EXPERT_WORKSTREAM_POLICY

    benchmark_skills.install_benchmark_skills()
    benchmark_skills.install_benchmark_skills()  # a second call changes nothing

    assert runtime.STATIC_EXPERT_WORKSTREAM_POLICY == original + benchmark_skills.POINTER
    assert "Read the scientific-figure-style skill before your first final figure." in benchmark_skills.POINTER
    assert runtime.OCEAN_EXPERT_WORKSTREAM_POLICY == interactive and NAME not in interactive
    folders = skills.ocean_skill_dirs()
    assert folders.count(benchmark_skills.SKILLS) == 1 and folders[-1] == benchmark_skills.SKILLS


def test_the_packaged_helper_module_is_still_found_first(restored):
    from oceanx.research.toolbook import packaged_source

    before = packaged_source()
    benchmark_skills.install_benchmark_skills()
    assert packaged_source() == before and "def weighted_mean" in before


def test_nothing_is_installed_outside_a_static_run(restored, monkeypatch, tmp_path):
    monkeypatch.delenv(FIGURE_DELIVERY_ENV)
    folders, policy = skills.ocean_skill_dirs, runtime.STATIC_EXPERT_WORKSTREAM_POLICY

    assert benchmark_skills.install_benchmark_skills() == []

    assert skills.ocean_skill_dirs is folders and native_skills.ocean_skill_dirs is folders
    assert runtime.STATIC_EXPERT_WORKSTREAM_POLICY == policy
    assert NAME not in skill_names(prepare_skill_library(tmp_path, role="ocean_process_expert"))


def test_install_stops_when_oceanx_loads_skills_differently(restored, monkeypatch):
    monkeypatch.setattr(native_skills, "ocean_skill_dirs", lambda *, capabilities=(): ())
    with pytest.raises(RuntimeError, match="skill loading changed"):
        benchmark_skills.install_benchmark_skills()


def test_the_example_in_the_skill_runs_as_written(tmp_path, monkeypatch):
    import matplotlib
    matplotlib.use("Agg")

    content = (benchmark_skills.SKILLS / NAME / "SKILL.md").read_text(encoding="utf-8")
    (example,) = re.findall(r"```python\n(.*?)```", content, flags=re.DOTALL)
    monkeypatch.chdir(tmp_path)
    exec(compile(example, "scientific-figure-style example", "exec"), {})  # noqa: S102 - the benchmark's own example
    assert (tmp_path / "sst-anomaly-2023.png").stat().st_size > 10_000


def test_the_arm_record_names_the_benchmark_skills():
    assert benchmark_skills.benchmark_skill_names() == [NAME]


@pytest.mark.parametrize("delivery, expected", [("static", [NAME]), (None, [])])
def test_the_real_agent_server_child_installs_the_skill_for_a_static_run(tmp_path, delivery, expected):
    """Real runner -> production gateway -> real child, with only the HTTP server stubbed.

    The stub stands where the server would start serving and records what a data Expert of this
    process would be given.
    """
    root = Path(__file__).resolve().parents[2]
    server = root / "benchmarking/server"
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY=benchmark-flash-key\nBENCH_MODEL=deepseek-flash\n")
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    stub = tmp_path / "stub" / "langgraph_api"
    stub.mkdir(parents=True)
    (stub / "__init__.py").write_text("")
    (stub / "cli.py").write_text('''
import json
from pathlib import Path

def run_server(**kwargs):
    from oceanx import runtime
    from oceanx.native_skills import prepare_skill_library
    library = prepare_skill_library(Path("skill-library"), role="ocean_process_expert")
    Path("observed-skills.json").write_text(json.dumps({
        "skills": sorted(path.name for path in (library / "skills").iterdir()),
        "policy": runtime.STATIC_EXPERT_WORKSTREAM_POLICY}))
''')
    env = {**os.environ, "OCEANMIND_CONFIG_DIR": str(tmp_path / "desktop"),
           "OCEAN_BENCH_CONFIG": str(env_file),
           "PYTHONPATH": os.pathsep.join([str(stub.parent), str(server), str(root / "src"),
                                          os.environ.get("PYTHONPATH", "")]),
           "NO_PROXY": "127.0.0.1,localhost"}
    env.pop(FIGURE_DELIVERY_ENV, None)
    if delivery:
        env[FIGURE_DELIVERY_ENV] = delivery
    process = subprocess.Popen([sys.executable, str(server / "run_oceanx.py"), "--backend", str(attempt)],
                               env=env, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _stdout, stderr = process.communicate(timeout=60)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    assert "Agent Server failed to start" in stderr  # the stub does not serve; what it saw is the assertion
    observed = json.loads((attempt / "state/observed-skills.json").read_text())
    record = json.loads((attempt / "model_protocol.json").read_text())
    assert record["benchmark_skills"] == expected
    assert (NAME in observed["skills"]) is bool(expected)
    assert ("scientific-figure-style skill" in observed["policy"]) is bool(expected)
    assert "xarray-array-ops" in observed["skills"]
