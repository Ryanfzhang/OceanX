"""Offline Finch adapter/supervisor tests; no API requests or model-written jobs."""
import asyncio
import json
import sys
import time
import types
from pathlib import Path

import finch_worker as worker
import pytest
import run_finch as runner
from finch_sandbox import BACKEND, notebook_command, sandbox_command

from oceanx.batch import QueryCase
from benchmark_config import load_config
from test_prepare_queries import archive as archive


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.os, "getuid", lambda: 1000)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setattr(runner.shutil, "which", lambda name: sys.executable)
    config = tmp_path / ".env"
    config.write_text("BENCH_MODEL=test-model\nBENCH_OCEANX_API=openai\n"
                      "BENCH_OPENAI_BASE_URL=https://example.invalid/v1\nDEEPSEEK_API_KEY=secret-test-key\n")
    data = tmp_path / "data"
    data.mkdir()
    (data / "input.nc").write_bytes(b"unchanged")
    finch = tmp_path / "finch"
    finch.mkdir()
    fake = tmp_path / "worker.py"
    fake.write_text('''
import json, pathlib, subprocess, sys, time
attempt = pathlib.Path(sys.argv[sys.argv.index('--attempt')+1])
spec = json.loads((attempt / 'worker.json').read_text())
prompt = (attempt / 'submitted_prompt.txt').read_text()
work = pathlib.Path(spec['workspace'])
(work / 'notebook.ipynb').write_text('{}')
(work / 'outputs/map.png').write_bytes(b'png')
(work / 'outputs/values.csv').write_text('value\\n42\\n')
(attempt / 'model_calls.jsonl').write_text(json.dumps({'state':'completed', 'duration_seconds':1,
    'usage':{'input_tokens':100,'output_tokens':20,'cached_input_tokens':80}})+'\\n')
(attempt / 'transcript.jsonl').write_text('{}\\n')
if 'TIMEOUT' in prompt:
    subprocess.Popen([sys.executable,'-c',"import time; time.sleep(1); open('escaped.txt','w').write('bad')"])
    time.sleep(30)
if 'FAIL' in prompt:
    (attempt / 'worker_result.json').write_text(json.dumps({'status':'failed','stop_reason':'step_limit'}))
    sys.exit(1)
(attempt / 'answer.md').write_text('Executed answer: 42')
(attempt / 'worker_result.json').write_text(json.dumps({'status':'completed','steps':2}))
''')
    monkeypatch.setattr(runner, "WORKER", fake)
    monkeypatch.setattr(runner, "preflight", lambda args, env: {
        "backend": BACKEND, "dependencies": {"python": "3.12", "libraries": {}}})
    removed = []
    queries = tmp_path / "queries.jsonl"
    output = tmp_path / "runs"
    def invoke(items, extra=()):
        queries.write_text("\n".join(json.dumps({"id": f"Q{i:02}", "query": q,
            "datasets": [str(data)], "timeout_seconds": timeout, "literature_mode": "search_only"})
            for i, (q, timeout) in enumerate(items, 1)))
        return ["--config", str(config), "--queries", str(queries), "--output", str(output),
                "--finch-root", str(finch), "--python", sys.executable,
                *extra]
    return tmp_path, output, invoke, removed


def results(output):
    return [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]


def test_success_resume_and_artifacts(setup):
    root, output, invoke, removed = setup
    args = invoke([("Analyze data", 5)])
    assert runner.main(args) == 0
    [record] = results(output)
    attempt = Path(record["attempt_dir"])
    assert record["status"] == "completed" and record["steps"] == 2
    assert record["external_usage"]["input_tokens"] == 100
    assert (root / "data/input.nc").read_bytes() == b"unchanged"
    assert not list(output.rglob("*.nc"))
    assert (attempt / "workspace/outputs/map.png").exists()
    evidence = json.loads((attempt / "evidence_manifest.json").read_text())["files"]
    assert "workspace/notebook.ipynb" in evidence
    assert "workspace/outputs/map.png" in evidence
    assert "input.nc" not in str(evidence)
    identity = (output / "manifest.json").read_text()
    assert "secret-test-key" not in identity
    mode = json.loads(identity)["identity"]["model_compatibility"]
    assert mode["agent_reasoning"] == "upstream_two_call_react"
    assert mode["tool_choice"] == "upstream_required"
    assert json.loads((output / "arm.json").read_text())["model_compatibility"] == mode
    assert runner.main([*args, "--resume"]) == 0
    assert len(results(output)) == 1 and removed == []
    with pytest.raises(ValueError, match="Resume"):
        runner.main([*args, "--resume", "--max-steps", "30"])


