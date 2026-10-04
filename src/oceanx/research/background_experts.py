"""Experts that keep working while the Coordinator goes on.

DeepAgents' ``task`` returns only when its subagent has finished, and every tool call of one model turn
must return before the model is called again. Experts delegated together were therefore handed back
together: in Q08 of the 40-call batch B1.3 returned after 14 minutes, and its follow-up, the longest node
of the run, could start only when the slowest sibling returned at 41 minutes.

Here a ``task`` call starts its Expert as a background job of the same Coordinator run and returns as
soon as the next running Expert finishes. The native tool runs unchanged inside the job, so its start and
end events, its receipt, its tree binding and its checkpoints are what they were; only the moment the
Coordinator is called again changes. A receipt whose own call has already returned travels with the next
``task`` or ``await_experts`` result. Whether to continue one line at once or to wait for several results
is the Coordinator's decision; ``await_experts`` is how it waits.
"""
from __future__ import annotations

import asyncio
import dataclasses
import time
import uuid
from dataclasses import dataclass

from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command
from pydantic import BaseModel, Field

from oceanx.research.delegation import infer_node_id

AWAIT_TOOL = "await_experts"
# DeepAgents moves a tool result longer than 16,000 characters to a file; one delivery stays below that.
DELIVERY_CHARS = 12_000
NOTHING_TO_WAIT_FOR = "No Expert is running and no receipt is waiting."
AWAIT_DESCRIPTION = (
    "Wait for Experts that are working in the background. With no arguments it returns as soon as the "
    "next one finishes, with every receipt you have not yet seen and the Experts still running. Give "
    "node_ids to wait until those research-tree nodes have all returned, or wait_for_all for every "
    "running Expert: use these when the next question depends on several results together. Call it "
    "when you have nothing to delegate; never finish while an Expert is still running."
)


@dataclass
class _Job:
    """One Expert that a ``task`` call started."""

    label: str  # "B1.3 (ocean_process_expert)"
    node_id: str | None
    assignment: tuple[str, str]  # the role and what it works on: the node, or the question itself
    started: float
    work: asyncio.Future
    in_call: bool = True  # its own task call has not returned yet
    delivered: bool = False


def _receipt(result) -> str:
    """The receipt text of a native task result (a Command carrying a ToolMessage, or the message)."""
    update = getattr(result, "update", None)
    messages = ((update.get("messages") or ()) if isinstance(result, Command) and isinstance(update, dict)
                else (result,))
    return "\n".join(m.text for m in messages if isinstance(m, ToolMessage)) or str(result)


def appended(result, text: str):
    """A tool result, the native task Command or a ToolMessage, with ``text`` added to its message."""
    def add(message):
        return (message.model_copy(update={"content": f"{message.text}\n\n{text}"})
                if isinstance(message, ToolMessage) else message)

    update = getattr(result, "update", None)
    if isinstance(result, Command) and isinstance(update, dict) and update.get("messages"):
        return dataclasses.replace(result, update={
            **update, "messages": [add(message) for message in update["messages"]]})
    return add(result)


def _turn(state, call_id) -> str:
    """The model turn a tool call belongs to; the waiting calls of one turn return together."""
    messages = state.get("messages", ()) if isinstance(state, dict) else getattr(state, "messages", ())
    for message in reversed(list(messages or ())):
        calls = getattr(message, "tool_calls", None) or ()
        if isinstance(message, AIMessage) and any(call.get("id") == call_id for call in calls):
            return "|".join(str(call.get("id")) for call in calls)
    return str(call_id)


