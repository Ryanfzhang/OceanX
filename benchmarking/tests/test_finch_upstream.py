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


def test_pinned_transport_sends_disabled_thinking_with_required_tools(tmp_path, monkeypatch):
    """Exercise real Router/OpenAI serialization, not merely its configuration."""
    import httpx
    import ldp.graph.common_ops as common
    from aviary.core import Message, Tool

    requests = []

    async def send(client, request, **kwargs):
        assert request.url.host == "example.invalid"  # Never contact an API.
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "deepseek-flash"
        assert body["thinking"] == {"type": "disabled"}
        if body["tool_choice"] == "required":
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_1", "type": "function", "function": {
                    "name": "add", "arguments": '{"a":2,"b":3}'}}]}
        else:
            message = {"role": "assistant", "content": "Thought: add the numbers."}
        return httpx.Response(200, request=request, json={
            "id": "test-completion", "object": "chat.completion", "created": 1,
            "model": "deepseek-flash", "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    def add(a: int, b: int) -> int:
        """Add two numbers.

        Args:
            a: First number.
            b: Second number.
        """
        return a + b

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    path = tmp_path / ".env"
    path.write_text("DEEPSEEK_API_KEY=test-secret\n"
                    "BENCH_OPENAI_BASE_URL=https://example.invalid/v1\n")
    restore = worker.install_model(load_config(path))
    try:
        async def calls():
            model = common.LLMModel(config={"name": "deepseek-flash"})
            messages = [Message(role="user", content="Add 2 and 3.")]
            tools = [Tool.from_function(add)]
            await model.call_single(messages, tools=tools, tool_choice="none")
            result = await model.call_single(messages, tools=tools, tool_choice="required")
            assert result.messages[0].tool_calls[0].function.name == "add"
        asyncio.run(calls())
    finally:
        restore()
    assert [body["tool_choice"] for body in requests] == ["none", "required"]


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
        assert params["extra_body"] == {"thinking": {"type": "disabled"}}
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
    assert [request["tool_choice"] for request in requests] == ["none", "required"] * 2
    assert sum(call["usage"]["input_tokens"] for call in calls) == 40
    assert "test-secret" not in (tmp_path / "transcript.jsonl").read_text()
    executions = [json.loads(line) for line in (tmp_path / "code_runs.jsonl").read_text().splitlines()]
    assert [e["state"] for e in executions] == ["running", "succeeded"]
