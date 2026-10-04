"""The Coordinator goes on as each Expert returns instead of waiting for the slowest of a batch."""

import asyncio
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command
from pydantic import BaseModel, Field

from oceanx.research.background_experts import (
    AWAIT_TOOL,
    DELIVERY_CHARS,
    BackgroundDelegationMiddleware,
    RunningExperts,
)

ROLE = "ocean_process_expert"


def receipt(node: str) -> str:
    return f"Result: {node} answered.\n\nReport: /reports/{node}/report.md"


class TaskArgs(BaseModel):
    description: str
    subagent_type: str


class World:
    """Experts that finish only when the test lets them, and a record of what happened in which order."""

    def __init__(self, *, failing=(), receipts=None):
        self.gates: dict[str, asyncio.Event] = defaultdict(asyncio.Event)
        self.log: list[tuple[str, str]] = []
        self.failing = set(failing)
        self.receipts = receipts or {}
        self.experts = RunningExperts()

    def finish(self, *nodes: str) -> None:
        for node in nodes:
            self.gates[node].set()

    async def returned(self, node: str) -> None:
        """Until the Expert of ``node`` is no longer running (its job has completed)."""
        while ("started", node) not in self.log or any(
                job.node_id == node for job in self.experts.running()):
            await asyncio.sleep(0)

    def task_tool(self) -> StructuredTool:
        async def atask(description: str, subagent_type: str, runtime: ToolRuntime) -> Command:
            node = description.split(":")[0]
            self.log.append(("started", node))
            await self.gates[node].wait()
            if node in self.failing:
                raise RuntimeError(f"{node} failed")
            self.log.append(("finished", node))
            return Command(update={"messages": [ToolMessage(
                self.receipts.get(node) or receipt(node), tool_call_id=runtime.tool_call_id)]})

        return StructuredTool.from_function(
            name="task", coroutine=atask, description="Ask an Expert.", args_schema=TaskArgs,
            infer_schema=False)


class Coordinator(FakeMessagesListChatModel):
    """A scripted Coordinator that records what each call was shown; ``before[n]`` runs before reply n."""

    seen: list[list[BaseMessage]] = Field(default_factory=list)
    before: dict[int, Any] = Field(default_factory=dict)

    def bind_tools(self, tools: Any, **_kwargs: Any):
        return self

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        hook = self.before.get(len(self.seen))
        if hook is not None:
            await hook()
        return FakeMessagesListChatModel._generate(
            self, messages, stop=stop, run_manager=run_manager, **kwargs)


def call(name: str, call_id: str, **args) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def delegate(*nodes: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[
        call("task", f"task-{node}", description=f"{node}: a question", subagent_type=ROLE) for node in nodes])


def wait(call_id: str = "wait", **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[call(AWAIT_TOOL, call_id, **args)])


def agent(world: World, replies, *, before=None, middleware=()):
    model = Coordinator(responses=list(replies), before=before or {})
    graph = create_agent(model=model, tools=[world.task_tool()], system_prompt="base",
                         middleware=[BackgroundDelegationMiddleware(world.experts), *middleware])
    return graph, model


def run(graph):
    """One Coordinator run; bounded, so a wait that never ends fails the test instead of hanging it."""
    return asyncio.wait_for(graph.ainvoke({"messages": [HumanMessage(content="research")]}), timeout=20)


def tool_text(messages, call_id: str) -> str:
    return next(m.text for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == call_id)


def times_delivered(messages, node: str) -> int:
    return sum(m.text.count(f"Result: {node} answered.") for m in messages if isinstance(m, ToolMessage))


@pytest.mark.asyncio
async def test_a_single_task_returns_its_own_native_receipt_unchanged():
    world = World()
    world.finish("B1.1")
    graph, model = agent(world, [delegate("B1.1"), AIMessage(content="done")])

    result = await run(graph)

    assert tool_text(result["messages"], "task-B1.1") == receipt("B1.1")  # nothing added, as before
    assert len(model.seen) == 2
    assert not world.experts.outstanding()


