"""Start Agent Server and forward the desktop protocol. No agents run in this gateway."""
from __future__ import annotations

import asyncio
import os
import secrets
import socket
import sys
from pathlib import Path

import httpx
from websockets.asyncio.client import connect


async def run_desktop_gateway(state_directory: Path, *, expected_client_kind="desktop"):
    root = state_directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    if getattr(sys, "frozen", False):
        from oceanx.sandbox.execution import current_python_executable
        executable = str(current_python_executable())
    else:
        executable = sys.executable
    token = secrets.token_urlsafe(32)
    desktop_token = secrets.token_urlsafe(32)
    environment = {**os.environ, "OCEAN_SERVER_TOKEN": token,
                   "OCEAN_DESKTOP_TOKEN": desktop_token,
                   "OCEAN_CLIENT_KIND": expected_client_kind,
                   "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}
    # Server diagnostics go to a file, never corrupt the desktop JSONL transport.
    log = (root / "agent-server.log").open("ab")
    process = await asyncio.create_subprocess_exec(executable, "-m", "oceanx.research.server",
        "--state", str(root), "--port", str(port), env=environment,
        stdin=asyncio.subprocess.DEVNULL, stdout=log, stderr=log)
    headers = {"authorization": "Bearer " + token}
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            async with asyncio.timeout(90):
                while True:
                    if process.returncode is not None:
                        raise RuntimeError(f"Agent Server failed to start. See {root / 'agent-server.log'}")
                    try:
                        response = await client.get(f"http://127.0.0.1:{port}/ok", headers=headers)
                        if response.is_success:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.2)
        async with connect(f"ws://127.0.0.1:{port}/ocean/protocol",
                           additional_headers={**headers, "x-ocean-desktop-token": desktop_token},
                           max_size=None) as websocket:
            async def inbound():
                while True:
                    line = await asyncio.to_thread(sys.stdin.buffer.readline)
                    if not line:
                        return
                    await websocket.send(line.decode("utf-8"))
            async def outbound():
                async for frame in websocket:
                    sys.stdout.write("OHJSON:" + frame + "\n")
                    sys.stdout.flush()
            tasks = [asyncio.create_task(inbound()), asyncio.create_task(outbound())]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        return 0
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=30)
            except TimeoutError:
                process.kill()
                await process.wait()
        log.close()