class RunningExperts:
    """The Experts one Coordinator run has started, until each receipt has reached the Coordinator."""

    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        self.jobs: list[_Job] = []
        self._turns: dict[str, asyncio.Event] = {}  # model turn -> set once its waiting calls may return
        self._next = asyncio.Event()  # set, and replaced, each time an Expert finishes

    @staticmethod
    def _described(call: dict) -> tuple[str, str | None, tuple[str, str]]:
        """A task call's label, its tree node and its assignment (the role and what it works on)."""
        args = call.get("args") or {}
        description = str(args.get("description") or "").strip()
        role = str(args.get("subagent_type") or "expert")
        node_id = str(args.get("node_id") or "").strip() or infer_node_id(description)
        label = (f"{node_id} ({role})" if node_id
                 else f"{role}: {description.splitlines()[0][:60]}" if description else role)
        return label, node_id, (role, node_id or description)

    def working_on(self, call: dict) -> _Job | None:
        """The Expert already working on this call's assignment. A second one would share its folder
        and kernel, which are named after the role and the node."""
        assignment = self._described(call)[2]
        return next((job for job in self.running() if job.assignment == assignment), None)

    def start(self, call: dict, work) -> _Job:
        """Run ``work``, the native task call, in the background of this Coordinator run."""
        label, node_id, assignment = self._described(call)
        job = _Job(label, node_id, assignment, self.clock(), asyncio.ensure_future(work))
        job.work.add_done_callback(self._finished)
        self.jobs.append(job)
        return job

    def _finished(self, _work) -> None:
        finished, self._next = self._next, asyncio.Event()
        finished.set()
        for released in self._turns.values():  # every turn that began before this Expert finished
            released.set()

    async def changed(self) -> None:
        """Until the next Expert finishes."""
        await self._next.wait()

    def released(self, turn: str) -> asyncio.Event:
        """Set when the waiting calls of this model turn may return: an Expert has finished since the
        turn began, or a receipt was already waiting when it began."""
        if turn not in self._turns:
            self._turns[turn] = asyncio.Event()
            if self._waiting():
                self._turns[turn].set()
        return self._turns[turn]

    def running(self) -> list[_Job]:
        return [job for job in self.jobs if not job.work.done()]

    def _waiting(self) -> list[_Job]:
        """Finished Experts whose own call returned before they did; a later call carries the receipt."""
        return [job for job in self.jobs if job.work.done() and not job.delivered and not job.in_call]

    def outstanding(self) -> bool:
        """Whether an Expert is still working or a receipt has not reached the Coordinator."""
        return any(not job.delivered for job in self.jobs)

    def own_result(self, job: _Job):
        """What a task call returns for its own Expert; None while that Expert is still working.

        A failed Expert raises here, in its own call or in the call that collects it, as the native
        tool did.
        """
        job.in_call = False
        if not job.work.done():
            return None
        job.delivered = True
        return job.work.result()

    def collect(self, room: int = DELIVERY_CHARS, *, beside_own: bool = False) -> str:
        """The waiting receipts, oldest first, as many whole ones as fit in ``room`` characters.

        On its own a delivery always holds at least one receipt, however long; beside a call's own
        receipt (``beside_own``) one that does not fit waits for the next call.
        """
        blocks: list[str] = []
        for job in self._waiting():
            try:
                block = f"Receipt of {job.label}:\n{_receipt(job.work.result())}"
            except BaseException:
                job.delivered = True  # a failed Expert is raised once, by the call that collects it
                raise
            if (blocks or beside_own) and sum(map(len, blocks)) + len(block) > room:
                break
            job.delivered = True
            blocks.append(block)
        return "\n\n".join(blocks)

    def status(self, skip: _Job | None = None) -> str:
        """What is still to come: receipts not yet read and the Experts still working."""
        waiting = len(self._waiting())
        running = [job for job in self.running() if job is not skip]
        lines = []
        if waiting:
            lines.append(f"{waiting} more receipt{' is' if waiting == 1 else 's are'} ready: call "
                         f"{AWAIT_TOOL} to read {'it' if waiting == 1 else 'them'}.")
        if running:
            now = self.clock()
            lines.append("Still running: " + "; ".join(
                f"{job.label}, {int((now - job.started) // 60)} min" for job in running) + ".")
        return "\n".join(lines)

    async def close(self) -> None:
        """Stop every Expert still working; a cancelled or failed Coordinator run leaves none behind."""
        for job in self.jobs:
            job.work.cancel()
        await asyncio.gather(*(job.work for job in self.jobs), return_exceptions=True)


class AwaitExpertsArgs(BaseModel):
    node_ids: list[str] = Field(
        default_factory=list,
        description=("Research-tree nodes whose Experts must all have returned, for example "
                     "['B1.3', 'B1.4']. Leave empty to return when the next Expert finishes."))
    wait_for_all: bool = Field(
        default=False, description="Wait until every running Expert has returned.")


