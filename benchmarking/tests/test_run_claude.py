"""Real subprocess supervision with a fake CLI; no model calls or server access."""
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

import run_claude as runner
from test_prepare_queries import archive as archive


@pytest.fixture
def setup(tmp_path, monkeypatch):
    import benchmark_config
    monkeypatch.setattr(benchmark_config, "preflight", lambda **kw: None)
    config_file = tmp_path / ".env"
    config_file.write_text("BENCH_MODEL=test-deepseek\nBENCH_OCEANX_API=anthropic\n"
                           "BENCH_ANTHROPIC_BASE_URL=https://example.invalid\nDEEPSEEK_API_KEY=test-key\n")
    executable = tmp_path / "fake-claude"
    executable.write_text(f"#!{sys.executable}\n" + '''
import json, os, pathlib, subprocess, sys, time
if "--version" in sys.argv:
    print("fake-claude 1.0")
    sys.exit(0)
prompt = sys.stdin.read()
pathlib.Path("code.py").write_text("print('analysis')")
pathlib.Path("figure.png").write_bytes(b"test-image")
pathlib.Path("figures").mkdir()
pathlib.Path("figures/view.png").write_bytes(b"png")
pathlib.Path("analysis.ipynb").write_text("{}")
pathlib.Path("argv.json").write_text(json.dumps(sys.argv))
print(json.dumps({"type":"assistant", "message":{"model":"test-deepseek", "content":[{"type":"text", "text":"partial work"}]}}), flush=True)
if "TIMEOUT" in prompt or "CANCEL" in prompt:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1); open('escaped.txt', 'w').write('bad')"])
    pathlib.Path("child.pid").write_text(str(child.pid))
    time.sleep(30)
if "MALFORMED" in prompt:
    print("not-json")
    sys.exit(0)
result = {"type":"result", "subtype":"success", "is_error":False, "result":"Research answer", "usage":{"input_tokens":10}}
if "API_ERROR" in prompt:
    result.update(subtype="error_during_execution", is_error=True, result="API failed")
if "DENIED" in prompt:
    result["permission_denials"] = [{"tool_name":"Bash"}]
if "NOREPORT" in prompt:
    result["result"] = " \\n"
print(json.dumps(result), flush=True)
sys.exit(4 if "NONZERO" in prompt else 0)
''')
    executable.chmod(0o700)
    data = tmp_path / "data"
    data.mkdir()
    (data / "input.nc").write_bytes(b"input unchanged")
    queries = tmp_path / "queries.jsonl"
    output = tmp_path / "runs"
    def invoke(items, extra=()):
        queries.write_text("\n".join(json.dumps({"id": f"Q{i:02}", "query": q,
            "datasets": ["data"], "timeout_seconds": timeout})
            for i, (q, timeout) in enumerate(items, 1)))
        return ["--config", str(config_file), "--queries", str(queries), "--output", str(output), "--claude", str(executable), *extra]
    return tmp_path, output, invoke


def results(output):
    return [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]


def refused():
    return PermissionError(errno.EPERM, "Operation not permitted")


@pytest.fixture
def exited_group(monkeypatch):
    """os.killpg as macOS answers while a stopped group still holds exited processes nobody has
    reaped: "not permitted" to the first three kill signals, then whatever the system says."""
    real, kills = os.killpg, []

    def killpg(pgid, signum):
        if signum == signal.SIGKILL:
            kills.append(pgid)
            if len(kills) <= 3:
                raise refused()
        real(pgid, signum)

    monkeypatch.setattr(os, "killpg", killpg)
    return kills


def test_success_files_model_config_and_resume(setup):
    root, output, invoke = setup
    args = invoke([("Analyze data", 5)], ["--allow-tools", "Read", "Bash", "Write"])
    assert runner.main(args) == 0
    result = results(output)[0]
    attempt = Path(result["attempt_dir"])
    assert result["agent"] == "claude-code"
    assert result["elapsed_seconds"] > 0
    assert result["usage"]["input_tokens"] == 10
    assert (attempt / "answer.md").read_text() == "Research answer"
    assert (attempt / "workspace/figure.png").exists()
    assert (root / "data/input.nc").read_bytes() == b"input unchanged"
    assert not list(output.rglob("*.nc"))
    command = json.loads((attempt / "command.json").read_text())
    assert command[command.index("--model") + 1] == "test-deepseek"
    assert "--dangerously-skip-permissions" not in command
    assert "--no-session-persistence" in command
    assert runner.main([*args, "--resume"]) == 0
    assert len(results(output)) == 1
    assert json.loads((output / 'arm.json').read_text())['arm'] == 'Claude'
    assert result['external_usage']['input_tokens'] is None  # incomplete CLI usage is not zero
    with pytest.raises(ValueError, match="Model differs"):
        runner.main([*args, "--resume", "--model", "changed-model"])