def test_no_argument_launch_from_env(setup, archive, monkeypatch):
    root, _, _, _ = setup
    file = root / '.env'
    file.write_text(file.read_text() + f'BENCH_DATA_ROOT={archive}\nBENCH_OUTPUT_ROOT={root / "automatic"}\n'
                    f'BENCH_FINCH_ROOT={root / "finch"}\nBENCH_FINCH_PYTHON={sys.executable}\n'
                    'BENCH_TASKS=Q07\nBENCH_FINCH_MAX_STEPS=17\n')
    monkeypatch.setenv('OCEAN_BENCH_CONFIG', str(file))
    assert runner.main([]) == 0
    output = root / 'automatic/methods-public-r1/runs/Finch'
    assert results(output)[0]['id'] == 'Q07'
    identity = json.loads((output / 'manifest.json').read_text())['identity']
    assert identity['max_steps'] == 17
    assert 'secret-test-key' not in json.dumps(identity)


def test_timeout_partial_delivery_children_and_retry(setup):
    _, output, invoke, removed = setup
    args = invoke([("TIMEOUT", .3), ("Analyze", 5)])
    assert runner.main(args) == 1
    records = results(output)
    assert [r["status"] for r in records] == ["timed_out", "completed"]
    time.sleep(1.1)
    assert not list(output.rglob("escaped.txt"))
    assert len(list(output.rglob("map.png"))) == 2
    assert removed == []
    assert runner.main([*args, "--resume"]) == 1
    assert len(results(output)) == 3  # Failed case gets a new attempt, completed case is skipped.


def test_step_failure_continues_without_docker(setup):
    _, output, invoke, _ = setup
    assert runner.main(invoke([("FAIL", 5), ("OK", 5)])) == 1
    assert [r["status"] for r in results(output)] == ["failed", "completed"]


def test_unavailable_native_sandbox_fails_before_creating_attempt(setup, monkeypatch):
    _, output, invoke, _ = setup
    def unavailable(*_):
        raise ValueError("Bubblewrap notebook preflight failed")
    monkeypatch.setattr(runner, "preflight", unavailable)
    with pytest.raises(ValueError, match="preflight failed"):
        runner.main(invoke([("Analyze", 5)]))
    assert not output.exists()


def test_docker_arguments_are_no_longer_accepted(setup):
    _, output, invoke, _ = setup
    with pytest.raises(SystemExit):
        runner.main(invoke([("Analyze", 5)], ["--docker", "docker", "--image", "old-image"]))
    assert not output.exists()


