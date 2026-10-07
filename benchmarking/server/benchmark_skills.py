"""Skills that only benchmark runs of OceanX get.

OceanX's own code and packaged skills are not changed. The benchmark's Agent Server process
(benchmark_agent_server.py) adds the folder ``benchmarking/skills`` to the folders skills are
loaded from, and one sentence to the Expert policy of static-figure runs that points to it. The
desktop never runs this code.

``scientific-figure-style`` is the part of OceanX's ``scientific-figure-design`` that does not
depend on the interactive plotting interface (the figure follows the claim, the colour scale
follows the variable's meaning), written for matplotlib image files. A benchmark run does not get
``scientific-figure-design`` itself, because every arm delivers ordinary image files.
"""
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "skills"
POINTER = ("Read the scientific-figure-style skill before your first final figure. A conclusion about "
           "where something is needs a map or section of the field itself.\n")
_INSTALLED = "_benchmark_skill_folders"


def benchmark_skill_names() -> list[str]:
    return sorted(path.parent.name for path in SKILLS.glob("*/SKILL.md"))


def install_benchmark_skills() -> list[str]:
    """Make the benchmark's skills loadable in this process and return their names.

    Nothing is installed, and the list is empty, unless figures are delivered as image files.
    """
    from oceanx import native_skills, runtime, skills
    from oceanx.figure_delivery import static_figures

    if not static_figures():
        return []  # these skills are about ordinary image files; run_oceanx.py sets static delivery
    packaged = skills.ocean_skill_dirs
    if getattr(packaged, _INSTALLED, False):
        return benchmark_skill_names()
    if native_skills.ocean_skill_dirs is not packaged or not isinstance(
            getattr(runtime, "STATIC_EXPERT_WORKSTREAM_POLICY", None), str):
        raise RuntimeError("OceanX skill loading changed; update benchmarking/server/benchmark_skills.py")

    def with_benchmark_skills(*, capabilities=()):
        # The packaged folders stay first: other code takes the helper module from the first one.
        return (*packaged(capabilities=capabilities), SKILLS)

    setattr(with_benchmark_skills, _INSTALLED, True)
    skills.ocean_skill_dirs = native_skills.ocean_skill_dirs = with_benchmark_skills
    runtime.STATIC_EXPERT_WORKSTREAM_POLICY = runtime.STATIC_EXPERT_WORKSTREAM_POLICY.rstrip("\n") + "\n" + POINTER
    return benchmark_skill_names()