def test_no_argument_launch_from_env(setup, archive, monkeypatch):
    root, _, _ = setup
    file = root / '.env'
    file.write_text(file.read_text() + f'BENCH_DATA_ROOT={archive}\nBENCH_OUTPUT_ROOT={root / "automatic"}\n'
                    f'BENCH_CLAUDE_EXECUTABLE={root / "fake-claude"}\nBENCH_TASKS=Q07\n'
                    'BENCH_CLAUDE_ALLOW_TOOLS=Read,Bash,Write\n')
    monkeypatch.setenv('OCEAN_BENCH_CONFIG', str(file))
    assert runner.main([]) == 0
    output = root / 'automatic/methods-public-r1/runs/Claude'
    assert results(output)[0]['id'] == 'Q07'
    identity = json.loads((output / 'manifest.json').read_text())['identity']
    assert identity['allow_tools'] == ['Read', 'Bash', 'Write']
    assert 'test-key' not in json.dumps(identity)
    # The real entrypoint releases its experiment lease after the batch. Reset
    # archives both selection and method output, then the same .env launches fresh.
    from benchmark_run import reset_experiment
    from benchmark_config import load_config
    old = reset_experiment(load_config(file))
    assert (old / 'runs/Claude/results.jsonl').is_file()
    assert runner.main([]) == 0
    assert len(results(output)) == 1


def test_claude_loads_its_own_settings_file_when_no_file_is_named(setup, archive, monkeypatch):
    import benchmark_config
    root, _, _ = setup
    shared = root / '.env'   # as written by the fixture: no data root, so a launch from it would stop
    own = root / '.env.claude'
    own.write_text(shared.read_text() + f'BENCH_DATA_ROOT={archive}\nBENCH_OUTPUT_ROOT={root / "automatic"}\n'
                   f'BENCH_CLAUDE_EXECUTABLE={root / "fake-claude"}\nBENCH_TASKS=Q07\n'
                   'BENCH_EXPERIMENT=claude-own\nBENCH_CLAUDE_ALLOW_TOOLS=Read,Bash,Write\n')
    monkeypatch.setattr(benchmark_config, 'DEFAULT_CONFIG', shared)
    monkeypatch.setenv('OCEAN_BENCH_CONFIG', 'restored after the test')
    monkeypatch.delenv('OCEAN_BENCH_CONFIG')
    assert runner.main([]) == 0
    assert results(root / 'automatic/claude-own/runs/Claude')[0]['id'] == 'Q07'


@pytest.mark.parametrize("query,status", [("API_ERROR", "failed"), ("MALFORMED", "failed"),
                                           ("NONZERO", "failed"), ("DENIED NOREPORT", "needs_interaction"),
                                           ("NOREPORT", "failed")])
def test_failures_continue_and_preserve_partial(setup, query, status):
    _, output, invoke = setup
    assert runner.main(invoke([(query, 5), ("OK", 5)])) == 1
    first, second = results(output)
    assert first["status"] == status
    assert second["status"] == "completed"
    assert (Path(first["attempt_dir"]) / "partial_answer.md").read_text() == "partial work"


def test_a_report_delivered_despite_a_refused_tool_call_is_a_completed_attempt(setup):
    """Claude's Q15 of the three-method batch was a full report scored as nothing for one refusal."""
    _, output, invoke = setup
    assert runner.main(invoke([("DENIED", 5)])) == 0
    (only,) = results(output)
    assert only["status"] == "completed"
    assert only["permission_denials"] == [{"tool_name": "Bash"}]
    assert (Path(only["attempt_dir"]) / "answer.md").read_text() == "Research answer"


