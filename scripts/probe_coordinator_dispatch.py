"""Paid Coordinator-only probe; stop before executing the first dispatch batch.

Uses the production Server, prompt, model and native tools. The test-only hook
does not tell the model it is being inspected and never launches an Expert.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def install_observer(root):
    from langchain.agents.middleware.types import AgentMiddleware, hook_config
    from langchain_core.callbacks import AsyncCallbackHandler

    from oceanx.research import graphs

    class Inputs(AsyncCallbackHandler):
        async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
            save(root / f"model-input-{run_id}.json",
                 [[m.model_dump(mode="json") for m in batch] for batch in messages])

    class StopBeforeDispatch(AgentMiddleware):
        @hook_config(can_jump_to=["end"])
        async def aafter_model(self, state, runtime):
            last = state["messages"][-1]
            if any(c["name"] in {"start_async_task", "update_async_task"} for c in last.tool_calls):
                save(root / "dispatch.json", last.model_dump(mode="json"))
                return {"jump_to": "end"}
            return None

    original = graphs.build

    async def observed(config, role, **kwargs):
        if role != "coordinator":
            raise RuntimeError("Dispatch-only test must never launch an Expert")
        kwargs["middleware"] = [*(kwargs.get("middleware") or []), StopBeforeDispatch()]
        graph = await original(config, role, **kwargs)
        return graph.with_config(callbacks=[*graph.config.get("callbacks", []), Inputs()])

    graphs.build = observed


async def probe(root, query_file):
    import httpx
    from langgraph_sdk import get_client
    from websockets.asyncio.client import connect

    from oceanx.model_config import load_model_profile

    root.mkdir(parents=True, exist_ok=False)
    case = json.loads(query_file.read_text())
    save(root / "query.json", case)
    profile = load_model_profile("coordinator")
    save(root / "model.json", {"provider": profile.provider, "model": profile.model,
                               "max_tokens": profile.max_tokens})
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token, desktop = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    headers = {"authorization": "Bearer " + token}
    with (root / "server.log").open("w") as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--server",  # noqa: ASYNC220 — isolated test server startup
            "--root", str(root), "--port", str(port)], stdout=log, stderr=log,
            env={**os.environ, "OCEAN_SERVER_TOKEN": token, "OCEAN_DESKTOP_TOKEN": desktop,
                 "OCEAN_SKILL_CURATOR": "0", "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"})
        try:
            url = f"http://127.0.0.1:{port}"
            async with httpx.AsyncClient(timeout=2) as http, asyncio.timeout(90):
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Probe Server exited; inspect server.log")
                    try:
                        if (await http.get(url + "/ok", headers=headers)).is_success:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(.2)
            context, revision = {}, 0
            async with connect(url.replace("http:", "ws:") + "/ocean/protocol",
                additional_headers={**headers, "x-ocean-desktop-token": desktop}, max_size=None) as ws:
                async def request(kind, payload):
                    nonlocal revision
                    request_id = "req_" + uuid4().hex
                    frame = {"protocol_version": 2, "request_id": request_id, "type": kind, "payload": payload}
                    if context:
                        frame.update(context=dict(context), expected_workspace_revision=revision)
                    await ws.send(json.dumps(frame))
                    while True:
                        event = json.loads(await ws.recv())
                        body = event.get("payload", {})
                        revision = max(revision, body.get("workspace_revision") or 0)
                        if event["type"] == "system.ready":
                            context.update(client_id=body["client_id"], session_id=body["session_id"])
                            return event
                        if event.get("request_id") == request_id and event["type"] in {"request.completed", "request.failed", "system.error", "interaction.requested"}:
                            if event["type"] != "request.completed":
                                save(root / "setup-error.json", event)
                                raise RuntimeError(f"Setup failed for {kind}; see setup-error.json")
                            return event

                await request("system.handshake", {"client_kind": "desktop", "client_version": "dispatch-probe", "supported_protocol_versions": [2]})
                context["workspace_id"] = "ws_" + uuid4().hex
                workspace = root / "workspace"
                workspace.mkdir()
                await request("workspace.open", {"path": str(workspace)})
                task = await request("task.create", {"title": "Coordinator dispatch-only probe"})
                context["task_id"] = task["payload"]["result"]["task"]["task_id"]
                for path in case["datasets"]:
                    await request("dataset.import", {"local_path": path, "materialization_level": "local_reference"})
            client = get_client(url=url, headers=headers, api_key=None)
            thread = await client.threads.create()
            binding = {"workspace_id": context["workspace_id"], "task_id": context["task_id"],
                       "workspace_path": str(workspace), "original_question": case["query"],
                       "request_id": "req_dispatch_probe"}
            start = time.monotonic()
            run = await client.runs.create(thread["thread_id"], "coordinator",
                input={"messages": [{"role": "user", "content": case["query"]}]},
                config={"configurable": binding, "recursion_limit": 2_147_483_647})
            save(root / "binding.json", {**binding, "thread_id": thread["thread_id"], "run_id": run["run_id"]})
            print("Coordinator running; Experts will not start.", flush=True)
            try:
                async with asyncio.timeout(600):  # this probe's boundary, not a research quota
                    while True:
                        status = await client.runs.get(thread["thread_id"], run["run_id"])
                        if status["status"] not in {"pending", "running"}:
                            break
                        await asyncio.sleep(.5)
            finally:
                status = await client.runs.get(thread["thread_id"], run["run_id"])
                if status["status"] in {"pending", "running"}:
                    await client.runs.cancel(thread["thread_id"], run["run_id"], wait=True)
            state = await client.threads.get_state(thread["thread_id"])
            save(root / "state.json", state)
            assert not state.get("values", {}).get("async_tasks"), "Unexpected Expert launched"
            result = {"run_status": status["status"], "wall_seconds": time.monotonic() - start,
                      "dispatch_captured": (root / "dispatch.json").is_file(), "experts_started": 0}
            save(root / "result.json", result)
            print(json.dumps(result), flush=True)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--query-file", type=Path)
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.server:
        install_observer(args.root)
        from oceanx.research.server import main
        sys.argv = [sys.argv[0], "--state", str(args.root / "state"), "--port", str(args.port)]
        main()
    else:
        asyncio.run(probe(args.root.resolve(), args.query_file))
