"""An Expert is told how many model calls it has, and on every later call how many remain."""

import asyncio
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from oceanx.research import graphs
from oceanx.research.graphs import (
    ExpertCallBudgetMiddleware,
    _expert_call_phases,
    _with_budget_note,
)
from oceanx.research.services import AgentRun
from tests.test_oceanx.test_native_subagents import _BudgetProbeModel
from tests.test_oceanx.test_saved_data_index import _backend


def scripted_run(analysis_calls, report_path=None):
    """A probe Expert that analyses for ``analysis_calls`` calls, then only reads files to the end."""
    wind_down_calls = graphs.EXPERT_FINAL_CALL - analysis_calls  # calls after analysis, before the final one

    @tool
    def execute(value: int) -> str:
        """Perform one probe research operation."""
        return f"result {value}"

    @tool
    def read_file(value: int) -> str:
        """Perform one probe report-file read."""
        return f"page {value}"

    def call(name, index):
        return AIMessage(content="", tool_calls=[{
            "name": name, "args": {"value": index}, "id": f"{name}-{index}", "type": "tool_call"}])

    responses = [call("execute", i) for i in range(analysis_calls)]
    responses += [call("read_file", i) for i in range(wind_down_calls)]
    responses.append(AIMessage(content="Final report delivery."))
    model = _BudgetProbeModel(responses=responses)
    graph = create_agent(model=model, tools=[execute, read_file], system_prompt="base",
                         middleware=[ExpertCallBudgetMiddleware(report_path=report_path)])
    return asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="Assigned question")]})), model


def last_text(model, call_number):
    last = model.seen_messages[call_number - 1][-1]
    return last, last.text


def test_each_call_after_the_first_ends_with_the_calls_that_remain():
    result, model = scripted_run(analysis_calls=48)

    first, first_text = last_text(model, 1)
    assert isinstance(first, HumanMessage) and "[Budget" not in first_text  # the system prompt says it
    _, second = last_text(model, 2)
    assert second.endswith("[Budget: model call 2 of 60; 47 left for analysis, then 12 only to finish the report.]")
    assert second.startswith("result 0\n\n")  # the first tool result itself comes first, unchanged
    assert last_text(model, 48)[1].endswith("model call 48 of 60; 1 left for analysis, then 12 only to finish the report.]")
    assert last_text(model, 49)[1].endswith(
        "[Budget: model call 49 of 60; analysis is over, 12 left only to finish the report; the last has no tools.]")
    assert last_text(model, 59)[1].endswith(
        "[Budget: model call 59 of 60; analysis is over, 2 left only to finish the report; the last has no tools.]")
    assert last_text(model, 60)[1].endswith("[Budget: model call 60 of 60, the last; no tools.]")
    # a notice is for one call only: it is never saved in the conversation, so the cached prefix never changes
    assert not any("[Budget" in message.text for message in result["messages"])
    for call_number in range(2, 61):  # all but the last message of a request is exactly what was saved
        sent = [m for m in model.seen_messages[call_number - 1] if not isinstance(m, SystemMessage)]
        assert [m.text for m in sent[:-1]] == [m.text for m in result["messages"][:len(sent) - 1]]


def test_the_notice_is_still_sent_while_the_report_checkpoint_pauses_analysis(tmp_path):
    # No report is ever saved here, so from call 31 the checkpoint swaps the system prompt and the tools.
    _, model = scripted_run(analysis_calls=48, report_path=tmp_path / "report.md")

    system = next(m.text for m in model.seen_messages[30] if isinstance(m, SystemMessage))
    assert "Required report checkpoint" in system
    assert last_text(model, 31)[1].endswith(
        "[Budget: model call 31 of 60; 18 left for analysis, then 12 only to finish the report.]")
    assert last_text(model, 30)[1].endswith(
        "[Budget: model call 30 of 60; 19 left for analysis, then 12 only to finish the report.]")


def test_a_lower_call_limit_is_reflected_in_the_notices(monkeypatch):
    checkpoint, wind_down, final = _expert_call_phases(40)
    for name, value in (("EXPERT_MODEL_CALL_LIMIT", 40), ("EXPERT_REPORT_CHECKPOINT_START", checkpoint),
                        ("EXPERT_WIND_DOWN_START", wind_down), ("EXPERT_FINAL_CALL", final)):
        monkeypatch.setattr(graphs, name, value)

    _, model = scripted_run(analysis_calls=32)

    assert last_text(model, 2)[1].endswith(
        "[Budget: model call 2 of 40; 31 left for analysis, then 8 only to finish the report.]")
    assert last_text(model, 33)[1].endswith(
        "[Budget: model call 33 of 40; analysis is over, 8 left only to finish the report; the last has no tools.]")
    assert last_text(model, 40)[1].endswith("[Budget: model call 40 of 40, the last; no tools.]")


def request_ending_with(message, calls_made=5):
    earlier = [HumanMessage(content="Assigned question"), AIMessage(content="", tool_calls=[
        {"name": "read_file", "args": {}, "id": "t1", "type": "tool_call"}])]
    return ModelRequest(model=SimpleNamespace(), messages=[*earlier, message], tools=[],
                        state={"messages": [], "run_model_call_count": calls_made},
                        system_message=SystemMessage(content="base"))


def test_an_image_result_keeps_its_image_when_the_notice_is_added():
    image = {"type": "image", "base64": "AAAA", "mime_type": "image/jpeg"}
    request = request_ending_with(ToolMessage(content=[image], tool_call_id="t1"))

    noted = _with_budget_note(request)

    content = noted.messages[-1].content
    assert content[0] == image
    assert content[-1]["type"] == "text" and content[-1]["text"].startswith("[Budget: model call 6 of 60")
    assert request.messages[-1].content == [image]  # the saved message itself is untouched
    assert all(a is b for a, b in zip(noted.messages[:-1], request.messages[:-1]))  # the prefix is the same objects


def test_a_request_that_does_not_end_with_a_tool_result_is_left_alone():
    request = request_ending_with(HumanMessage(content="A follow-up question"))
    assert _with_budget_note(request) is request


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ocean_process_expert", "statistical_inference_expert",
                                  "literature_reproduction_expert", "scientific_discussion_partner"])
async def test_every_expert_is_told_its_call_budget_in_its_instructions(tmp_path, monkeypatch, role):
    async with _backend(tmp_path, monkeypatch) as (_host, _task, config, seen):
        run = AgentRun.from_config(config, role, question="B1: how many calls")
        await graphs.build(config, role, run=run)

    prompt = seen["system_prompt"]
    assert (f"Call budget: you have {graphs.EXPERT_MODEL_CALL_LIMIT} model calls for this assignment, "
            "and one call can run several tools.") in prompt
    assert (f"Analysis tools work through call {graphs.EXPERT_WIND_DOWN_START}; calls "
            f"{graphs.EXPERT_WIND_DOWN_START + 1} to {graphs.EXPERT_FINAL_CALL} may only finish the report, "
            f"and call {graphs.EXPERT_MODEL_CALL_LIMIT} has no tools.") in prompt
    assert "The end of each tool result shows which call you are on and how many remain." in prompt
