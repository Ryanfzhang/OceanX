"""Real pinned Finch/LDP interfaces, fake model and Docker; run in finch-bench.

The ordinary OceanX environment skips this module (Finch is intentionally separate).
No notebook code is executed on the host and no provider request is made.
"""
import asyncio
import json

import pytest

pytest.importorskip("fhda")

import aiodocker
import finch_worker as worker
import litellm
import nbformat
from benchmark_config import Config, Endpoint
from fhda.notebook_env import NBEnvironment


def test_pinned_agent_notebook_delivery_and_usage(tmp_path, monkeypatch):
    assert worker.dependency_check()["libraries"]["ldp"] == "0.26.0"
    workspace = tmp_path / "workspace"
    (workspace / "outputs").mkdir(parents=True)
    spec = {"workspace": str(workspace), "mounts": [], "image": "test-image",
            "uid": 1000, "gid": 1000, "memory_bytes": 1000000, "cpus": 1,
            "container_name": "oceanx-finch-test", "max_steps": 3,
            "temperature": 1, "execution_timeout": 10}
    (tmp_path / "worker.json").write_text(json.dumps(spec))
    (tmp_path / "submitted_prompt.txt").write_text("Compute 2 + 3 and submit the answer.")
    containers, requests = [], []

    class FakeDocker:
        @property
        def containers(self):
            return self

        async def run(self, config, name):
            containers.append(config)
            return self

        async def stop(self):
            pass

        async def delete(self):
            pass

        async def close(self):
            pass

    async def notebook_execution(environment):
        # Exercise real edit/save/reload/render interfaces, not a host Python kernel.
        cell = environment.state.cells[-1]
        cell.execution_count = 1
        cell.outputs = [nbformat.v4.new_output("stream", name="stdout", text="5\n")]
        environment.state.save_nb()
        environment.state.reload_nb()
        return "Executed all cells."

    async def acompletion(router, *args, **kwargs):
        params = router.model_list[0]["litellm_params"]
        assert params["model"] == "openai/gpt-4o"
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
        return litellm.ModelResponse(model="gpt-4o", choices=[{
            "index": 0, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
            "message": message}], usage={"prompt_tokens": 10, "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 2}})

    monkeypatch.setattr(aiodocker, "Docker", FakeDocker)
    monkeypatch.setattr(NBEnvironment, "_run_notebook_docker", notebook_execution)
    monkeypatch.setattr(litellm.Router, "acompletion", acompletion)
    config = Config("gpt-4o", "openai", {"openai": Endpoint("https://example.invalid/v1", "test-secret")}, 100)
    result = asyncio.run(worker.episode(tmp_path, config))
    assert result == {"status": "completed", "stop_reason": None, "steps": 2}
    assert (tmp_path / "answer.md").read_text() == "The sum is 5."
    notebook = nbformat.read(workspace / "notebook.ipynb", as_version=4)
    assert notebook.cells[0].outputs[0].text == "5\n"
    assert containers[0]["HostConfig"]["NetworkMode"] == "none"
    calls = [json.loads(line) for line in (tmp_path / "model_calls.jsonl").read_text().splitlines()]
    assert len(calls) == len(requests) == 4  # Two ReAct calls per step.
    assert sum(call["usage"]["input_tokens"] for call in calls) == 40
    assert "test-secret" not in (tmp_path / "transcript.jsonl").read_text()
    executions = [json.loads(line) for line in (tmp_path / "code_runs.jsonl").read_text().splitlines()]
    assert [e["state"] for e in executions] == ["running", "succeeded"]