@pytest.mark.asyncio
async def test_the_coordinator_is_called_again_when_the_first_of_a_batch_returns():
    world = World()
    world.finish("B1.1")
    seen_when_called_again = {}

    async def on_second_call():
        seen_when_called_again["slow finished"] = ("finished", "B1.2") in world.log
        world.finish("B1.2")

    graph, model = agent(world, [delegate("B1.1", "B1.2"), wait(), AIMessage(content="done")],
                         before={2: on_second_call})

    result = await run(graph)

    assert seen_when_called_again == {"slow finished": False}  # no waiting for the slowest of the batch
    shown = model.seen[1]
    first, second = tool_text(shown, "task-B1.1"), tool_text(shown, "task-B1.2")
    assert first.startswith(receipt("B1.1"))
    assert f"Still running: B1.2 ({ROLE}" in first
    assert second.startswith(f"Started: B1.2 ({ROLE}) is working in the background")
    assert "Result: B1.2" not in second
    assert tool_text(result["messages"], "wait").startswith(
        f"Receipt of B1.2 ({ROLE}):\n" + receipt("B1.2"))
    assert times_delivered(result["messages"], "B1.1") == times_delivered(result["messages"], "B1.2") == 1
    assert len(model.seen) == 3


@pytest.mark.asyncio
async def test_a_receipt_stays_with_its_own_call_when_a_sibling_call_returns_first():
    # The slow Expert's call was issued first, so it is also the first to return when the fast one
    # finishes; the fast Expert's receipt must still come from its own call, once.
    world = World()
    world.finish("B1.1")

    async def on_second_call():
        world.finish("B1.2")

    graph, model = agent(world, [delegate("B1.2", "B1.1"), wait(), AIMessage(content="done")],
                         before={2: on_second_call})

    result = await run(graph)

    shown = model.seen[1]
    assert tool_text(shown, "task-B1.1").startswith(receipt("B1.1"))
    assert tool_text(shown, "task-B1.2").startswith(f"Started: B1.2 ({ROLE}) is working in the background")
    assert "B1.1 answered" not in tool_text(shown, "task-B1.2")
    assert times_delivered(result["messages"], "B1.1") == times_delivered(result["messages"], "B1.2") == 1


@pytest.mark.asyncio
async def test_a_follow_up_starts_while_a_sibling_is_still_running():
    world = World()
    world.finish("B1.1")

    async def let_the_sibling_return_once_the_follow_up_runs():
        while ("started", "B1.1.1") not in world.log:
            await asyncio.sleep(0)
        world.finish("B1.2")

    async def on_third_call():
        world.finish("B1.1.1")

    graph, model = agent(
        world,
        [delegate("B1.1", "B1.2"), delegate("B1.1.1"), wait(), AIMessage(content="done")],
        before={3: on_third_call})
    side = asyncio.create_task(let_the_sibling_return_once_the_follow_up_runs())

    result = await run(graph)
    await side

    assert world.log.index(("started", "B1.1.1")) < world.log.index(("finished", "B1.2"))
    carried = tool_text(model.seen[2], "task-B1.1.1")  # the follow-up's call brought the sibling's receipt
    assert carried.startswith(f"Receipt of B1.2 ({ROLE}):\n" + receipt("B1.2"))
    assert f"Started: B1.1.1 ({ROLE}) is working in the background" in carried
    assert "Result: B1.1.1" not in carried
    assert f"Receipt of B1.1.1 ({ROLE})" in tool_text(result["messages"], "wait")
    for node in ("B1.1", "B1.2", "B1.1.1"):
        assert times_delivered(result["messages"], node) == 1


@pytest.mark.asyncio
async def test_a_receipt_that_arrived_while_the_coordinator_was_busy_comes_with_its_next_call():
    world = World()
    world.finish("B1.1")

    async def sibling_returns_during_the_second_call():
        world.finish("B1.2")
        await world.returned("B1.2")

    async def on_third_call():
        world.finish("B1.3")

    graph, model = agent(
        world, [delegate("B1.1", "B1.2"), delegate("B1.3"), wait(), AIMessage(content="done")],
        before={2: sibling_returns_during_the_second_call, 3: on_third_call})

    result = await run(graph)

    carried = tool_text(model.seen[2], "task-B1.3")
    assert carried.startswith(f"Receipt of B1.2 ({ROLE})")  # handed over at once, not at the next completion
    assert f"Started: B1.3 ({ROLE})" in carried
    assert ("finished", "B1.3") in world.log
    assert world.log.index(("finished", "B1.2")) < world.log.index(("started", "B1.3"))
    for node in ("B1.1", "B1.2", "B1.3"):
        assert times_delivered(result["messages"], node) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [{"node_ids": ["B1.2", "B1.3"]}, {"wait_for_all": True}])
