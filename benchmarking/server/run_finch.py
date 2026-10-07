"""Sequential, local Finch baseline. No Edison jobs, uploads, grading or data copies.

The host runs Finch's LDP ReAct agent; its notebook runs in a network-disabled
Bubblewrap sandbox with exactly the case's datasets mounted read-only. Finch is an
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
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from benchmark_config import load_runner_config
from finch_sandbox import BACKEND, cpu_ids, sandbox_command
from finch_worker import model_compatibility
from run_claude import inventory, supervise, write_json

from oceanx.batch import load_queries

FINCH_COMMIT = "aea66fdf2dd2be827727de50a73cae60dff59972"
REPO = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).with_name("finch_worker.py")
SANDBOX = Path(__file__).with_name("finch_sandbox.py")
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
                raise ValueError("Dataset paths cannot contain colons or newlines")


def input_mounts(case):
    return [{"source": str(path), "target": f"/inputs/{i}/{path.name}", "read_only": True}
            for i, path in enumerate(case.datasets)]


def prompt_for(case, *, max_steps=None, execution_timeout=None):
    """The research query with the facts of this runner that the upstream prompts cannot know.

    Seven attempts of the three-method batch delivered nothing: the model called a shell tool that
    does not exist, concluded from list_workdir that the inputs were missing, ran out of steps
    without submitting, or grew a notebook past the replay limit.
    """
    context = {"datasets": [m["target"] for m in input_mounts(case)],
               "selected_papers": case.selected_papers, "answers": case.answers,
               "literature_mode": case.literature_mode}
    limits = ""
    if execution_timeout:
        limits += (f"Each edit_cell reruns every cell and the whole rerun must finish within "
                   f"{int(execution_timeout)} seconds, or the attempt ends: load only the period, depths "
                   "and region a cell needs, save intermediate results under /workspace/scratch and "
                   "reload them in later cells instead of recomputing. ")
    if max_steps:
        limits += (f"You have {int(max_steps)} steps, one tool call each. Only a report sent with "
                   "submit_answer is delivered, so submit what you have before the steps run out. ")
    return (
        "Execute the research question, not merely a plan. Original inputs are read-only. "
        "Write final figures and derived tables under /workspace/outputs; keep temporary "
        "calculations under /workspace/scratch. Do not copy original datasets. Submit the "
        "final research report with submit_answer, citing your saved figures and tables. "
        "State missing evidence and unresolved questions honestly. No evaluator, other "
        "attempts, OceanX skills or reference answers are supplied. This is the local Finch "
        "analysis-component baseline: no literature-search tool or network access is provided. "
        "Supplied local papers can be read; do not invent citations or download papers. "
        "The only way to run code is the edit_cell tool, which adds or replaces a notebook cell "
        "and runs the notebook; there is no shell tool. The input paths below exist only for "
        "notebook code: read them there. list_workdir shows /workspace only and never the "
        "inputs. " + limits + "\n\n"
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
    # The worker loads only benchmarking/.env credentials explicitly. The calculation
    # sandbox receives none of this environment and has no external network.
    env = {k: v for k, v in os.environ.items()
           if not any(word in k.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
           and not k.startswith(("AWS_", "GOOGLE_", "AZURE_", "ANTHROPIC_", "OPENAI_", "LITELLM_"))}
    env["PYTHONPATH"] = str(root / "src")
    env["PYTHONNOUSERSITE"] = "1"
    env["LITELLM_TELEMETRY"] = "False"
    env["USE_DOCKER"], env["USE_R"], env["STAGE"] = "false", "false", "local"
    return env


def preflight(args, env):
    validate_checkout(args.finch_root, args.finch_commit)
    probe = subprocess.run([args.python, str(WORKER), "--check"], env=env,
                           cwd=args.finch_root, capture_output=True, text=True, timeout=60, check=False)
    if probe.returncode:
        raise ValueError("Finch interpreter/import check failed: " + probe.stderr[-2000:])
    dependencies = json.loads(probe.stdout)
    probe = subprocess.run([args.kernel_python, str(WORKER), "--kernel-check"], env=env,
                           cwd=args.finch_root, capture_output=True, text=True, timeout=60, check=False)
    if probe.returncode:
        raise ValueError("Finch notebook environment check failed: " + probe.stderr[-2000:])
    kernel = json.loads(probe.stdout)
    runtime = {"backend": BACKEND, "dependencies": dependencies, "kernel": kernel,
               "bwrap": args.bwrap, "prlimit": args.prlimit, "taskset": args.taskset,
               "cpu_ids": cpu_ids(), "bwrap_version": subprocess.check_output(
                   [args.bwrap, "--version"], text=True, timeout=10).strip()}
    # Fail before any model request if user namespaces/Jupyter loopback sockets are unavailable.
    with tempfile.TemporaryDirectory(prefix="finch-preflight-") as directory:
        spec = {**runtime, "workspace": directory, "mounts": [], "cpus": args.cpus,
                "memory_bytes": args.memory_mb * 1024**2}
        checked = subprocess.run(sandbox_command(spec, [kernel["executable"], "-c",
            ("import ipykernel, nbconvert, numpy, xarray, socket; "
             "s=socket.socket(); s.bind(('127.0.0.1', 0)); s.close()")]),
            capture_output=True, text=True, timeout=60, check=False)
        if checked.returncode:
            raise ValueError("Bubblewrap notebook preflight failed: " + checked.stderr[-2000:])
    return runtime


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


def delivery_check(directory):
    """Check submission hygiene separately from runtime completion and science.

    A successful notebook replay proves execution, not a useful analysis. Neither
    a nonempty answer nor these checks can replace the external scientific rubric.
    """
    answer = directory / "answer.md"
    text = answer.read_text(encoding="utf-8").strip() if answer.is_file() else ""
    executions = sum(record.get("state") == "succeeded"
                     for record in read_calls(directory / "code_runs.jsonl"))
    placeholder = text.casefold().strip("` \t\r\n.!:") == "placeholder"
    return {"status": "not_submitted" if not text else "invalid" if placeholder else "unverified",
            "issues": ["placeholder_answer"] if placeholder else [],
            "successful_notebook_executions": executions,
            "evidence_notes": [] if executions else ["no_successful_notebook_execution"],
            "scientific_validation": "not_evaluated"}


def run_case(case, directory, args, env, cancelled):
    directory.mkdir(parents=True, mode=0o700)
    workspace = directory / "workspace"
    workspace.mkdir(mode=0o700)
    (workspace / "outputs").mkdir()
    (workspace / "scratch").mkdir()
    write_json(directory / "query.json", case.model_dump(mode="json"))
    prompt = directory / "submitted_prompt.txt"
    prompt.write_text(prompt_for(case, max_steps=args.max_steps,
                                 execution_timeout=args.execution_timeout), encoding="utf-8")
    spec = {**args.runtime, "workspace": str(workspace), "mounts": input_mounts(case),
            "max_steps": args.max_steps, "temperature": args.temperature,
            "memory_bytes": args.memory_mb * 1024**2, "cpus": args.cpus,
            "execution_timeout": args.execution_timeout}
    write_json(directory / "worker.json", spec)
    command = [args.python, str(WORKER), "--attempt", str(directory),
               "--config", str(args.config)]
    started, at = time.monotonic(), datetime.now(UTC).isoformat()
    code, reason, error = None, None, None
    try:
        code, reason = supervise(command, workspace, prompt, directory,
                                 case.timeout_seconds or args.timeout, cancelled, env=env)
    except OSError as exc:
        error = str(exc)
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
    if status == "completed" and (code != 0 or reason or error
                                   or not answer.is_file() or not answer.read_text().strip()):
        status = "failed"
    accounting = token_accounting(read_calls(directory / "model_calls.jsonl"))
    write_json(directory / "token_usage.json", accounting)
    write_json(directory / "artifacts.json", inventory(workspace))
    write_json(directory / "evidence_manifest.json", evidence_manifest(workspace))
    result = {"id": case.id, "agent": "finch-local", "status": status,
              "delivery_check": delivery_check(directory),
              "started_at": at, "elapsed_seconds": time.monotonic() - started,
              "exit_code": code, "stop_reason": reason or terminal.get("stop_reason"),
              "runner_error": error,
              "worker_error": terminal.get("error"),
              "execution_log": terminal.get("execution_log"),
              "steps": terminal.get("steps"), "attempt_dir": str(directory),
              "external_usage": accounting,
              "limitations": "Local Finch analysis component, not full Robin. No search tool, "
                  "no cross-task learning. Runtime completion is not scientific validation."}
    write_json(directory / "result.json", result)
    return result


def main(argv=None):
    from contextlib import ExitStack
    with ExitStack() as stack:
        return _main(argv, stack)


def _main(argv, stack):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path,
                        help="Settings file; by default benchmarking/.env.finch if it exists, else benchmarking/.env")
    parser.add_argument("--finch-root", type=Path)
    parser.add_argument("--finch-commit")
    parser.add_argument("--python", help="Finch Python 3.12+ interpreter")
    parser.add_argument("--kernel-python", help="Notebook interpreter; defaults to --python")
    parser.add_argument("--bwrap", help="Linux Bubblewrap executable")
    parser.add_argument("--arm", help="External arm label; not an OceanX policy")
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--execution-timeout", type=float)
    parser.add_argument("--memory-mb", type=int)
    parser.add_argument("--cpus", type=float)
    parser.add_argument("--resume", action="store_true", default=None)
    args = parser.parse_args(argv)
    config = load_runner_config('Finch', args.config)
    config.endpoint(config.oceanx_api)
    from benchmark_run import configure_run
    configure_run(args, config, 'Finch', stack=stack)
    if sys.platform != "linux":
        raise ValueError("Finch runner requires Linux Bubblewrap; no Docker or unsandboxed fallback")
    if os.getuid() == 0:
        raise ValueError("Run Finch as an ordinary user, not root")
    for value in (args.max_steps, args.timeout, args.execution_timeout, args.memory_mb, args.cpus):
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Step, time and resource limits must be positive and finite")
    if not math.isfinite(args.temperature) or not 0 <= args.temperature <= 2:
        raise ValueError("Temperature must be between 0 and 2")
    args.config = config.source
    args.finch_root = args.finch_root.expanduser().resolve()
    args.kernel_python = shutil.which(args.kernel_python or args.python)
    args.python, args.bwrap = shutil.which(args.python), shutil.which(args.bwrap)
    args.prlimit, args.taskset = shutil.which("prlimit"), shutil.which("taskset")
    if not all((args.python, args.kernel_python, args.bwrap, args.prlimit, args.taskset)):
        raise ValueError("Finch/kernel Python, bwrap, prlimit and taskset must exist")
    cases = load_queries(args.queries)
    validate_datasets(cases)
    output = args.output.expanduser().resolve()
    if any(c in str(output) for c in (":", "\n", "\r")):
        raise ValueError("Workspace paths cannot contain colons or newlines")
    for protected in (REPO, args.finch_root, args.queries.resolve(), args.config,
                      *(p for case in cases for p in case.datasets)):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("Output must be separate from repositories, config, queries and data")
    env = worker_environment(args.finch_root)
    runtime = preflight(args, env)
    args.runtime = runtime
    identity = {"agent": "finch-local", "arm": args.arm, "finch_commit": args.finch_commit,
                "finch_root": str(args.finch_root), "python": args.python,
                "runtime": runtime, "model_protocol": config.public(),
                "model_compatibility": model_compatibility(config),
                "max_steps": args.max_steps, "temperature": args.temperature,
                "timeout": args.timeout, "execution_timeout": args.execution_timeout,
                "memory_mb": args.memory_mb, "cpus": args.cpus,
                "cases": [c.model_dump(mode="json") for c in cases],
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "worker_sha256": hashlib.sha256(WORKER.read_bytes()).hexdigest(),
                "sandbox_sha256": hashlib.sha256(SANDBOX.read_bytes()).hexdigest()}
    if args.resume:
        if json.loads((output / "manifest.json").read_text())["identity"] != identity:
            raise ValueError("Resume inputs, model, Finch version, runtime or runner changed")
    else:
        output.mkdir(parents=True, exist_ok=False, mode=0o700)
    import fcntl
    with (output / ".runner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not args.resume:
            write_json(output / "manifest.json", {"identity": identity})
            write_json(output / "arm.json", {"arm": args.arm, "agent": "finch-local",
                "policy": None, "lessons": None, "model": config.model, "runtime": runtime,
                "model_compatibility": model_compatibility(config),
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
                delivery = result["delivery_check"]
                print(f"[{case.id}] runtime={result['status']} delivery={delivery['status']} "
                      f"notebook_executions={delivery['successful_notebook_executions']}", flush=True)
                failed |= result["status"] != "completed"
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
