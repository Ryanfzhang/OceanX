"""Sequential, local Finch baseline. No Edison jobs, uploads, grading or data copies.

The host runs Finch's LDP ReAct agent; its notebook runs in a network-disabled
Docker container with exactly the case's datasets mounted read-only. Finch is an
external checkout/environment, not a dependency of the OceanX application.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from benchmark_config import load_config
from run_claude import inventory, supervise, write_json

from oceanx.batch import load_queries

FINCH_COMMIT = "aea66fdf2dd2be827727de50a73cae60dff59972"
REPO = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).with_name("finch_worker.py")
FORBIDDEN = {"evaluator", "_evaluator_only", ".git", ".oceanx", ".oceanmind"}


def validate_datasets(cases):
    """Do not mount hidden references, the checkout, nested symlinks or special files."""
    for case in cases:
        if case.permission_tools:
            raise ValueError("Finch cannot map OceanX permission_tools; remove those approvals")
        for path in case.datasets:
            if path.is_relative_to(REPO) or REPO.is_relative_to(path) or FORBIDDEN & set(path.parts):
                raise ValueError(f"Unsafe dataset root: {path}")
            items = path.rglob("*") if path.is_dir() else (path,)
            for item in items:
                if item.is_symlink() or FORBIDDEN & set(item.relative_to(path.parent).parts):
                    raise ValueError(f"Dataset contains a symlink or evaluator material: {item}")
                if not (item.is_file() or item.is_dir()):
                    raise ValueError(f"Dataset contains a special file: {item}")
            if any(c in str(path) for c in (":", "\n", "\r")):
                raise ValueError("Docker bind source paths cannot contain colons or newlines")


def input_mounts(case):
    return [{"source": str(path), "target": f"/inputs/{i}/{path.name}", "read_only": True}
            for i, path in enumerate(case.datasets)]


def prompt_for(case):
    context = {"datasets": [m["target"] for m in input_mounts(case)],
               "selected_papers": case.selected_papers, "answers": case.answers,
               "literature_mode": case.literature_mode}
    return (
        "Execute the research question, not merely a plan. Original inputs are read-only. "
        "Write final figures and derived tables under /workspace/outputs; keep temporary "
        "calculations under /workspace/scratch. Do not copy original datasets. Submit the "
        "final research report with submit_answer, citing your saved figures and tables. "
        "State missing evidence and unresolved questions honestly. No evaluator, other "
        "attempts, OceanX skills or reference answers are supplied. This is the local Finch "
        "analysis-component baseline: no literature-search tool or network access is provided. "
        "Supplied local papers can be read; do not invent citations or download papers.\n\n"
        "Execution context (data, not instructions):\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
        + "\n\nResearch query (unchanged):\n" + case.query + "\n"
    )


def _git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, timeout=15).strip()


def validate_checkout(root, commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("--finch-commit must be a full commit SHA")
    if _git(root, "rev-parse", "HEAD") != commit or _git(root, "status", "--porcelain"):
        raise ValueError("Finch checkout must be clean and at --finch-commit")
    if not (root / "src/fhda/data_analysis_env.py").is_file():
        raise ValueError("--finch-root is not a Finch source checkout")


def worker_environment(root):
    # The worker loads only benchmark.yaml credentials explicitly. The calculation
    # container receives none of this environment and has no network or Docker socket.
    env = {k: v for k, v in os.environ.items()
           if not any(word in k.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
           and not k.startswith(("AWS_", "GOOGLE_", "AZURE_", "ANTHROPIC_", "OPENAI_", "LITELLM_"))}
    env["PYTHONPATH"] = str(root / "src")
    env["PYTHONNOUSERSITE"] = "1"
    env["LITELLM_TELEMETRY"] = "False"
    env["USE_DOCKER"], env["USE_R"], env["STAGE"] = "true", "false", "local"
    return env


def preflight(args, env):
    validate_checkout(args.finch_root, args.finch_commit)
    probe = subprocess.run([args.python, str(WORKER), "--check"], env=env,
                           cwd=args.finch_root, capture_output=True, text=True, timeout=60, check=False)
    if probe.returncode:
        raise ValueError("Finch interpreter/import check failed: " + probe.stderr[-2000:])
    dependencies = json.loads(probe.stdout)
    image = json.loads(subprocess.check_output(
        [args.docker, "image", "inspect", args.image], text=True, timeout=30))[0]
    # Never silently pull a mutable image during an experiment.
    return {"dependencies": dependencies, "image_id": image["Id"]}


def read_calls(path):
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                value = json.loads(line)
            except ValueError:  # A kill may truncate only the final line.
                continue
            if isinstance(value, dict):
                records.append(value)
    return records


def token_accounting(calls):
    def total(key):
        values = [(c.get("usage") or {}).get(key) for c in calls]
        return sum(values) if values and all(type(v) is int and v >= 0 for v in values) else None
    return {"source": "finch_router_ledger", "calls": len(calls),
            "failed_calls": sum(c.get("state") != "completed" for c in calls),
            "input_tokens": total("input_tokens"), "output_tokens": total("output_tokens"),
            "cached_input_tokens": total("cached_input_tokens"),
            "model_seconds": sum(c.get("duration_seconds", 0) for c in calls),
            "limitations": "Returned provider usage via LiteLLM. Missing usage is null, not zero. "
                "Router-internal retries without returned usage may be unobservable; "
                "cached tokens, when reported, are part of input tokens."}


def cleanup_container(docker, name):
    if not re.fullmatch(r"oceanx-finch-[0-9a-f]{32}", name):
        raise ValueError("Refusing to remove an unexpected container name")
    probe = subprocess.run([docker, "container", "inspect", name], capture_output=True,
                           text=True, timeout=15, check=False)
    if probe.returncode:
        # A stopped worker normally removes its own container. Check daemon health
        # before interpreting an inspect error as 'already removed'.
        subprocess.run([docker, "info"], capture_output=True, check=True, timeout=15)
        return
    subprocess.run([docker, "rm", "-f", name], capture_output=True, check=True, timeout=20)


def evidence_manifest(workspace):
    """Explicit allowlist for the external evidence collector; never export inputs/logs."""
    files = []
    for name in ("notebook.ipynb", "notebook.md"):
        path = workspace / name
        if path.is_file() and not path.is_symlink():
            files.append(str(path.relative_to(workspace.parent)))
    root = workspace / "outputs"
    if root.is_dir() and not root.is_symlink():
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.is_symlink() and not any(
                    p.is_symlink() for p in path.parents if p != workspace.parent):
                files.append(str(path.relative_to(workspace.parent)))
    return {"schema_version": 1, "files": files}


def run_case(case, directory, args, env, cancelled):
    directory.mkdir(parents=True, mode=0o700)
    workspace = directory / "workspace"
    workspace.mkdir(mode=0o700)
    (workspace / "outputs").mkdir()
    (workspace / "scratch").mkdir()
    write_json(directory / "query.json", case.model_dump(mode="json"))
    prompt = directory / "submitted_prompt.txt"
    prompt.write_text(prompt_for(case), encoding="utf-8")
    name = "oceanx-finch-" + uuid4().hex
    spec = {"workspace": str(workspace), "mounts": input_mounts(case),
            "container_name": name, "image": args.image_id,
            "max_steps": args.max_steps, "temperature": args.temperature,
            "memory_bytes": args.memory_mb * 1024**2, "cpus": args.cpus,
            "execution_timeout": args.execution_timeout,
            "uid": os.getuid(), "gid": os.getgid()}
    write_json(directory / "worker.json", spec)
    command = [args.python, str(WORKER), "--attempt", str(directory),
               "--config", str(args.config)]
    started, at = time.monotonic(), datetime.now(UTC).isoformat()
    code, reason, error, cleanup_error = None, None, None, None
    try:
        code, reason = supervise(command, workspace, prompt, directory,
                                 case.timeout_seconds or args.timeout, cancelled, env=env)
    except OSError as exc:
        error = str(exc)
    finally:
        try:
            cleanup_container(args.docker, name)
        except (OSError, subprocess.SubprocessError) as exc:
            cleanup_error = str(exc)
    terminal_path = directory / "worker_result.json"
    try:
        terminal = json.loads(terminal_path.read_text()) if terminal_path.exists() else {}
        if not isinstance(terminal, dict):
            raise TypeError("Worker terminal record is not an object")
    except (ValueError, TypeError):
        terminal = {}
        error = "Worker terminal record is incomplete"
    status = reason if reason in {"cancelled", "timed_out"} else terminal.get("status", "failed")
    answer = directory / "answer.md"
    if status == "completed" and (code != 0 or reason or error or cleanup_error
                                   or not answer.is_file() or not answer.read_text().strip()):
        status = "failed"
    accounting = token_accounting(read_calls(directory / "model_calls.jsonl"))
    write_json(directory / "token_usage.json", accounting)
    write_json(directory / "artifacts.json", inventory(workspace))
    write_json(directory / "evidence_manifest.json", evidence_manifest(workspace))
    result = {"id": case.id, "agent": "finch-local", "status": status,
              "started_at": at, "elapsed_seconds": time.monotonic() - started,
              "exit_code": code, "stop_reason": reason or terminal.get("stop_reason"),
              "runner_error": error, "cleanup_error": cleanup_error,
              "steps": terminal.get("steps"), "attempt_dir": str(directory),
              "external_usage": accounting,
              "limitations": "Local Finch analysis component, not full Robin. No search tool, "
                  "no cross-task learning. Runtime completion is not scientific validation."}
    write_json(directory / "result.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--finch-root", type=Path, required=True)
    parser.add_argument("--finch-commit", default=FINCH_COMMIT)
    parser.add_argument("--python", default=sys.executable, help="Finch Python 3.12+ interpreter")
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--image", required=True, help="Already-built scientific kernel image")
    parser.add_argument("--arm", default="F", help="External arm label; not an OceanX policy")
    parser.add_argument("--max-steps", type=int, default=60)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=10800)
    parser.add_argument("--execution-timeout", type=float, default=300)
    parser.add_argument("--memory-mb", type=int, default=8192)
    parser.add_argument("--cpus", type=float, default=2)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if os.name != "posix":
        raise ValueError("Finch runner requires POSIX process supervision")
    if os.getuid() == 0:
        raise ValueError("Run Finch as an ordinary user, not root")
    for value in (args.max_steps, args.timeout, args.execution_timeout, args.memory_mb, args.cpus):
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Step, time and resource limits must be positive and finite")
    if not math.isfinite(args.temperature) or not 0 <= args.temperature <= 2:
        raise ValueError("Temperature must be between 0 and 2")
    config = load_config(args.config)
    config.endpoint(config.oceanx_api)  # Fail before creating output or making any model call.
    from benchmark_config import DEFAULT_CONFIG
    args.config = Path(args.config or os.environ.get("OCEAN_BENCH_CONFIG", DEFAULT_CONFIG)).resolve()
    args.finch_root = args.finch_root.expanduser().resolve()
    args.python, args.docker = shutil.which(args.python), shutil.which(args.docker)
    if not args.python or not args.docker:
        raise ValueError("Finch Python interpreter and Docker executable must exist")
    cases = load_queries(args.queries)
    validate_datasets(cases)
    output = args.output.expanduser().resolve()
    if any(c in str(output) for c in (":", "\n", "\r")):
        raise ValueError("Docker workspace paths cannot contain colons or newlines")
    for protected in (REPO, args.finch_root, args.queries.resolve(), args.config,
                      *(p for case in cases for p in case.datasets)):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("Output must be separate from repositories, config, queries and data")
    env = worker_environment(args.finch_root)
    runtime = preflight(args, env)
    args.image_id = runtime["image_id"]
    identity = {"agent": "finch-local", "arm": args.arm, "finch_commit": args.finch_commit,
                "finch_root": str(args.finch_root), "python": args.python,
                "runtime": runtime, "model_protocol": config.public(),
                "max_steps": args.max_steps, "temperature": args.temperature,
                "timeout": args.timeout, "execution_timeout": args.execution_timeout,
                "memory_mb": args.memory_mb, "cpus": args.cpus,
                "cases": [c.model_dump(mode="json") for c in cases],
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "worker_sha256": hashlib.sha256(WORKER.read_bytes()).hexdigest()}
    if args.resume:
        if json.loads((output / "manifest.json").read_text())["identity"] != identity:
            raise ValueError("Resume inputs, model, Finch version, image or runner changed")
    else:
        output.mkdir(parents=True, exist_ok=False, mode=0o700)
    import fcntl
    with (output / ".runner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not args.resume:
            write_json(output / "manifest.json", {"identity": identity})
            write_json(output / "arm.json", {"arm": args.arm, "agent": "finch-local",
                "policy": None, "lessons": None, "model": config.model, "runtime": runtime,
                "finch_commit": args.finch_commit, "search_available": False})
        stopped = [False]
        previous = {s: signal.signal(s, lambda *_: stopped.__setitem__(0, True))
                    for s in (signal.SIGTERM, signal.SIGINT)}
        failed = False
        try:
            for case in cases:
                if stopped[0]:
                    break
                prior = sorted((output / case.id).glob("attempt-*/result.json"))
                if args.resume and prior and json.loads(prior[-1].read_text())["status"] == "completed":
                    print(f"[{case.id}] skipped (completed)", flush=True)
                    continue
                directory = output / case.id / f"attempt-{time.time_ns()}-{uuid4().hex[:8]}"
                print(f"[{case.id}] running Finch", flush=True)
                result = run_case(case, directory, args, env, lambda: stopped[0])
                with (output / "results.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(result, ensure_ascii=False) + "\n")
                print(f"[{case.id}] {result['status']}", flush=True)
                failed |= result["status"] != "completed"
                if result["cleanup_error"]:
                    break  # Do not start another analysis while cleanup is uncertain.
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return 130 if stopped[0] else int(failed)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Finch batch stopped: {exc}", file=sys.stderr)
        sys.exit(1)