async def test_await_experts_can_wait_for_several_results_together(arguments):
    world = World()
    world.finish("B1.1")
    calls_after_one_of_two = {}

    async def release_one_then_the_other():
        while len(model.seen) < 2:
            await asyncio.sleep(0)
        world.finish("B1.2")
        await world.returned("B1.2")
        for _ in range(50):  # the joint wait must not return for one of its two results
            await asyncio.sleep(0)
        calls_after_one_of_two["model calls"] = len(model.seen)
        world.finish("B1.3")

    graph, model = agent(
        world, [delegate("B1.1", "B1.2", "B1.3"), wait(**arguments), AIMessage(content="done")])
    side = asyncio.create_task(release_one_then_the_other())

    result = await run(graph)
    await side

    assert calls_after_one_of_two == {"model calls": 2}
    together = tool_text(result["messages"], "wait")
    assert f"Receipt of B1.2 ({ROLE})" in together and f"Receipt of B1.3 ({ROLE})" in together
    assert len(model.seen) == 3


@pytest.mark.asyncio
async def test_await_experts_says_so_when_nothing_is_running_or_a_node_is_unknown():
    world = World()
    world.finish("B1.1")
    graph, _model = agent(world, [
        delegate("B1.1"), wait("none"), wait("unknown", node_ids=["B9.9"]), AIMessage(content="done")])

    result = await run(graph)

    assert tool_text(result["messages"], "none") == "No Expert is running and no receipt is waiting."
    assert tool_text(result["messages"], "unknown").startswith("No running Expert for: B9.9.")


@pytest.mark.asyncio
async def test_the_coordinator_cannot_finish_while_an_expert_is_still_running():
    world = World()
    world.finish("B1.1")

    async def let_it_return_after_the_early_ending():
        while len(model.seen) < 2:
            await asyncio.sleep(0)
        for _ in range(20):
            await asyncio.sleep(0)
        world.finish("B1.2")

    graph, model = agent(world, [
        delegate("B1.1", "B1.2"), AIMessage(content="An answer before B1.2 returned."),
        AIMessage(content="The answer with both results.")])
    side = asyncio.create_task(let_it_return_after_the_early_ending())

    result = await run(graph)
    await side

    assert result["messages"][-1].text == "The answer with both results."
    early = next(m for m in result["messages"]
                 if isinstance(m, AIMessage) and m.text == "An answer before B1.2 returned.")
    assert [c["name"] for c in early.tool_calls] == [AWAIT_TOOL]  # the wait was added for it
    waited = tool_text(result["messages"], early.tool_calls[0]["id"])
    assert f"Receipt of B1.2 ({ROLE})" in waited
    assert len(model.seen) == 3 and not world.experts.outstanding()


@pytest.mark.asyncio
async def test_a_reply_that_ends_with_every_receipt_delivered_is_left_alone():
    world = World()
    world.finish("B1.1")
    graph, model = agent(world, [delegate("B1.1"), AIMessage(content="done")])

    result = await run(graph)

    assert result["messages"][-1].tool_calls == [] and len(model.seen) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failing, replies", [
    ("B1.1", [delegate("B1.1")]),                          # fails inside its own task call
    ("B1.2", [delegate("B1.1", "B1.2"), wait()]),          # fails in the background, raised by the wait
])
async def test_a_failed_expert_fails_the_run_as_it_did_before(failing, replies):
    world = World(failing={failing})
    world.finish("B1.1")

    async def on_second_call():
        world.finish("B1.2")

    graph, _model = agent(world, [*replies, AIMessage(content="never reached")], before={2: on_second_call})

    with pytest.raises(RuntimeError, match=f"{failing} failed"):
        await run(graph)


@pytest.mark.asyncio
async def test_a_refused_assignment_does_not_hold_back_the_others():
    class Refuser(AgentMiddleware):
        async def awrap_tool_call(self, request, handler):
            if "B1.9" in str(request.tool_call["args"].get("description")):
                return ToolMessage(content="Not started: research-tree node B1.9 does not exist.",
                                   tool_call_id=request.tool_call["id"], name="task", status="error")
            return await handler(request)

    world = World()
    state_when_called_again = {}

    async def on_second_call():
        state_when_called_again["B1.2 finished"] = ("finished", "B1.2") in world.log
        world.finish("B1.2")

    graph, model = agent(world, [delegate("B1.9", "B1.2"), wait(), AIMessage(content="done")],
                         before={2: on_second_call}, middleware=[Refuser()])

    result = await run(graph)

    assert state_when_called_again == {"B1.2 finished": False}  # the refusal came back at once
    refusal = tool_text(model.seen[1], "task-B1.9")
    assert refusal.startswith("Not started: research-tree node B1.9 does not exist.")
    assert tool_text(model.seen[1], "task-B1.2").startswith(f"Started: B1.2 ({ROLE})")
    assert times_delivered(result["messages"], "B1.2") == 1