def test_the_prompt_says_the_run_is_one_turn_and_nothing_resumes(setup):
    """Claude's Q25 ended its turn waiting for a background job that could never report back."""
    from oceanx.batch import QueryCase
    prompt = runner.prompt_for(QueryCase(id="Q25", query="How much heat?"))
    assert "nothing runs or resumes after your final response" in prompt
    assert "Wait for background work to finish before you end" in prompt
    assert "if time is short, report what you have" in prompt
    assert prompt.endswith("Research query (unchanged):\nHow much heat?\n")


def test_timeout_kills_children_retains_outputs(setup):
    _, output, invoke = setup
    assert runner.main(invoke([("TIMEOUT", 0.3), ("OK", 5)])) == 1
    assert [r["status"] for r in results(output)] == ["timed_out", "completed"]
    # No answer is made up for it; what the agent wrote on the way is kept as it was.
    timed_out = Path(results(output)[0]["attempt_dir"])
    assert not (timed_out / "answer.md").exists()
    partial = timed_out / "partial_answer.md"  # absent when the time limit came before the first message
    assert not partial.exists() or partial.read_text() == "partial work"
    time.sleep(1.1)
    assert not list(output.rglob("escaped.txt"))
    assert list(output.rglob("figure.png"))


def test_timeout_recorded_when_stopped_group_holds_only_exited_processes(setup, exited_group):
    _, output, invoke = setup
    assert runner.main(invoke([("TIMEOUT", 0.3)])) == 1
    [record] = results(output)
    assert (record["status"], record["stop_reason"], record["runner_error"]) == (
        "timed_out", "timed_out", None)
    assert len(exited_group) >= 4  # refused three times, then asked again


def test_group_that_keeps_refusing_is_recorded_as_an_error(setup, monkeypatch):
    """A process the runner may not signal is not taken for one that has exited."""
    _, output, invoke = setup
    real = os.killpg

    def killpg(pgid, signum):
        try:
            real(pgid, signum)  # the fake CLI is stopped all the same, so nothing outlives the test
        except ProcessLookupError:
            pass
        raise refused()

    monkeypatch.setattr(os, "killpg", killpg)
    monkeypatch.setattr(runner, "GROUP_REAP_SECONDS", 0.05)
    assert runner.main(invoke([("TIMEOUT", 0.3)])) == 1
    [record] = results(output)
    assert record["status"] == "failed" and record["stop_reason"] == "launch_or_io_error"
    assert "Operation not permitted" in record["runner_error"]


def test_stop_group_accepts_child_that_exited_by_itself():
    """Not reaped yet, it is the only member of its group: the case macOS answers "not permitted"."""
    process = subprocess.Popen([sys.executable, "-c", "pass"], stdout=subprocess.PIPE,
                               start_new_session=True)
    assert process.stdout.read() == b""  # end of file: it has exited; nothing has waited for it
    process.stdout.close()
    time.sleep(0.1)
    runner.stop_group(process)
    assert process.wait() == 0


def test_group_signal_reaps_child_before_asking_again(monkeypatch):
    class Exited:  # our child after it exited: its group refuses until the child is reaped
        pid, reaped = 4242, False

        def poll(self):
            self.reaped = True
            return 0

    child = Exited()

    def killpg(pgid, signum):
        raise ProcessLookupError(errno.ESRCH, "No such process") if child.reaped else refused()

    monkeypatch.setattr(os, "killpg", killpg)
    assert runner.signal_group(child, signal.SIGTERM) is False


