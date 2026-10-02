"""Real pinned Finch/LDP interfaces, fake model and sandbox; run in finch-bench.

The ordinary OceanX environment skips this module (Finch is intentionally separate).
No notebook code is executed on the host and no provider request is made.
"""
import asyncio
import json

import pytest

pytest.importorskip("fhda")

import finch_worker as worker
import litellm
import nbformat
from benchmark_config import load_config
from fhda.notebook_env import NBEnvironment


def test_pinned_agent_notebook_delivery_and_usage(tmp_path, monkeypatch):
    assert worker.dependency_check()["libraries"]["ldp"] == "0.26.0"
    workspace = tmp_path / "workspace"
    (workspace / "outputs").mkdir(parents=True)
    spec = {"workspace": str(workspace), "mounts": [], "max_steps": 3,
            "temperature": 1, "execution_timeout": 10}
    (tmp_path / "worker.json").write_text(json.dumps(spec))
    (tmp_path / "submitted_prompt.txt").write_text("Compute 2 + 3 and submit the answer.")
    requests, executions_seen = [], []

    async def notebook_execution(spec, log_path):
        # Exercise real edit/save/reload/render interfaces, not a host Python kernel.
        assert spec["workspace"] == str(workspace)
        executions_seen.append(spec)
        notebook = nbformat.read(workspace / "notebook.ipynb", as_version=4)
        cell = notebook.cells[-1]
        cell.execution_count = 1
        cell.outputs = [nbformat.v4.new_output("stream", name="stdout", text="5\n")]
        nbformat.write(notebook, workspace / "notebook.ipynb")
        return 0, "Executed all cells."

    async def acompletion(router, *args, **kwargs):
        params = router.model_list[0]["litellm_params"]
        assert params["model"] == "openai/deepseek-flash"
        assert params["api_base"] == "https://example.invalid/v1"
        assert params["api_key"] == "test-secret"
        requests.append(kwargs)
        if kwargs.get("tools") and kwargs.get("tool_choice") != "none":
            edited = any(r.get("tools") and r.get("tool_choice") != "none" for r in requests[:-1])
            name = "submit_answer" if edited else "edit_cell"
            arguments = {"answer": "The sum is 5."} if edited else {"contents": "print(2 + 3)"}
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"call_{len(requests)}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)}}]}
        else:
            message = {"role": "assistant", "content": "Thought: use the notebook, then submit."}
        return litellm.ModelResponse(model="deepseek-flash", choices=[{
            "index": 0, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
            "message": message}], usage={"prompt_tokens": 10, "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 2}})

    monkeypatch.setattr(worker, "execute_notebook", notebook_execution)
    async def never_start_unisolated_kernel(state):
        raise AssertionError("Upstream host kernel must never start")
    monkeypatch.setattr(NBEnvironment, "_run_notebook_docker", never_start_unisolated_kernel)
    monkeypatch.setattr(litellm.Router, "acompletion", acompletion)
    env_file = tmp_path / '.env'
    env_file.write_text('DEEPSEEK_API_KEY=test-secret\nBENCH_MAX_TOKENS=100\n'
                        'BENCH_OPENAI_BASE_URL=https://example.invalid/v1\n')
    config = load_config(env_file)
    result = asyncio.run(worker.episode(tmp_path, config))
    assert result == {"status": "completed", "stop_reason": None, "steps": 2}
    assert (tmp_path / "answer.md").read_text() == "The sum is 5."
    notebook = nbformat.read(workspace / "notebook.ipynb", as_version=4)
    assert notebook.cells[0].outputs[0].text == "5\n"
    assert len(executions_seen) == 1
    calls = [json.loads(line) for line in (tmp_path / "model_calls.jsonl").read_text().splitlines()]
    assert len(calls) == len(requests) == 4  # Two ReAct calls per step.
    assert sum(call["usage"]["input_tokens"] for call in calls) == 40
    assert "test-secret" not in (tmp_path / "transcript.jsonl").read_text()
    executions = [json.loads(line) for line in (tmp_path / "code_runs.jsonl").read_text().splitlines()]
    assert [e["state"] for e in executions] == ["running", "succeeded"]