@pytest.mark.asyncio
async def test_an_assignment_that_is_still_running_is_not_started_a_second_time():
    # Before, a node could not be delegated again while its Expert worked: the Coordinator was not
    # called. Two Experts for one node would share its folder and kernel.
    world = World()
    world.finish("B1.1")

    async def let_both_return_once_the_other_role_has_started():
        while world.log.count(("started", "B1.2")) < 2:
            await asyncio.sleep(0)
        world.finish("B1.2")

    again = AIMessage(content="", tool_calls=[
        call("task", "again", description="B1.2: a question", subagent_type=ROLE),
        call("task", "other-role", description="B1.2: a question",
             subagent_type="statistical_inference_expert")])
    graph, model = agent(world, [delegate("B1.1", "B1.2"), again, AIMessage(content="done")])
    side = asyncio.create_task(let_both_return_once_the_other_role_has_started())

    result = await run(graph)
    await side

    refused = next(m for m in model.seen[2] if isinstance(m, ToolMessage) and m.tool_call_id == "again")
    assert refused.status == "error"
    assert refused.text == (f"Not started: B1.2 ({ROLE}) is already working on this; its receipt comes "
                            "with a later task or await_experts result.")
    assert world.log.count(("started", "B1.2")) == 2  # the first one, and the other role's own Expert
    assert times_delivered(result["messages"], "B1.2") == 2
    assert not world.experts.outstanding()


@pytest.mark.asyncio
async def test_each_experts_own_tool_run_ends_when_it_returns_with_its_own_receipt():
    world = World()
    world.finish("B1.1")

    async def on_second_call():
        world.finish("B1.2")

    graph, _model = agent(world, [delegate("B1.1", "B1.2"), wait(), AIMessage(content="done")],
                          before={2: on_second_call})
    order = []
    async for event in graph.astream_events({"messages": [HumanMessage(content="research")]}, version="v2"):
        if event["event"] == "on_chat_model_start":
            order.append("model")
        elif event["event"] == "on_tool_end" and event["name"] == "task":
            output = event["data"]["output"]
            order.append(output.update["messages"][0].text)

    # The desktop reads each Expert's result from its own task run, whenever that run ends.
    assert order == ["model", receipt("B1.1"), "model", receipt("B1.2"), "model"]


def assignment(node: str) -> dict:
    return {"id": f"task-{node}", "args": {"description": f"{node}: a question", "subagent_type": ROLE}}


@pytest.mark.asyncio
async def test_one_delivery_stays_below_the_size_deepagents_moves_to_a_file():
    long = {f"B1.{i}": f"Result: B1.{i} answered. " + "x" * 5_000 for i in range(1, 6)}
    experts = RunningExperts()

    async def returned(node):
        return Command(update={"messages": [ToolMessage(long[node], tool_call_id=f"task-{node}")]})

    jobs = [experts.start(assignment(node), returned(node)) for node in long]
    for job in jobs:
        assert experts.own_result(job) is None  # each call returned "still running" before its Expert did
    await asyncio.gather(*(job.work for job in jobs))

    first = experts.collect()
    assert 10_000 < len(first) <= DELIVERY_CHARS < 16_000  # DeepAgents moves a longer result to a file
    assert first.count("Receipt of ") == 2
    assert "3 more receipts are ready: call await_experts to read them." in experts.status()
    rest = experts.collect() + experts.collect()
    assert rest.count("Receipt of ") == 3 and not experts.outstanding()


@pytest.mark.asyncio
async def test_a_receipt_longer_than_one_delivery_is_still_delivered_whole():
    experts = RunningExperts()

    async def returned():
        return ToolMessage("Result: " + "y" * 20_000, tool_call_id="task-B1.1")

    job = experts.start(assignment("B1.1"), returned())
    assert experts.own_result(job) is None
    await job.work

    assert len(experts.collect()) > 20_000 and not experts.outstanding()