def test_sigterm_records_cancelled_and_stops_batch(setup):
    _, output, invoke = setup
    args = invoke([("CANCEL", 20), ("SHOULD NOT START", 5)])
    bootstrap = ("import sys; sys.path.insert(0, " + repr(str(Path(runner.__file__).parent)) + "); "
                 "import benchmark_config; benchmark_config.preflight=lambda **kw: None; "
                 "import run_claude; sys.exit(run_claude.main())")
    process = subprocess.Popen([sys.executable, "-c", bootstrap, *args],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not list(output.rglob("child.pid")) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert list(output.rglob("child.pid"))
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        assert process.returncode == 130
        assert [r["status"] for r in results(output)] == ["cancelled"]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_log_limit(setup, monkeypatch):
    _, output, invoke = setup
    monkeypatch.setattr(runner, "LOG_LIMIT", 20)
    assert runner.main(invoke([("OK", 5)])) == 1
    result = results(output)[0]
    assert result["stop_reason"] == "log_limit_exceeded"
    assert (Path(result["attempt_dir"]) / "events.jsonl").stat().st_size <= 20


def test_refuse_existing_output_and_source_overlap(setup):
    root, output, invoke = setup
    args = invoke([("OK", 5)])
    with pytest.raises(ValueError, match="separate"):
        runner.main([*args, "--output", str(root / "data/results")])
    output.mkdir()
    with pytest.raises(FileExistsError):
        runner.main(args)


def test_inventory_does_not_follow_symlinks(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "source").symlink_to(tmp_path, target_is_directory=True)
    record = runner.inventory(workspace)
    assert record["files"] == []
    assert record["excluded"] == ["source"]


def test_whole_call_tokens_no_double_counting(tmp_path):
    events = tmp_path / "events.jsonl"
    step = {"type": "assistant", "message": {"id": "one", "model": "pro",
            "usage": {"input_tokens": 10, "output_tokens": 1}}}
    events.write_text(json.dumps(step) + "\n" + json.dumps(step) + "\n")
    terminal = {"usage": {"input_tokens": 10}, "modelUsage": {
        "pro": {"inputTokens": 30, "outputTokens": 40,
                "cacheReadInputTokens": 100, "cacheCreationInputTokens": 0},
        "aux": {"inputTokens": 5, "outputTokens": 10,
                "cacheReadInputTokens": 20, "cacheCreationInputTokens": 0}}}
    report = runner.token_accounting(events, terminal)
    assert report["whole_call_totals"]["total_tokens_including_cache"] == 205
    assert report["whole_call_totals"]["input_tokens"] == 35
    assert len(report["observed_unique_steps"]) == 1
    assert "output_tokens" not in report["observed_unique_steps"][0]
    assert runner.evaluation_usage(report)['input_tokens'] == 155
    assert runner.evaluation_usage(report)['cached_input_tokens'] == 120


def test_missing_final_tokens_are_unknown(tmp_path):
    report = runner.token_accounting(tmp_path / "missing", None)
    assert report["whole_call_totals"]["total_tokens_including_cache"] is None
    assert not report["final_result_present"]

def test_export_delivery_preserves_paths_and_skips_source_links(tmp_path):
    from run_claude import export_delivery
    workspace = tmp_path / "workspace"
    (workspace / "figures").mkdir(parents=True)
    (workspace / "figures/view.png").write_bytes(b"png")
    source = tmp_path / "private.nc"
    source.write_bytes(b"input data")
    (workspace / "figures/source.nc").symlink_to(source)
    (workspace / "analysis.ipynb").write_text("{}")
    destination = tmp_path / "delivery"
    destination.mkdir()
    export_delivery(workspace, destination)
    assert (destination / "figures/view.png").read_bytes() == b"png"
    assert not (destination / "figures/source.nc").exists()
    assert (destination / "analysis.ipynb").is_file()
    manifest = json.loads((destination / 'evidence_manifest.json').read_text())
    assert manifest['files'] == ['figures/view.png', 'workspace/analysis.ipynb']


def test_claude_blinding_and_inventory_use_external_evidence(setup):
    import evaluate
    _, output, invoke = setup
    assert runner.main(invoke([('OK', 5)], ['--arm', 'C'])) == 0
    attempt = Path(results(output)[0]['attempt_dir'])
    mapping, blind = output.parent / 'map.json', output.parent / 'blind'
    assert evaluate.main(['blind', '--runs', str(output), '--map', str(mapping), '--out', str(blind)]) == 0
    assert len(list(blind.rglob('view.png'))) == 1
    assert len(list(blind.rglob('analysis.ipynb'))) == 1
    assert not list(blind.rglob('events.jsonl'))
    assert evaluate.main(['inventory', '--runs', str(output), '--out', str(output.parent / 'inventory')]) == 0
    record = json.loads((attempt / 'run_record.json').read_text())
    assert record['tree'] is None and record['code_runs']['total'] is None
    assert record['missing'] == ['whole-call token totals']
    assert 'research tree' not in record['missing']
