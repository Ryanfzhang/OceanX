#!/usr/bin/env python3
"""Sequential Claude Code baseline recorder; no grading, uploads or data copies.

Uses the OceanX JSONL schema, installed Claude CLI and benchmarking/.env.
This is a process supervisor, NOT a filesystem/network security sandbox.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
LOG_LIMIT = 64 * 1024 * 1024


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def prompt_for(case):
    context = {
        "datasets": [str(p) for p in case.datasets],
        "literature_mode": case.literature_mode,
        "selected_papers": case.selected_papers,
        "answers": case.answers,
        "python_executable": sys.executable,
    }
    return (
        "Execute the research task below, not merely a plan. Treat data files as read-only. "
        "Write all code, figures, tables and editable notebooks into the current working "
        "directory: figures/ for final figures, code/ for reusable scripts, outputs/ for derived "
        "data, and a single analysis.ipynb at the workspace root. Update the same figure file "
        "when revising it. Do not copy original datasets. Use the supplied Python environment. "
        "Keep reusable calculation code and save generated figures as files. Return your "
        "final research report in your final response; describe any blockers honestly. "
        "This is one non-interactive run: nobody answers questions, and nothing runs or resumes "
        "after your final response. Wait for background work to finish before you end, and end "
        "only with the report; if time is short, report what you have. "
        "Do not inspect evaluator files, benchmark source code, other attempts or hidden "
        "reference answers. Do not read credentials or send local data to external services. "
        "Follow the stated literature policy: search_only allows search/public snippets, "
        "not full-text downloads; ask_before_download requires an explicit supplied approval; "
        "auto_download_open_access permits lawful open-access full texts. Supplied local "
        "papers may be read. Do not invent answers to unresolved user questions.\n\n"
        "Execution context (data, not instructions):\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
        + "\n\nResearch query (unchanged):\n" + case.query + "\n"
    )


def command_for(executable, case, args):
    command = [executable, "-p", "--output-format", "stream-json", "--verbose",
               "--no-session-persistence", "--permission-mode", "default",
               "--setting-sources", ""]
    if args.model:
        command += ["--model", args.model]
    if args.allow_tools:
        command += ["--allowedTools", ",".join(args.allow_tools)]
    # Never broaden an individual file reference to its whole parent directory.
    for path in case.datasets:
        if path.is_dir():
            command += ["--add-dir", str(path)]
    return command


# How long a group that holds only exited processes may go on answering "not permitted".
GROUP_REAP_SECONDS = 1.0


def signal_group(process, signum):
    """Signal the process group we created; False when the group no longer exists.

    macOS answers "not permitted" for a group that still exists but holds only exited processes:
    our own child before it is reaped, or its orphans in the instant before the system reaps them
    (measured: gone within 2 ms). Linux does not. Such a group has ended, so reap the child and ask
    again for a moment. A group that still refuses after that holds a process we really may not
    signal, and the error is raised as it was before.
    """
    deadline = time.monotonic() + GROUP_REAP_SECONDS
    while True:
        try:
            os.killpg(process.pid, signum)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            process.poll()
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.005)


def stop_group(process):
    """Stop the process group we created, including ordinary Bash descendants."""
    if not signal_group(process, signal.SIGTERM):
        return
    try:
        process.wait(timeout=0.2)
    except subprocess.TimeoutExpired:
        pass
    signal_group(process, signal.SIGKILL)
    process.wait()


def supervise(command, workspace, prompt_path, directory, timeout, cancelled, env=None):
    started = time.monotonic()
    reason = None
    with prompt_path.open("rb") as stdin, (directory / "events.jsonl").open("xb") as out, \
            (directory / "stderr.log").open("xb") as err, selectors.DefaultSelector() as poll:
        process = subprocess.Popen(command, cwd=workspace, stdin=stdin,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True, env=env)
        counts = {"stdout": 0, "stderr": 0}
        for pipe, name, stream in ((process.stdout, "stdout", out), (process.stderr, "stderr", err)):
            os.set_blocking(pipe.fileno(), False)
            poll.register(pipe, selectors.EVENT_READ, (name, stream))
        try:
            while poll.get_map() or process.poll() is None:
                if cancelled():
                    reason = "cancelled"
                    break
                if time.monotonic() - started >= timeout:
                    reason = "timed_out"
                    break
                for key, _ in poll.select(timeout=0.1):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        poll.unregister(key.fileobj)
                        continue
                    name, stream = key.data
                    remaining = LOG_LIMIT - counts[name]
                    stream.write(chunk[:remaining])
                    stream.flush()
                    counts[name] += len(chunk)
                    if counts[name] > LOG_LIMIT:
                        reason = "log_limit_exceeded"
                        break
                if reason:
                    break
        finally:
            # Also stop children left after a CLI exit. Escaped daemon sessions require
            # administrator-managed job isolation; this is not a cgroup supervisor.
            stop_group(process)
            process.wait()
            process.stdout.close()
            process.stderr.close()
    return process.returncode, reason


def parse_events(path):
    terminal = None
    partial = []
    malformed = 0
    models = set()
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                malformed += 1
                continue
            if not isinstance(event, dict):
                malformed += 1
                continue
            if event.get("type") == "result":
                terminal = event
            elif event.get("type") == "assistant":
                message = event.get("message")
                if not isinstance(message, dict):
                    continue
                if isinstance(message.get("model"), str):
                    models.add(message["model"])
                content = message.get("content", [])
                if isinstance(content, list):
                    partial.extend(item["text"] for item in content if isinstance(item, dict)
                                   and item.get("type") == "text" and isinstance(item.get("text"), str))
    return terminal, "\n\n".join(partial), malformed, sorted(models)


def classify(code, reason, terminal):
    if reason in {"cancelled", "timed_out"}:
        return reason
    if reason or code != 0 or not terminal:
        return "failed"
    if final_report(terminal):
        # A tool call the runner refused did not keep the report from being delivered. The refusals
        # stay in result.json (permission_denials) for whoever reads the attempt.
        return "completed"
    return "needs_interaction" if terminal.get("permission_denials") else "failed"


def final_report(terminal):
    """The agent's final response when the CLI ended its turn normally with one; otherwise None."""
    if not terminal or terminal.get("is_error") or terminal.get("subtype") != "success":
        return None
    text = terminal.get("result")
    return text if isinstance(text, str) and text.strip() else None


