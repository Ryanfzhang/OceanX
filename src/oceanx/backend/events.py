"""Shared event bus with transport-local sequence assignment."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from oceanx.backend.auth import Principal
from oceanx.protocol.v2.models import ClientKind, EventEnvelope, RequestCompletedEvent

EventSender = Callable[[EventEnvelope], Awaitable[None] | None]
HandshakeValidator = Callable[[str | None, str | None], Awaitable[bool] | bool]


def _delivery_result(result: dict[str, Any]) -> dict[str, Any]:
    """Project a terminal result for transport, without mutating durable records.

    Full plans, Expert reports and code execution logs already live in the
    request/team/execution stores. They are not rendering inputs: the desktop
    gets its Canvas from team snapshots and loads participant transcripts on
    demand. Repeating the full audit trail here can drop the *entire* final
    answer at the desktop's frame-size guard. Keep usage for batch consumers.
    """
    projected = dict(result)
    provenance = result.get("team_provenance")
    if isinstance(provenance, dict):
        detail_keys = ("work_plan", "work", "code_executions")
        omitted = [key for key in detail_keys if key in provenance]
        if omitted:
            summary = {key: value for key, value in provenance.items() if key not in detail_keys}
            for key, count_key in (("work", "work_count"), ("code_executions", "code_execution_count")):
                if isinstance(provenance.get(key), list):
                    summary[count_key] = len(provenance[key])
            summary["details_omitted"] = omitted
            projected["team_provenance"] = summary

    # request.status.get wraps a persisted terminal event. Apply the same
    # projection to old oversized records on replay, never rewriting the DB.
    terminal = result.get("terminal_event")
    if isinstance(terminal, dict) and terminal.get("type") == "request.completed":
        payload = terminal.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
            projected["terminal_event"] = {
                **terminal,
                "payload": {**payload, "result": _delivery_result(payload["result"])},
            }
    return projected


@dataclass
class BackendClient:
    """One authenticated transport connection, not an authority source."""

    transport: Literal["stdio", "websocket"]
    expected_client_kind: ClientKind
    sender: EventSender
    verified_local_desktop: bool = False
    handshake_validator: HandshakeValidator | None = None
    connection_id: str = field(default_factory=lambda: f"conn_{uuid4().hex}")
    client_id: str | None = None
    session_id: str | None = None
    workspace_id: str | None = None
    principal: Principal | None = None
    client_capability: str | None = None
    resume_client_id: str | None = None
    resume_session_id: str | None = None
    resume_workspace_id: str | None = None
    resume_principal: Principal | None = None
    sequence: int = 0
    closed: bool = False

    @property
    def authenticated(self) -> bool:
        return self.client_id is not None and self.session_id is not None and self.principal is not None

    async def validate_handshake(
        self,
        bootstrap_token: str | None,
        client_capability: str | None,
    ) -> bool:
        if self.handshake_validator is None:
            return True
        result = self.handshake_validator(bootstrap_token, client_capability)
        return bool(await result) if inspect.isawaitable(result) else bool(result)


class EventBus:
    """Deliver one durable event through multiple sequence-owning transports."""

    def __init__(self) -> None:
        self._clients: dict[str, BackendClient] = {}
        self._lock = asyncio.Lock()

    async def register(self, client: BackendClient) -> None:
        async with self._lock:
            self._clients[client.connection_id] = client

    async def unregister(self, client: BackendClient) -> None:
        async with self._lock:
            self._clients.pop(client.connection_id, None)
            client.closed = True

    async def emit_local(self, client: BackendClient, event: EventEnvelope) -> None:
        await self._send(client, event)

    async def emit_workspace(self, event: EventEnvelope) -> None:
        """Broadcast a domain event only to authenticated workspace readers."""

        async with self._lock:
            clients = list(self._clients.values())
        for client in clients:
            if (
                client.authenticated
                and client.principal is not None
                and client.principal.allows("workspace.read")
                and client.session_id is not None
                and event.workspace_id is not None
                and client.workspace_id == event.workspace_id
            ):
                await self._send(client, event)

    async def emit_request_session(
        self,
        event: EventEnvelope,
        *,
        session_id: str | None,
        principal_key: str,
    ) -> None:
        """Route a request-local replay to the owning local principal/session."""

        async with self._lock:
            clients = list(self._clients.values())
        for client in clients:
            if (
                client.authenticated
                and client.session_id == session_id
                and client.principal is not None
                and client.principal.key == principal_key
            ):
                await self._send(client, event)

    async def emit_system(self, event: EventEnvelope) -> None:
        async with self._lock:
            clients = list(self._clients.values())
        for client in clients:
            if client.authenticated:
                await self._send(client, event)

    async def _send(self, client: BackendClient, event: EventEnvelope) -> None:
        if client.closed:
            return
        # All delivery paths (live, reconnect replay, request status, stdio and
        # websocket) share this boundary. Keep the committed event unmodified.
        if isinstance(event, RequestCompletedEvent):
            event = event.model_copy(update={
                "payload": event.payload.model_copy(update={
                    "result": _delivery_result(event.payload.result),
                }),
            })
        client.sequence += 1
        sequenced = event.model_copy(update={"sequence": client.sequence})
        result = client.sender(sequenced)
        if inspect.isawaitable(result):
            await result


__all__ = ["BackendClient", "EventBus", "EventSender", "HandshakeValidator"]
