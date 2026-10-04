"""A tool call with stray closing brackets must not end the run: Q07 of the 40-call batch died in 21 s on one."""

import asyncio
from pathlib import Path

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from oceanx.research.tool_calls import ToolCallRepairMiddleware, repaired_message
from tests.test_oceanx.test_native_subagents import _BudgetProbeModel


def invalid(args, name="update_research_tree", call_id="call_1"):
    return {"type": "invalid_tool_call", "id": call_id, "name": name, "args": args, "error": None}


@pytest.mark.parametrize("args, expected", [
    ('{"changes": [], "view": "full"}}', {"changes": [], "view": "full"}),  # the Q07 reply, a stray "}"
    ('{"changes": []}]', {"changes": []}),
    ('{"a": {"b": [1, 2]}}\n}', {"a": {"b": [1, 2]}}),
    ('  {"view": "full"}  }} ', {"view": "full"}),
])
def test_stray_closing_brackets_after_complete_arguments_are_dropped(args, expected):
    message = AIMessage(content="", invalid_tool_calls=[invalid(args)])

    fixed = repaired_message(message)

    assert fixed.tool_calls == [{"name": "update_research_tree", "args": expected, "id": "call_1",
                                 "type": "tool_call"}]
    assert fixed.invalid_tool_calls == []


@pytest.mark.parametrize("args", [
    '{"changes": [',                      # cut off: the arguments are not all there
    '{"a": 1} and then some text',        # trailing text, not just brackets
    '[1, 2]',                             # arguments must be an object
    '{"a": 1}{"b": 2}',                   # two calls glued together are not one call
    "",
])
def test_arguments_that_are_not_complete_are_left_alone(args):
    message = AIMessage(content="", invalid_tool_calls=[invalid(args)])

    assert repaired_message(message) is message


def test_repaired_calls_follow_the_valid_ones_and_unrepaired_ones_stay_invalid():
    message = AIMessage(
        content="",
        tool_calls=[{"name": "ls", "args": {"path": "/"}, "id": "ok", "type": "tool_call"}],
        invalid_tool_calls=[invalid('{"x": 1}}', "grep", "fixable"), invalid('{"x": ', "glob", "broken")])

    fixed = repaired_message(message)

    assert [c["id"] for c in fixed.tool_calls] == ["ok", "fixable"]
    assert [c["id"] for c in fixed.invalid_tool_calls] == ["broken"]
    assert message.invalid_tool_calls and len(message.tool_calls) == 1  # the original message is untouched


def test_a_message_without_invalid_calls_is_returned_as_it_is():
    message = AIMessage(content="plain reply")
    assert repaired_message(message) is message


def agent_with(responses, ran):
    @tool
    def update_research_tree(changes: list, view: str = "full") -> str:
        """Probe tool standing in for the research tree."""
        ran.append((changes, view))
        return "tree updated"

    model = _BudgetProbeModel(responses=responses)
    graph = create_agent(model=model, tools=[update_research_tree], system_prompt="base",
                         middleware=[ToolCallRepairMiddleware()])
    return graph, model


def test_a_reply_with_a_stray_bracket_runs_its_tool_and_the_run_goes_on():
    ran = []
    graph, model = agent_with([
        AIMessage(content="", invalid_tool_calls=[invalid('{"changes": [], "view": "full"}}')]),
        AIMessage(content="Delegated."),
    ], ran)

    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="research")]}))

    assert ran == [([], "full")]
    assert any(isinstance(m, ToolMessage) and m.text == "tree updated" for m in result["messages"])
    assert result["messages"][-1].text == "Delegated."
    assert len(model.seen_messages) == 2


def test_the_synchronous_path_repairs_too():
    ran = []
    graph, _model = agent_with([
        AIMessage(content="", invalid_tool_calls=[invalid('{"changes": [], "view": "full"}}')]),
        AIMessage(content="Delegated."),
    ], ran)

    result = graph.invoke({"messages": [HumanMessage(content="research")]})

    assert ran == [([], "full")] and result["messages"][-1].text == "Delegated."


def test_a_reply_that_cannot_be_repaired_is_asked_for_once_more():
    ran = []
    graph, model = agent_with([
        AIMessage(content="", invalid_tool_calls=[invalid('{"changes": [')]),   # cut off
        AIMessage(content="", tool_calls=[{"name": "update_research_tree", "args": {"changes": []},
                                           "id": "again", "type": "tool_call"}]),
        AIMessage(content="Delegated."),
    ], ran)

    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="research")]}))

    assert ran == [([], "full")] and result["messages"][-1].text == "Delegated."
    assert len(model.seen_messages) == 3  # the broken reply, its replacement, and the final answer


def test_the_synchronous_path_asks_once_more_too():
    ran = []
    graph, model = agent_with([
        AIMessage(content="", invalid_tool_calls=[invalid('{"changes": [')]),
        AIMessage(content="", tool_calls=[{"name": "update_research_tree", "args": {"changes": []},
                                           "id": "again", "type": "tool_call"}]),
        AIMessage(content="Delegated."),
    ], ran)

    result = graph.invoke({"messages": [HumanMessage(content="research")]})

    assert ran == [([], "full")] and result["messages"][-1].text == "Delegated."
    assert len(model.seen_messages) == 3


def test_a_second_broken_reply_is_not_retried_again():
    graph, model = agent_with([
        AIMessage(content="", invalid_tool_calls=[invalid('{"changes": [')]),
        AIMessage(content="", invalid_tool_calls=[invalid('{"changes": [')]),
        AIMessage(content="never asked for"),
    ], [])

    asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="research")]}))

    assert len(model.seen_messages) == 2  # one retry, then the run ends as it did before


def test_the_coordinator_and_every_expert_are_built_with_the_repair():
    source = (Path(__file__).parents[2] / "src/oceanx/research/graphs.py").read_text(encoding="utf-8")
    # The Coordinator in research mode, the Coordinator in standard mode, and every Expert.
    assert source.count("ToolCallRepairMiddleware()") == 3
