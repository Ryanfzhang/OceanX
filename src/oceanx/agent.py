"""Workspace-bound Deep Agents/LangGraph runtime construction."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oceanx.model_config import ModelRole, load_model_profile
from oceanx.tools import OceanToolServices

OCEAN_EXPERT_MIN_RESPONSE_TOKENS = 24_576


class OceanAgentRuntimeError(RuntimeError):
    """The configured model or checkpoint runtime cannot start."""


@dataclass
class OceanAgentRuntime:
    provider_id: str
    model_id: str
    engine: Any
    _close: Callable[[], Awaitable[None]]

    async def close(self) -> None:
        await self._close()


OceanAgentRuntimeFactory = Callable[
    [OceanToolServices, Path, Callable[[str, str, str], str]],
    Awaitable[OceanAgentRuntime],
]


def configured_provider_id(role: ModelRole = "coordinator") -> str:
    try:
        return load_model_profile(role).provider
    except (OSError, ValueError) as exc:
        raise OceanAgentRuntimeError(str(exc)) from exc


def configured_model_id(role: ModelRole = "coordinator") -> str:
    try:
        return load_model_profile(role).model
    except (OSError, ValueError) as exc:
        raise OceanAgentRuntimeError(str(exc)) from exc


async def build_default_ocean_agent_runtime(
    services: OceanToolServices, workspace_path: Path,
    operation_id_factory: Callable[[str, str, str], str],
) -> OceanAgentRuntime:
    """Subscribe to the Coordinator on Agent Server; never execute a local graph."""
    from oceanx.deep_runtime import DeepAgentEngine
    from oceanx.research.gateway import ServerGraphStream, agent_server_client
    if not services.task_id:
        raise OceanAgentRuntimeError("Research execution requires a task-owned Agent Server thread")
    profile = load_model_profile("coordinator")
    stream = ServerGraphStream(client=agent_server_client(), binding={
        "workspace_id": services.workspace_id, "workspace_path": str(workspace_path),
        "task_id": services.task_id,
    })
    engine = DeepAgentEngine(
        graph=stream,
        thread_id=stream.thread_id,
        operation_id_factory=operation_id_factory,
    )
    async def close():
        pass  # Closing a UI subscriber is not cancellation of the server thread.
    return OceanAgentRuntime(profile.provider, profile.model, engine, close)