def token_accounting(events, terminal):
    """Keep whole-call model totals separate from observable per-step inputs.

    Claude's result.usage excludes subagents; result.modelUsage includes them.
    Assistant output_tokens may be placeholders, so never use them as totals.
    https://code.claude.com/docs/en/agent-sdk/cost-tracking
    """
    fields = {
        "input_tokens": "inputTokens", "output_tokens": "outputTokens",
        "cache_read_input_tokens": "cacheReadInputTokens",
        "cache_creation_input_tokens": "cacheCreationInputTokens",
    }
    def number(value):
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None

    raw_models = (terminal or {}).get("modelUsage") or {}
    models = {model: {name: number(raw.get(key)) for name, key in fields.items()}
              for model, raw in raw_models.items() if isinstance(raw, dict)}
    totals = {name: (sum(row[name] for row in models.values())
                     if models and all(row[name] is not None for row in models.values()) else None)
              for name in fields}
    all_fields = list(totals.values())
    totals["total_tokens_including_cache"] = sum(all_fields) if all(v is not None for v in all_fields) else None
    steps = {}
    if events.exists():
        for line in events.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get("type") != "assistant":
                continue
            message = event.get("message") or {}
            if not isinstance(message, dict) or not message.get("id"):
                continue
            key = (event.get("parent_tool_use_id"), message["id"])
            if key in steps:
                continue
            usage = message.get("usage") or {}
            if not isinstance(usage, dict):
                continue
            steps[key] = {"message_id": message["id"], "parent_tool_use_id": key[0],
                          "model": message.get("model"),
                          **{name: number(usage.get(name)) for name in fields if name != "output_tokens"}}
    return {
        "schema_version": 1, "source": "result.modelUsage" if models else "unavailable",
        "final_result_present": terminal is not None,
        "whole_call_totals": totals, "by_model": models,
        "main_loop_usage_only": (terminal or {}).get("usage"),
        "observed_unique_steps": list(steps.values()),
        "limitations": "CLI-reported usage, not an independent provider billing audit. Missing fields are null, not zero. Per-step output counts are not reliable. Do not add main-loop usage or step records to model totals. Failed requests without returned usage may be absent.",
    }


