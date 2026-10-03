"""Run OceanX through its production Agent Server path, as one experimental arm.

The scientific query is submitted unchanged, without a research-tree instruction. All model roles use the
benchmarking/.env API configuration inside the actual Agent Server subprocess. Every arm runs the default research policy
unless --policy selects another; an arm fixes an optional frozen library (lessons and tools). Nothing is
learned during the run, and every attempt checks that.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from oceanx import __version__, batch

_original_interaction_answer = batch.interaction_answer
REPO = Path(__file__).resolve().parents[2]
# Set by main() for this process: the frozen library snapshot copied into every attempt, if any.
LIBRARY: Path | None = None


def file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def git_identity() -> dict:
    def git(*args):
        result = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    status = git("status", "--porcelain", "--untracked-files=no")
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(status) if status is not None else None}


def project_library(state: Path):
    """The lessons and tools of the OceanX state folder an attempt's backend runs on."""
    from oceanx.research.review import ProjectResearch
    return ProjectResearch(SimpleNamespace(root=state))


def snapshot_version(snapshot: Path) -> str | None:
    """The same content version OceanX records on tree events, whatever the snapshot folder is called."""
    import tempfile
    with tempfile.TemporaryDirectory() as temporary:
        project = project_library(Path(temporary))
        project.install(snapshot)
        return project.version()


def install_library(attempt: Path) -> dict:
    """Copy the frozen lessons and tools into the attempt's own state before its backend starts."""
    return {"snapshot": str(LIBRARY), "sha256_before": project_library(attempt / "state").install(LIBRARY)}


def oceanx_prompt(case):
    return case.query


def benchmark_interaction_answer(case, payload):
    if payload.get("kind") == "paper_selection":
        return json.dumps({"selected_paper_ids": [
            option["paper_id"] for option in payload.get("options", [])
        ]})
    return _original_interaction_answer(case, payload)


def backend_environment(case) -> dict:
    """The case's time limit is also the research budget, so the Coordinator stops starting new
    questions in time to deliver an answer before the attempt is cut off."""
    from oceanx.research.graphs import RESEARCH_BUDGET_ENV
    env = dict(os.environ)
    if case.timeout_seconds:
        env[RESEARCH_BUDGET_ENV] = str(round(case.timeout_seconds / 60, 1))
    return env


class BenchmarkClient(batch.BatchClient):
    # A benchmark attempt must keep its agents' conversations, so let the server finish writing them.
    shutdown_seconds = 120

    async def send(self, kind, payload):
        if kind == "session.submit":
            payload = {**payload, "text": oceanx_prompt(self.case)}
            (self.directory / "submitted_prompt.txt").write_text(payload["text"], encoding="utf-8")
        return await super().send(kind, payload)

    async def start(self):
        write_arm(self.directory)
        if LIBRARY is not None:
            batch._write_json(self.directory / "arm_library.json", install_library(self.directory))
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).resolve()), "--backend",
            str(self.directory.resolve()),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=batch._LOG_LIMIT,
            start_new_session=os.name == "posix", env=backend_environment(self.case),
        )
        self.stderr_task = asyncio.create_task(self._drain_stderr())
        await self.request("system.handshake", {
            "client_kind": "desktop", "client_version": __version__,
            "supported_protocol_versions": [2],
        })
        self.context["workspace_id"] = f"ws_batch_{uuid4().hex}"
        workspace = self.directory / "workspace"
        workspace.mkdir()
        await self.request("workspace.open", {"path": str(workspace)})
        task = await self.request("task.create", {"title": self.case.id})
        self.context["task_id"] = task["payload"]["result"]["task"]["task_id"]
        for path in self.case.datasets:
            await self.request("dataset.import", {
                "local_path": str(path), "materialization_level": "local_reference",
            })

    async def close(self):
        await super().close()
        record = self.directory / "arm_library.json"
        if LIBRARY is not None and record.exists():
            # Proof that the lessons and tools did not change while this attempt ran.
            saved = json.loads(record.read_text())
            after = project_library(self.directory / "state").library_hashes()
            batch._write_json(record, {**saved, "sha256_after": after, "unchanged": after == saved["sha256_before"]})


# This process's arm record; written into the output folder when the first attempt starts.
ARM: dict = {}