def await_experts_tool(experts: RunningExperts) -> StructuredTool:
    """The Coordinator's way to wait: for the next Expert, for named nodes, or for all of them."""

    def delivery(named: list[str]) -> str:
        known = {job.node_id for job in experts.jobs}
        unknown = [node for node in named if node not in known]
        return "\n\n".join(filter(None, [
            f"No running Expert for: {', '.join(unknown)}." if unknown else "",
            experts.collect(), experts.status()])) or NOTHING_TO_WAIT_FOR

    async def await_experts(node_ids: list[str] | None = None, wait_for_all: bool = False, *,
                            runtime: ToolRuntime) -> str:
        named = [node.strip() for node in node_ids or [] if node.strip()]
        if wait_for_all or named:
            while any(wait_for_all or job.node_id in named for job in experts.running()):
                await experts.changed()
        elif experts.running():
            await experts.released(_turn(runtime.state, runtime.tool_call_id)).wait()
        return delivery(named)

    def await_experts_now(node_ids: list[str] | None = None, wait_for_all: bool = False, *,
                          runtime: ToolRuntime) -> str:
        # A synchronous run starts no Expert in the background, so there is nothing to wait for.
        # The runtime parameter is what makes the tool node supply it to the coroutine above.
        return delivery([node.strip() for node in node_ids or [] if node.strip()])

    return StructuredTool.from_function(
        name=AWAIT_TOOL, func=await_experts_now, coroutine=await_experts, description=AWAIT_DESCRIPTION,
        args_schema=AwaitExpertsArgs, infer_schema=False)


class BackgroundDelegationMiddleware(AgentMiddleware):
    """Start each Expert in the background; call the Coordinator again when the next one returns.

    Listed first, so everything else about a ``task`` call (the budget check, the tree binding, the
    native tool) runs inside the Expert's job, and a refused assignment is a job that returns at once.
    """

    def __init__(self, experts: RunningExperts) -> None:
        super().__init__()
        self.experts = experts
        self.tools = [await_experts_tool(experts)]

    def wrap_tool_call(self, request, handler):
        return handler(request)  # a synchronous run keeps the blocking task

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        if call.get("name") != "task":
            return await handler(request)
        experts = self.experts
        working = experts.working_on(call)
        if working is not None:
            return ToolMessage(
                content=(f"Not started: {working.label} is already working on this; its receipt comes "
                         f"with a later task or {AWAIT_TOOL} result."),
                tool_call_id=call["id"], name="task", status="error")
        released = experts.released(_turn(request.state, call.get("id")))
        job = experts.start(call, handler(request))
        await released.wait()
        own = experts.own_result(job)
        if own is None:
            started = (f"Started: {job.label} is working in the background; its receipt comes with a "
                       f"later task or {AWAIT_TOOL} result.")
            return ToolMessage(
                content="\n\n".join(filter(None, [experts.collect(), started, experts.status(job)])),
                tool_call_id=call["id"], name="task")
        others = experts.collect(DELIVERY_CHARS - len(_receipt(own)), beside_own=True)
        note = "\n\n".join(filter(None, [others, experts.status()]))
        return appended(own, note) if note else own

    def _kept_waiting(self, response):
        """A reply that would end the run while an Expert is outstanding waits for it instead."""
        if not self.experts.outstanding():
            return response
        result = getattr(response, "result", None)
        reply = result[-1] if isinstance(result, list) and result else response
        if not isinstance(reply, AIMessage) or reply.tool_calls:
            return response
        waiting = reply.model_copy(update={"tool_calls": [{
            "name": AWAIT_TOOL, "args": {}, "id": f"call_{uuid.uuid4().hex}", "type": "tool_call"}]})
        return (dataclasses.replace(response, result=[*result[:-1], waiting])
                if isinstance(result, list) else waiting)

    def wrap_model_call(self, request, handler):
        return self._kept_waiting(handler(request))

    async def awrap_model_call(self, request, handler):
        return self._kept_waiting(await handler(request))


__all__ = [
    "AWAIT_TOOL", "DELIVERY_CHARS", "BackgroundDelegationMiddleware", "RunningExperts", "appended",
    "await_experts_tool",
]