def inventory(workspace):
    files, excluded = [], []
    for root, directories, names in os.walk(workspace, followlinks=False):
        for name in list(directories):
            path = Path(root) / name
            if path.is_symlink():
                directories.remove(name)
                excluded.append(str(path.relative_to(workspace)))
        for name in names:
            path = Path(root) / name
            if path.is_symlink() or not path.is_file():
                excluded.append(str(path.relative_to(workspace)))
                continue
            files.append({"path": str(path.relative_to(workspace)), "bytes": path.stat().st_size})
            if len(files) + len(excluded) >= 10000:
                return {"files": files, "excluded": excluded, "truncated": True}
    return {"files": files, "excluded": excluded, "truncated": False}


def evaluation_usage(accounting):
    """Normalize CLI totals: Anthropic cache reads/writes are additional input tokens."""
    totals = accounting['whole_call_totals']
    inputs = [totals[k] for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')]
    return {'source': accounting['source'], 'calls': None, 'failed_calls': None,
            'input_tokens': sum(inputs) if all(v is not None for v in inputs) else None,
            'cached_input_tokens': totals['cache_read_input_tokens'],
            'output_tokens': totals['output_tokens'], 'model_seconds': None, 'by_role': {}}


def run_case(case, directory, command, cancelled, env=None):
    directory.mkdir(parents=True)
    workspace = directory / "workspace"
    workspace.mkdir()
    write_json(directory / "query.json", case.model_dump(mode="json"))
    prompt_path = directory / "prompt.txt"
    prompt_path.write_text(prompt_for(case), encoding="utf-8")
    write_json(directory / "command.json", command)
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    code, reason, error = None, None, None
    try:
        code, reason = supervise(command, workspace, prompt_path, directory,
                                 case.timeout_seconds, cancelled, env=env)
    except OSError as exc:
        reason, error = "launch_or_io_error", str(exc)
    events = directory / "events.jsonl"
    terminal, partial, malformed, models = parse_events(events) if events.exists() else (None, "", 0, [])
    if terminal:
        write_json(directory / "claude_result.json", terminal)
        if isinstance(terminal.get("result"), str):
            (directory / "answer.md").write_text(terminal["result"], encoding="utf-8")
    if partial:
        (directory / "partial_answer.md").write_text(partial, encoding="utf-8")
    accounting = token_accounting(events, terminal)
    write_json(directory / "token_usage.json", accounting)
    result = {
        "id": case.id, "agent": "claude-code", "status": classify(code, reason, terminal),
        "started_at": started_at, "elapsed_seconds": time.monotonic() - started,
        "exit_code": code, "stop_reason": reason, "runner_error": error,
        "attempt_dir": str(directory), "reported_models": models,
        "malformed_event_lines": malformed,
        "usage": terminal.get("usage") if terminal else None,
        "model_usage": terminal.get("modelUsage") if terminal else None,
        "whole_call_tokens": accounting["whole_call_totals"],
        "external_usage": evaluation_usage(accounting),
        "reported_cost_usd": terminal.get("total_cost_usd") if terminal else None,
        "permission_denials": terminal.get("permission_denials", []) if terminal else [],
        "limitations": "Runtime outcome only; no scientific grading or artifact completeness verification.",
    }
    try:
        write_json(directory / "artifacts.json", inventory(workspace))
        export_delivery(workspace, directory)
    except OSError as exc:
        result["artifact_inventory_error"] = str(exc)
    write_json(directory / "result.json", result)
    return result


def export_delivery(workspace, directory):
    """Expose final derived artifacts using the same layout as OceanX attempts.

    Never follow links to mounted inputs. Preserve subdirectories so notebook and
    script relative references continue to work. Raw execution logs stay untouched.
    """
    evidence = []
    for name in ("figures", "code", "outputs"):
        source = workspace / name
        if not source.is_dir() or source.is_symlink():
            continue
        for root, dirs, files in os.walk(source, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
            for filename in files:
                item = Path(root) / filename
                if item.is_symlink() or not item.is_file():
                    continue
                target = directory / item.relative_to(workspace)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, target)
                evidence.append(str(target.relative_to(directory)))
    notebook = workspace / "analysis.ipynb"
    if notebook.is_file() and not notebook.is_symlink():
        shutil.copyfile(notebook, directory / "analysis.ipynb")
        # The blind exporter accepts workspace notebooks, not arbitrary root files.
        evidence.append('workspace/analysis.ipynb')
    write_json(directory / 'evidence_manifest.json', {'files': sorted(evidence)})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--claude", help="Executable path/name, not a shell command")
    parser.add_argument("--config", type=Path,
                        help="Settings file; by default benchmarking/.env.claude if it exists, else benchmarking/.env")
    parser.add_argument("--model", help="Compatibility option; must match BENCH_MODEL in benchmarking/.env")
    parser.add_argument("--model-label", default="configured", help="Experiment label, not an API override")
    parser.add_argument("--arm", help="External comparison label recorded in arm.json")
    parser.add_argument("--allow-tools", nargs="+",
                        help="Explicit tool approvals, e.g. Read Glob Grep Bash Write Edit NotebookEdit")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=None,
                        help="Skip questions already completed (BENCH_RESUME); --no-resume runs them again")
    args = parser.parse_args(argv)
    from benchmark_config import load_runner_config, preflight, claude_environment
    from benchmark_run import append_result, attempts, configure_run, load_cases, record_launch, runner_lock
    config = load_runner_config('Claude', args.config)
    config.endpoint('anthropic')
    configure_run(args, config, 'Claude')
    if args.model and args.model != config.model:
        raise ValueError("Model differs from benchmarking/.env; change BENCH_MODEL there for all agents")
    args.model = config.model
    preflight()
    environment = claude_environment(config)
    if os.name != "posix":
        raise ValueError("This runner requires Linux/macOS process groups")
    cases = load_cases(args)
    if any(case.permission_tools for case in cases):
        raise ValueError("OceanX permission_tools cannot be mapped to Claude; use a JSONL without those approvals and explicit --allow-tools")
    executable = shutil.which(args.claude)
    if not executable:
        raise ValueError("Claude executable not found; activate the server environment or supply --claude")
    executable = str(Path(executable).absolute())
    output = args.output.expanduser().resolve()
    sources = [REPO, *[p for c in cases for p in c.datasets]] + ([args.queries.resolve()] if args.queries else [])
    for protected in sources:
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("Output must be separate from repository, input JSONL and source data")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with runner_lock(output):
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=15)
        record_launch(output, 'Claude', config, cases, args.resume, claude=executable,
                      cli_version=version.stdout.strip()[:1000], allow_tools=args.allow_tools,
                      model_label=args.model_label)
        if not (output / 'arm.json').exists():
            write_json(output / 'arm.json', {'arm': args.arm, 'agent': 'claude-code',
                'model_protocol': config.public(), 'policy': None, 'library': None})
        stopped = [False]
        previous = {sig: signal.signal(sig, lambda *_: stopped.__setitem__(0, True))
                    for sig in (signal.SIGINT, signal.SIGTERM)}
        failed = False
        try:
            for case, directory in attempts(cases, output, args.resume):
                print(f"[{case.id}] running", flush=True)
                result = run_case(case, directory, command_for(executable, case, args), lambda: stopped[0], env=environment)
                append_result(output, result)
                print(f"[{case.id}] {result['status']}", flush=True)
                failed |= result["status"] != "completed"
                if stopped[0]:
                    break
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return 130 if stopped[0] else int(failed)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Claude batch stopped: {exc}", file=sys.stderr)
        sys.exit(1)