def test_sources_and_manifests_reject_links_and_evaluator(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    case = QueryCase(id="Q01", query="Analyze", datasets=[data])
    (data / "evaluator").mkdir()
    with pytest.raises(ValueError, match="evaluator"):
        runner.validate_datasets([case])
    (data / "evaluator").rmdir()
    source = tmp_path / "source.nc"
    source.write_bytes(b"original")
    (data / "link.nc").symlink_to(source)
    with pytest.raises(ValueError, match="symlink"):
        runner.validate_datasets([case])
    assert runner.input_mounts(case)[0] == {"source": str(data), "target": "/inputs/0/data", "read_only": True}
    work = tmp_path / "work"
    (work / "outputs").mkdir(parents=True)
    (work / "outputs/linked.nc").symlink_to(source)
    assert runner.evidence_manifest(work)["files"] == []


def test_unknown_tokens_are_not_zero():
    assert runner.token_accounting([])["input_tokens"] is None
    known = {"state": "completed", "usage": {"input_tokens": 10, "output_tokens": 3}}
    assert runner.token_accounting([known])["cached_input_tokens"] is None
    assert runner.token_accounting([known, {"state": "failed"}])["input_tokens"] is None
    assert worker.normalized_usage({"prompt_tokens": 10, "completion_tokens": 3,
        "prompt_tokens_details": {"cached_tokens": 8}})["input_tokens"] == 10


def test_deepseek_mode_is_explicit_and_other_models_are_unchanged(tmp_path):
    path = tmp_path / ".env"
    path.write_text("DEEPSEEK_API_KEY=test-key\n")
    mode = worker.model_compatibility(load_config(path))
    assert mode == {"agent_reasoning": "upstream_two_call_react",
                    "tool_choice": "upstream_required", "provider_thinking": "disabled",
                    "request_extra_body": {"thinking": {"type": "disabled"}}}
    path.write_text("DEEPSEEK_API_KEY=test-key\nBENCH_MODEL=test-model\n")
    assert worker.model_compatibility(load_config(path))["request_extra_body"] == {}


def test_deepseek_mode_is_saved_and_old_mode_cannot_resume(setup):
    root, output, invoke, _ = setup
    config = root / ".env"
    config.write_text(config.read_text().replace("test-model", "deepseek-flash"))
    args = invoke([("Analyze", 5)])
    assert runner.main(args) == 0
    arm = json.loads((output / "arm.json").read_text())
    assert arm["model_compatibility"]["provider_thinking"] == "disabled"
    manifest = output / "manifest.json"
    old = json.loads(manifest.read_text())
    del old["identity"]["model_compatibility"]
    manifest.write_text(json.dumps(old))
    with pytest.raises(ValueError, match="Resume"):
        runner.main([*args, "--resume"])


def test_namespace_boundary():
    spec = {"workspace": "/runs/work", "mounts": [{"source": "/data/private.nc", "target": "/inputs/0/private.nc"}],
            "memory_bytes": 1000, "cpus": 2, "cpu_ids": [2, 3, 4],
            "bwrap": "/usr/bin/bwrap", "prlimit": "/usr/bin/prlimit", "taskset": "/usr/bin/taskset",
            "kernel": {"executable": "/env/bin/python", "runtime_roots": ["/env"]},
            "execution_timeout": 300}
    command = notebook_command(spec)
    assert "--unshare-all" in command and "--share-net" not in command
    assert "--die-with-parent" in command and "--clearenv" in command
    binds = [command[i + 1:i + 3] for i, part in enumerate(command) if part == "--ro-bind"]
    assert ["/data/private.nc", "/inputs/0/private.nc"] in binds
    assert ["/env", "/env"] in binds and ["/", "/"] not in binds
    assert command[command.index("--bind") + 1:command.index("--bind") + 3] == ["/runs/work", "/workspace"]
    assert "--ExecutePreprocessor.timeout=300" in command
    assert "--as=1000:1000" in command and "2,3" in command
    assert not any("docker" in arg or "API_KEY" in arg for arg in command)
    with pytest.raises(ValueError, match="Unsafe kernel"):
        sandbox_command({**spec, "kernel": {"runtime_roots": ["/"]}}, ["true"])


def test_host_notebook_io_rejects_container_created_links(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "credential.yaml"
    secret.write_text("secret")
    (workspace / "notebook.ipynb").symlink_to(secret)
    with pytest.raises(ValueError, match="Notebook path"):
        worker.workspace_file(workspace / "notebook.ipynb", workspace)
    assert secret.read_text() == "secret"
    assert worker.workspace_file(workspace / "safe.ipynb", workspace) == workspace / "safe.ipynb"


def test_worker_environment_ignores_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "old")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "old")
    monkeypatch.setenv("MY_PASSWORD", "old")
    monkeypatch.setenv("PYTHONPATH", "/other/repo")
    env = runner.worker_environment(tmp_path)
    assert not any(k in env for k in ("OPENAI_API_KEY", "AWS_ACCESS_KEY_ID", "MY_PASSWORD"))
    assert env["PYTHONPATH"] == str(tmp_path / "src")


def test_meter_records_raw_request_once_and_redacts_failure(tmp_path, monkeypatch):
    class Router:
        async def acompletion(self, *args, **kwargs):
            if kwargs.get("fail"):
                raise ValueError("secret-test-key")
            return types.SimpleNamespace(model="test", choices=[], usage={"prompt_tokens": 10, "completion_tokens": 2})
    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(Router=Router))
    restore = worker.install_meter(tmp_path, "secret-test-key")
    async def run():
        await Router().acompletion("test", [{"role": "user", "content": "query"}])
        with pytest.raises(ValueError):
            await Router().acompletion("test", [], fail=True)
    try:
        asyncio.run(run())
    finally:
        restore()
    calls = runner.read_calls(tmp_path / "model_calls.jsonl")
    assert len(calls) == 2 and calls[0]["usage"]["input_tokens"] == 10
    assert calls[1]["error"] == "<REDACTED>"


