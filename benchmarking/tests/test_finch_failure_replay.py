"""Offline characterization of the observed Q07/Q08 Finch failures.

Q07 repeats its four recorded tool choices. Q08 reconstructs the observed
60-step pattern (one invalid bash, 58 directory listings, one notebook edit),
without claiming to replay the unavailable original model responses or data.
Real pinned Finch/LDP/LiteLLM serialize the requests; HTTP and notebook
execution are intercepted. No provider, input data or host kernel is used.
"""
import asyncio
import json
from collections import Counter

import pytest

pytest.importorskip("fhda")

import httpx
import nbformat
from fhda.notebook_env import NBEnvironment

from benchmark_config import load_config
import finch_worker as worker
import run_finch as runner


def observed_actions(task):
    if task == "Q07":
        return [
            ("list_workdir", {}),
            ("bash", {"command": "ls -la /inputs/0/thetao"}),
            ("bash", {"command": "ls -la /inputs/1/so"}),
            ("submit_answer", {"answer": "placeholder"}),
        ]
    return (
        [("bash", {"command": "ls -la /inputs/"})]
        + [("list_workdir", {})] * 53
        + [("edit_cell", {"contents": 'print("Input-file inspection only")'})]
        + [("list_workdir", {})] * 5
    )


@pytest.mark.parametrize("task", ["Q07", "Q08"])
def test_existing_failure_pattern_through_real_serialized_requests(
    tmp_path, monkeypatch, task,
):
    actions = observed_actions(task)
    workspace = tmp_path / "workspace"
    (workspace / "outputs").mkdir(parents=True)
    (workspace / "scratch").mkdir()
    (tmp_path / "worker.json").write_text(json.dumps({
        "workspace": str(workspace), "mounts": [], "max_steps": 60,
        "temperature": 1, "execution_timeout": 300,
    }))
    (tmp_path / "submitted_prompt.txt").write_text(
        "Analyze the supplied scientific data and submit a report supported by executed analysis."
    )
    path = tmp_path / ".env"
    path.write_text(
        "DEEPSEEK_API_KEY=offline-test-key\n"
        "BENCH_OPENAI_BASE_URL=https://example.invalid/v1\n"
    )
    requests, executions, action_index = [], [], 0

    async def send(client, request, **kwargs):
        nonlocal action_index
        # Replace the actual HTTP transport, rather than bypassing serialization.
        assert request.url.host == "example.invalid"
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "deepseek-flash"
        assert body["thinking"] == {"type": "disabled"}
        assert body["temperature"] == 1
        assert body["parallel_tool_calls"] is False
        definitions = {tool["function"]["name"]: tool["function"] for tool in body["tools"]}
        assert set(definitions) == {"edit_cell", "list_workdir", "submit_answer"}
        assert "contents" in definitions["edit_cell"]["parameters"]["properties"]
        assert "answer" in definitions["submit_answer"]["parameters"]["properties"]
        if body["tool_choice"] == "required":
            name, arguments = actions[action_index]
            action_index += 1
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"recorded_action_{action_index}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }]}
        else:
            assert body["tool_choice"] == "none"
            message = {"role": "assistant", "content": "Recorded action replay."}
        return httpx.Response(200, request=request, json={
            "id": f"offline_{len(requests)}", "object": "chat.completion", "created": 1,
            "model": "deepseek-flash", "choices": [{
                "index": 0, "message": message,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
            }], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    async def notebook_execution(spec, log):
        executions.append(spec)
        notebook = nbformat.read(workspace / "notebook.ipynb", as_version=4)
        notebook.cells[-1].execution_count = 1
        notebook.cells[-1].outputs = [
            nbformat.v4.new_output("stream", name="stdout", text="Input-file inspection only\n")
        ]
        nbformat.write(notebook, workspace / "notebook.ipynb")
        return 0, "Recorded execution output."

    async def no_host_kernel(*args, **kwargs):
        pytest.fail("An offline replay must never start an unrestricted host kernel")

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    monkeypatch.setattr(worker, "execute_notebook", notebook_execution)
    monkeypatch.setattr(NBEnvironment, "_run_notebook_docker", no_host_kernel)
    result = asyncio.run(worker.episode(tmp_path, load_config(path)))
    transcript = [
        json.loads(line) for line in (tmp_path / "transcript.jsonl").read_text().splitlines()
    ]
    observations = [
        message["content"] for event in transcript if event["type"] == "observations"
        for message in event["messages"] if message.get("role") == "tool"
    ]
    notebook = nbformat.read(workspace / "notebook.ipynb", as_version=4)
    assert len(requests) == 2 * len(actions)
    assert [r["tool_choice"] for r in requests] == ["none", "required"] * len(actions)
    assert action_index == len(actions)
    assert Counter(name for name, _ in actions)["list_workdir"] == (1 if task == "Q07" else 58)
    assert sum("Invalid tool call: bash" in str(o) for o in observations) == (2 if task == "Q07" else 1)
    assert list((workspace / "outputs").iterdir()) == []
    if task == "Q07":
        assert result == {"status": "completed", "stop_reason": None, "steps": 4}
        assert (tmp_path / "answer.md").read_text() == "placeholder"
        assert not notebook.cells and not executions
        check = runner.delivery_check(tmp_path)
        assert check["status"] == "invalid" and check["issues"] == ["placeholder_answer"]
        assert check["successful_notebook_executions"] == 0
    else:
        assert result == {"status": "failed", "stop_reason": "step_limit", "steps": 60}
        assert not (tmp_path / "answer.md").exists()
        assert len(notebook.cells) == len(executions) == 1
        check = runner.delivery_check(tmp_path)
        assert check["status"] == "not_submitted"
        assert check["successful_notebook_executions"] == 1

    # Keep inspectable transport evidence alongside pytest's temporary attempt.
    # Do not write headers, URLs, model credentials or reasoning responses.
    (tmp_path / "serialized_requests.json").write_text(json.dumps([
        {k: body[k] for k in ("tools", "tool_choice", "temperature", "parallel_tool_calls", "thinking")}
        for body in requests
    ], indent=2))
    (tmp_path / "replay_result.json").write_text(json.dumps(result, indent=2))
    (tmp_path / "delivery_check.json").write_text(json.dumps(check, indent=2))
