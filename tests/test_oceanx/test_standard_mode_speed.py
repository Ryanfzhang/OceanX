"""Bounded (standard-mode) requests: scope rule, code time cap, figure API inline, mode check."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from oceanx.agent_tools import ToolExecutionContext
from oceanx.expert_execution import STANDARD_MODE_CODE_SECONDS
from oceanx.research.graphs import (
    STANDARD_COORDINATOR_POLICY, STANDARD_EXPERT_POLICY, research_mode)
from oceanx.tools import OceanExpertRunCodeInput, OceanExpertRunCodeTool, OceanToolServices


def _config(mode=None):
    options = {"workflow_mode": mode} if mode else {}
    return {"configurable": {"request_options": options}}


def test_research_is_the_default_and_standard_is_explicit():
    assert research_mode(_config()) is True
    assert research_mode(_config("research")) is True
    assert research_mode(_config("standard")) is False


def test_standard_policies_state_the_finish_line_and_the_mode_check():
    assert "finish line" in STANDARD_EXPERT_POLICY
    assert f"{STANDARD_MODE_CODE_SECONDS} s" in STANDARD_EXPERT_POLICY
    assert ".preview.png" in STANDARD_EXPERT_POLICY
    assert "switch on Research mode" in STANDARD_COORDINATOR_POLICY
    assert "when unsure, proceed" in STANDARD_COORDINATOR_POLICY


def _run_tool(limit):
    seen = {}

    class Service:
        async def run_python(self, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop after capturing the call")

    tool = OceanExpertRunCodeTool(OceanToolServices(
        workspace_id="ws", provider_id="p", store=SimpleNamespace(), task_id="t",
        agent_thread_id="a", server_run_id="r", expert_code_execution=Service(),
        code_time_limit_seconds=limit))
    try:
        asyncio.run(tool.execute(OceanExpertRunCodeInput(purpose="p", code="1"),
                                 ToolExecutionContext(cwd=Path("."))))
    except RuntimeError:
        pass
    return seen


def test_code_tool_passes_the_mode_time_limit():
    assert _run_tool(STANDARD_MODE_CODE_SECONDS)["_timeout"] == STANDARD_MODE_CODE_SECONDS
    assert _run_tool(None)["_timeout"] is None  # research: the service default (300 s)