def test_external_blind_evidence_and_null_usage(setup, tmp_path):
    import evaluate
    _, output, invoke, _ = setup
    assert runner.main(invoke([("Analyze", 5)])) == 0
    attempt = Path(results(output)[0]["attempt_dir"])
    result = json.loads((attempt / "result.json").read_text())
    result["external_usage"]["input_tokens"] = None
    (attempt / "result.json").write_text(json.dumps(result))
    mapping, blind = tmp_path / "mapping.json", tmp_path / "blind"
    assert evaluate.main(["blind", "--runs", str(output), "--out", str(blind), "--map", str(mapping)]) == 0
    [record] = json.loads(mapping.read_text()).values()
    assert record["tokens"] is None
    assert list(blind.rglob("map.png")) and list(blind.rglob("notebook.ipynb"))
    assert not list(blind.rglob("transcript.jsonl")) and not list(blind.rglob("worker.json"))
    (attempt / "evidence_manifest.json").write_text(json.dumps({"files": ["../../private.nc"]}))
    with pytest.raises(ValueError, match="Unsafe"):
        list(evaluate.evidence_files(attempt))


def test_external_inventory_does_not_require_oceanx_tree(setup):
    import evaluate
    _, output, invoke, _ = setup
    assert runner.main(invoke([("Analyze", 5)])) == 0
    attempt = Path(results(output)[0]["attempt_dir"])
    record = evaluate.run_record(attempt, json.loads((output / "arm.json").read_text()))
    assert record["complete"] and record["tree"] is None
    assert "research tree" in record["not_applicable"]
    assert record["tokens"]["input_tokens"] == 100
    assert "agent conversations" not in record["missing"]


def test_external_missing_usage_still_allows_score_summary(tmp_path):
    import evaluate
    from test_evaluate import make_arm, score_file
    folder = make_arm(tmp_path / "runs", "F", None, {"Q01": 2})
    attempt = folder / "Q01/attempt-1"
    result = json.loads((attempt / "result.json").read_text())
    result["external_usage"] = {"input_tokens": None, "output_tokens": None}
    (attempt / "result.json").write_text(json.dumps(result))
    mapping, blind = tmp_path / "mapping.json", tmp_path / "blind"
    evaluate.main(["blind", "--runs", str(folder), "--out", str(blind), "--map", str(mapping)])
    [(blind_id, _entry)] = json.loads(mapping.read_text()).items()
    scores = tmp_path / "scores"
    scores.mkdir()
    (scores / f"{blind_id}.json").write_text(json.dumps(score_file(blind_id, "Q01", 2)))
    prereg = tmp_path / "prereg.yaml"
    prereg.write_text("experiment: external\ncomparisons: []\n")
    evaluate.main(["freeze", "--prereg", str(prereg)])
    evaluate.main(["summarize", "--prereg", str(prereg), "--map", str(mapping),
                   "--scores", str(scores), "--out", str(tmp_path / "report")])
    summary = json.loads((tmp_path / "report/summary.json").read_text())
    assert summary["arms"]["F"]["tokens"] is None
    assert "n/a" in (tmp_path / "report/report.md").read_text()


def test_checkout_pin(tmp_path, monkeypatch):
    (tmp_path / "src/fhda").mkdir(parents=True)
    (tmp_path / "src/fhda/data_analysis_env.py").write_text("")
    monkeypatch.setattr(runner, "_git", lambda root, *args: runner.FINCH_COMMIT if args[0] == "rev-parse" else "")
    runner.validate_checkout(tmp_path, runner.FINCH_COMMIT)
    with pytest.raises(ValueError, match="full commit"):
        runner.validate_checkout(tmp_path, "main")
    monkeypatch.setattr(runner, "_git", lambda *_: "modified")
    with pytest.raises(ValueError, match="clean"):
        runner.validate_checkout(tmp_path, runner.FINCH_COMMIT)