@pytest.mark.asyncio
async def test_a_receipt_that_does_not_fit_beside_the_calls_own_receipt_waits_for_the_next_call():
    experts = RunningExperts()
    gate = asyncio.Event()
    sizes = {"B1.1": 7_000, "B1.2": 9_000}

    async def returned(node):
        await gate.wait()
        return ToolMessage(f"Result: {node} answered. " + "z" * sizes[node], tool_call_id=f"task-{node}",
                           name="task")

    earlier = experts.start(assignment("B1.1"), returned("B1.1"))
    assert experts.own_result(earlier) is None  # its own call already returned "still running"
    request = SimpleNamespace(tool_call=assignment("B1.2") | {"name": "task"},
                              state={"messages": [delegate("B1.2")]})
    middleware = BackgroundDelegationMiddleware(experts)

    async def native(_request):
        return await returned("B1.2")

    call = asyncio.ensure_future(middleware.awrap_tool_call(request, native))
    await asyncio.sleep(0)
    gate.set()  # both Experts return in the same moment
    result = await asyncio.wait_for(call, timeout=10)

    assert result.text.startswith("Result: B1.2 answered.")
    assert "Result: B1.1 answered." not in result.text  # 7,000 more characters would pass 16,000
    assert result.text.endswith("1 more receipt is ready: call await_experts to read it.")
    assert len(result.text) < 12_000
    assert experts.collect().startswith(f"Receipt of B1.1 ({ROLE}):\nResult: B1.1 answered.")
    assert not experts.outstanding()


@pytest.mark.asyncio
async def test_calls_whose_turn_cannot_be_read_are_still_released_by_the_next_expert():
    # Without the model's message in the state each call looks like a turn of its own; none may be
    # left waiting for an Expert that is not the next to finish.
    experts = RunningExperts()
    gates = {node: asyncio.Event() for node in ("B1.1", "B1.2")}
    middleware = BackgroundDelegationMiddleware(experts)

    def native(node):
        async def run_expert(_request):
            await gates[node].wait()
            return ToolMessage(receipt(node), tool_call_id=f"task-{node}", name="task")
        return run_expert

    calls = [asyncio.ensure_future(middleware.awrap_tool_call(
        SimpleNamespace(tool_call=assignment(node) | {"name": "task"}, state={"messages": []}),
        native(node))) for node in ("B1.1", "B1.2")]
    await asyncio.sleep(0)
    gates["B1.1"].set()

    first, second = await asyncio.wait_for(asyncio.gather(*calls), timeout=10)

    assert first.text.startswith(receipt("B1.1"))
    assert second.text.startswith(f"Started: B1.2 ({ROLE}) is working in the background")
    gates["B1.2"].set()
    await experts.jobs[1].work
    assert experts.collect().startswith(f"Receipt of B1.2 ({ROLE})")


@pytest.mark.asyncio
async def test_a_failed_expert_is_raised_once_by_the_call_that_collects_it():
    experts = RunningExperts()

    async def fails():
        raise RuntimeError("provider failure")

    job = experts.start(assignment("B1.1"), fails())
    assert experts.own_result(job) is None
    await asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="provider failure"):
        experts.collect()
    assert experts.collect() == "" and not experts.outstanding()  # not raised a second time


@pytest.mark.asyncio
async def test_closing_cancels_the_experts_that_are_still_working():
    experts = RunningExperts()
    stopped = []

    async def never_returns(node):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopped.append(node)
            raise

    async def fails():
        raise RuntimeError("unseen failure")

    for node in ("B1.1", "B1.2"):
        experts.start(assignment(node), never_returns(node))
    experts.start(assignment("B1.3"), fails())
    await asyncio.sleep(0)

    await asyncio.wait_for(experts.close(), timeout=10)

    assert sorted(stopped) == ["B1.1", "B1.2"] and experts.running() == []


def test_a_synchronous_run_keeps_the_blocking_task():
    def task(description: str, subagent_type: str) -> str:
        return receipt(description.split(":")[0])

    tool = StructuredTool.from_function(name="task", func=task, description="Ask an Expert.",
                                        args_schema=TaskArgs, infer_schema=False)
    graph = create_agent(model=Coordinator(responses=[delegate("B1.1"), AIMessage(content="done")]),
                         tools=[tool], system_prompt="base",
                         middleware=[BackgroundDelegationMiddleware(RunningExperts())])

    result = graph.invoke({"messages": [HumanMessage(content="research")]})

    assert tool_text(result["messages"], "task-B1.1") == receipt("B1.1")
