"""`ocean research ...`: labels, the learned library, cleanup and paired policy experiments.

Every command here is run by a human. Nothing in this module runs inside a research
task, and none of it is available to research agents as a tool.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer

research_app = typer.Typer(help="Research-tree labels, lessons, tools and policy experiments.",
                           no_args_is_help=True)


def _echo(value) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _tree(path: Path):
    from oceanx.research.tree import ResearchTree
    path = path.expanduser().with_suffix(".json")
    if not path.with_suffix(".sqlite3").exists() and not path.exists():
        raise typer.BadParameter(f"No research tree at {path}.")
    return ResearchTree(path)


def _project(project: Path):
    from oceanx.research.review import ProjectResearch
    from oceanx.storage import OceanPaths
    return ProjectResearch(OceanPaths.for_project(project.expanduser()))


@research_app.command("show")
def show(tree: Path = typer.Option(..., "--tree", help="research_tree.json or .sqlite3")) -> None:
    """Print the full tree with outcomes and labels."""
    from oceanx.research.tree_view import render_full
    handle = _tree(tree)
    typer.echo(render_full(handle.document(), include_history=True))
    _echo({"outcomes": handle.store.outcomes(), "labels": handle.store.labels()})


@research_app.command("label")
def label(
    tree: Path = typer.Option(..., "--tree"),
    node: str = typer.Option(..., "--node"),
    value: str = typer.Option(..., "--label", help="decision-changing | "
                              "informative-but-not-decisive | misleading-or-wasteful"),
    labeler: str = typer.Option(..., "--labeler"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """Record a human label for one node (append-only)."""
    try:
        _tree(tree).label(node, value, labeler=labeler, note=note)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"labelled {node}: {value}")


@research_app.command("judge-labels")
def judge(tree: Path = typer.Option(..., "--tree"),
          model_role: str = typer.Option("meta", "--model-role")) -> None:
    """Leave-one-out labels from the meta model for executed nodes without a human label."""
    from oceanx.research.labels import judge_labels
    from oceanx.research.llm import default_llm
    handle = _tree(tree)
    report = handle.path.with_name("report.md")
    _echo(judge_labels(handle, default_llm(model_role),
                       final_report=report.read_text(encoding="utf-8") if report.exists() else ""))


@research_app.command("judge-agreement")
def agreement(runs: list[Path] = typer.Option(..., "--runs")) -> None:
    """How often the model judge matches human labels (can it replace the owner?)."""
    from oceanx.research.labels import judge_agreement
    from oceanx.research.memory import find_stores
    _echo(judge_agreement(find_stores(runs)))


@research_app.command("freeze-acceptance")
def freeze_acceptance(owner: str = typer.Option(..., "--owner")) -> None:
    """Validate and hash-lock the acceptance criteria before paired runs."""
    from oceanx.research import acceptance
    try:
        _echo(acceptance.freeze(owner=owner))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@research_app.command("pairs")
def paired_runs(
    queries: Path = typer.Option(..., "--queries", exists=True, dir_okay=False),
    output: Path = typer.Option(..., "--output"),
    policy_a: str = typer.Option(..., "--policy-a"),
    policy_b: str = typer.Option(..., "--policy-b"),
    seed: int = typer.Option(0, "--seed"),
) -> None:
    """Run held-out cases under two policies in randomised order (costs model usage)."""
    from oceanx.research.paired_runs import run_pairs_sync
    _echo(run_pairs_sync(queries, output, policy_a=policy_a, policy_b=policy_b, seed=seed))


@research_app.command("evaluate-pairs")
def evaluate_paired_runs(
    output: Path = typer.Option(..., "--output"),
    quality: Path = typer.Option(..., "--quality", exists=True,
                                 help="JSONL of {case, better: A|B|same}, one per case."),
) -> None:
    """Apply the frozen acceptance criteria to rated paired runs."""
    from oceanx.research.paired_runs import evaluate_pairs
    _echo(evaluate_pairs(output, quality_file=quality))


@research_app.command("consolidate")
def consolidate(
    project: Path = typer.Option(..., "--project", help="Project folder containing .oceanx/"),
    retention_days: int = typer.Option(30, "--retention-days", min=1),
    review: bool = typer.Option(False, "--review",
                                help="Also let the meta-agent review the lessons and learn tools."),
    force: bool = typer.Option(False, "--force", help="Review even if no task finished since the last one."),
    model_role: str = typer.Option("meta", "--model-role"),
) -> None:
    """Digest research trees, archive raw records past retention and count tool calls; with
    --review the meta-agent updates the project's lessons and tools (model calls)."""
    from oceanx.research.memory import find_stores
    llm = None
    if review:
        from oceanx.research.llm import default_llm
        llm = default_llm(model_role)
    _echo(_project(project).update(find_stores([project.expanduser()]), llm=llm, reviewer=llm,
                                   force=force, retention_days=retention_days))


@research_app.command("library")
def library(project: Path = typer.Option(..., "--project")) -> None:
    """Show the project's lessons and tools, with their evidence and call counts."""
    _echo(_project(project).overview())


@research_app.command("mark")
def mark(
    project: Path = typer.Option(..., "--project"),
    kind: str = typer.Option(..., "--kind", help="lesson | tool"),
    item: str = typer.Option(..., "--id", help="A lesson id such as L003, or a tool name."),
    right: bool = typer.Option(..., "--right/--wrong"),
    reviewer: str = typer.Option(..., "--reviewer"),
) -> None:
    """The owner's view of one lesson or tool: right keeps it, wrong removes it."""
    try:
        _project(project).mark(kind, item, "right" if right else "wrong", reviewer=reviewer)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"marked {kind} {item}: {'right' if right else 'wrong'}")


@research_app.command("snapshot")
def snapshot(
    project: Path = typer.Option(..., "--project"),
    output: Path = typer.Option(..., "--output", help="New folder for the frozen lessons and tools."),
) -> None:
    """Freeze the project's lessons and tools as a folder an experiment arm can run with."""
    try:
        _echo(_project(project).snapshot(output.expanduser()))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


__all__ = ["research_app"]
