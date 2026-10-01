"""Run OceanX through its production Agent Server path, as one experimental arm.

The scientific query is submitted unchanged, without a research-tree instruction. All model roles use the
root benchmark.yaml API configuration in this process only. An arm fixes the research policy and an
optional frozen lesson snapshot; nothing evolves during the run, and every attempt checks that.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from oceanx import __version__, batch

_original_interaction_answer = batch.interaction_answer
REPO = Path(__file__).resolve().parents[2]
# Set by main() for this process: the frozen lesson snapshot copied into every attempt, if any.
LESSONS: Path | None = None


def file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def git_identity() -> dict:
    def git(*args):
        result = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    status = git("status", "--porcelain", "--untracked-files=no")
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(status) if status is not None else None}


def lessons_version(snapshot: Path) -> str | None:
    """The same content version OceanX records on tree events, whatever the snapshot folder is called."""
    import tempfile

    from oceanx.research.lessons import LessonBook
    from oceanx.research.memory import ResearchMemory
    with tempfile.TemporaryDirectory() as temporary:
        (Path(temporary) / "lessons").mkdir()
        shutil.copyfile(snapshot / "lessons.json", Path(temporary) / "lessons" / "lessons.json")
        return LessonBook(ResearchMemory(Path(temporary))).version()


def install_lessons(attempt: Path) -> dict:
    """Copy the frozen lessons into the attempt's own state before its backend starts."""
    from oceanx.research.lessons import LessonBook
    from oceanx.research.memory import ResearchMemory
    research = attempt / "state" / "research"
    (research / "lessons").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LESSONS / "lessons.json", research / "lessons" / "lessons.json")
    LessonBook(ResearchMemory(research)).render_skills()
    return {"snapshot": str(LESSONS), "sha256_before": file_sha256(research / "lessons" / "lessons.json")}


def oceanx_prompt(case):
    return case.query


def benchmark_interaction_answer(case, payload):
    if payload.get("kind") == "paper_selection":
        return json.dumps({"selected_paper_ids": [
            option["paper_id"] for option in payload.get("options", [])
        ]})
    return _original_interaction_answer(case, payload)


class BenchmarkClient(batch.BatchClient):
    async def send(self, kind, payload):
        if kind == "session.submit":
            payload = {**payload, "text": oceanx_prompt(self.case)}
            (self.directory / "submitted_prompt.txt").write_text(payload["text"], encoding="utf-8")
        return await super().send(kind, payload)

    async def start(self):
        write_arm(self.directory)
        if LESSONS is not None:
            batch._write_json(self.directory / "arm_lessons.json", install_lessons(self.directory))
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).resolve()), "--backend",
            str(self.directory.resolve()),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=batch._LOG_LIMIT,
            start_new_session=os.name == "posix",
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
        record = self.directory / "arm_lessons.json"
        if LESSONS is not None and record.exists():
            # Proof that the lesson set did not change while this attempt ran.
            saved = json.loads(record.read_text())
            after = file_sha256(self.directory / "state" / "research" / "lessons" / "lessons.json")
            batch._write_json(record, {**saved, "sha256_after": after, "unchanged": after == saved["sha256_before"]})


# This process's arm record; written into the output folder when the first attempt starts.
ARM: dict = {}


def arm_record(args) -> dict:
    return {"arm": args.arm, "policy": args.policy, "oceanx_version": __version__, **git_identity(),
            "lessons": None if LESSONS is None else {"snapshot": str(LESSONS), "version": lessons_version(LESSONS),
                                                    "sha256": file_sha256(LESSONS / "lessons.json")},
            "queries": str(args.queries) if args.queries else None,
            "max_parallel_experts": os.environ.get("OCEANX_MAX_PARALLEL_EXPERTS", "2")}


def check_arm(output: Path) -> None:
    """A resumed output folder must belong to the same arm."""
    path = output / "arm.json"
    if path.exists():
        prior = json.loads(path.read_text())
        if {k: prior.get(k) for k in ("arm", "policy", "lessons")} != {k: ARM[k] for k in ("arm", "policy", "lessons")}:
            raise SystemExit("ERROR: this output folder belongs to a different arm; use a new --output")


def write_arm(attempt: Path) -> None:
    path = attempt.parents[1] / "arm.json"  # <output>/<case>/<attempt>
    if not path.exists():
        batch._write_json(path, {**ARM, "started_utc": dt.datetime.now(dt.UTC).isoformat()})


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--backend":
        from benchmark_models import install_oceanx_models

        model_policy = install_oceanx_models()

        from oceanx.cli import app

        attempt = Path(sys.argv[2]).resolve()
        batch._write_json(attempt / "model_protocol.json", model_policy)
        app(args=["backend", "--state-dir", str(attempt / "state")])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    query_input = parser.add_mutually_exclusive_group(required=True)
    query_input.add_argument("--queries", type=Path)
    query_input.add_argument("--query", help="A single ad-hoc test question")
    parser.add_argument("--dataset", action="append", default=[], type=Path)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--config", type=Path, help="Root benchmark.yaml by default")
    parser.add_argument("--arm", default="default", help="Arm label recorded in arm.json, e.g. A_v0")
    parser.add_argument("--policy", help="Research policy for every case, e.g. v0-coordinator-bfs or v2-nested")
    parser.add_argument("--lessons", type=Path,
                        help="Frozen lesson snapshot folder containing lessons.json; copied into every attempt")
    args = parser.parse_args()
    global LESSONS
    if args.policy:
        from oceanx.research.policy import POLICY_ENV, find_policy
        find_policy(args.policy)  # fail before any model call on an unknown name
        os.environ[POLICY_ENV] = args.policy  # inherited by every backend subprocess
    if args.lessons:
        LESSONS = args.lessons.expanduser().resolve()
        if not (LESSONS / "lessons.json").is_file():
            parser.error("--lessons must be a folder containing lessons.json")
    ARM.update(arm_record(args))
    check_arm(args.output.expanduser().resolve())
    from benchmark_config import DEFAULT_CONFIG, load_config, preflight
    config_path = (args.config or DEFAULT_CONFIG).expanduser().resolve()
    config = load_config(config_path)
    config.endpoint(config.oceanx_api)
    os.environ["OCEAN_BENCH_CONFIG"] = str(config_path)
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