def library_versions() -> dict:
    """The libraries whose formats the saved conversation checkpoints depend on."""
    from importlib import metadata
    versions = {}
    for name in ("langgraph", "langgraph-api", "langgraph-runtime-inmem", "langgraph-checkpoint",
                 "deepagents", "langchain-core"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def arm_record(args) -> dict:
    from oceanx.research.policy import active_policy
    from oceanx.research.review import LIBRARY_FILES
    # The policy every backend subprocess will run: --policy if given, otherwise the default.
    return {"arm": args.arm, "policy": active_policy().name, "oceanx_version": __version__, **git_identity(),
            "libraries": library_versions(),
            "library": None if LIBRARY is None else {
                "snapshot": str(LIBRARY), "version": snapshot_version(LIBRARY),
                "sha256": {name: file_sha256(LIBRARY / name) for name in LIBRARY_FILES}},
            "queries": str(args.queries) if args.queries else None,
            "max_parallel_experts": os.environ.get("OCEANX_MAX_PARALLEL_EXPERTS", "2")}


def check_arm(output: Path) -> None:
    """A resumed output folder must belong to the same arm."""
    path = output / "arm.json"
    if path.exists():
        prior = json.loads(path.read_text())
        if {k: prior.get(k) for k in ("arm", "policy", "library")} != {k: ARM[k] for k in ("arm", "policy", "library")}:
            raise SystemExit("ERROR: this output folder belongs to a different arm; use a new --output")


def write_arm(attempt: Path) -> None:
    path = attempt.parents[1] / "arm.json"  # <output>/<case>/<attempt>
    if not path.exists():
        batch._write_json(path, {**ARM, "started_utc": dt.datetime.now(dt.UTC).isoformat()})


def main(argv=None):
    if argv is None and len(sys.argv) == 3 and sys.argv[1] == "--backend":
        from benchmark_models import run_oceanx_gateway

        attempt = Path(sys.argv[2]).resolve()
        asyncio.run(run_oceanx_gateway(attempt / "state"))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    query_input = parser.add_mutually_exclusive_group()
    query_input.add_argument("--queries", type=Path)
    query_input.add_argument("--query", help="A single ad-hoc test question")
    parser.add_argument("--dataset", action="append", default=[], type=Path)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true", default=None)
    parser.add_argument("--config", type=Path, help="benchmarking/.env by default")
    parser.add_argument("--arm", help="Arm label recorded in arm.json, e.g. B or C1")
    parser.add_argument("--policy", help="Research policy for every case; the default (v2-nested) when omitted")
    parser.add_argument("--library", "--lessons", dest="library", type=Path,
                        help="Frozen library snapshot (lessons.json and tools.json, made by "
                             "research_cli.py snapshot); copied into every attempt")
    args = parser.parse_args(argv)
    from benchmark_config import load_config, preflight
    from benchmark_run import configure_run
    config = load_config(args.config)
    config.endpoint(config.oceanx_api)
    args.config = config.source
    os.environ["OCEAN_BENCH_CONFIG"] = str(config.source)
    configure_run(args, config, 'OceanX')
    from oceanx.research.review import LIBRARY_FILES, LIBRARY_FROZEN_ENV
    global LIBRARY
    LIBRARY = None
    # Nothing is learned while a benchmark runs: no attempt reviews its lessons or counts tool calls
    # into its library. Learning is a separate step on the evolution project (research_cli.py).
    os.environ[LIBRARY_FROZEN_ENV] = "1"  # inherited by every backend subprocess
    from oceanx.research.policy import DEFAULT_POLICY, POLICY_ENV, find_policy
    args.policy = args.policy or DEFAULT_POLICY
    find_policy(args.policy)  # fail before any model call on an unknown name
    os.environ[POLICY_ENV] = args.policy  # ignore stale shell policy, inherited by every backend subprocess
    if args.library:
        LIBRARY = args.library.expanduser().resolve()
        if not any((LIBRARY / name).is_file() for name in LIBRARY_FILES):
            parser.error("--library must be a folder containing lessons.json or tools.json")
    ARM.update(arm_record(args))
    check_arm(args.output.expanduser().resolve())
    preflight(require_sandbox=True)
    if args.queries and args.dataset:
        parser.error("Use --dataset with --query; JSONL cases contain their own datasets")
    cases = batch.load_queries(args.queries) if args.queries else [
        batch.resolve_datasets(batch.QueryCase(
            id="QUERY", query=args.query, datasets=args.dataset, timeout_seconds=args.timeout,
        ), Path.cwd())
    ]
    # This process and its dedicated children only; the installed OceanX entrypoint is untouched.
    batch.BatchClient = BenchmarkClient
    batch.interaction_answer = benchmark_interaction_answer
    try:
        results = asyncio.run(batch.run_batch(
            cases, args.output, resume=args.resume
        ))
    finally:
        from collect_oceanx import collect_run

        if args.output.exists() and any(args.output.glob("*/attempt-*/result.json")):
            try:
                print(f"Collected results: {collect_run(args.output)}", file=sys.stderr)
            except (OSError, ValueError, KeyError) as exc:
                print(f"Result collection failed: {exc}", file=sys.stderr)
    raise SystemExit(0 if all(item["status"] == "completed" for item in results) else 1)


if __name__ == "__main__":
    main()
