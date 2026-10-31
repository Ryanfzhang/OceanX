"""Provider payload regression for native synchronous task receipts."""

import pytest
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
    message_chunk_to_message,
)
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from oceanx.model_config import OceanChatDeepSeek, OceanModelProfile, create_chat_model


def profile(provider="openai", url="https://api.deepseek.com", model="deepseek-v4-pro"):
    return OceanModelProfile(
        name="test",
        label="test",
        provider=provider,
        model=model,
        base_url=url,
        credential_slot="test",
        api_key="test",
        max_tokens=65536,
    )


@pytest.mark.parametrize(
    "provider,url",
    [
        ("openai", "https://api.deepseek.com"),
        ("openai", "https://api.deepseek.com/v1"),
        ("deepseek", None),
        ("deepseek", "https://provider.example/v1"),
    ],
)
def test_deepseek_adapter_keeps_config(provider, url):
    model = create_chat_model(profile(provider, url))
    assert isinstance(model, OceanChatDeepSeek)
    assert model.model_name == "deepseek-v4-pro" and model.max_tokens == 65536
    if url:
        assert model.api_base == url


def test_other_openai_endpoints_are_not_reclassified_by_model_name():
    model = create_chat_model(profile(url="https://api.deepseek.com.example/v1"))
    assert type(model) is ChatOpenAI


def test_stream_checkpoint_resume_preserves_reasoning_for_tools_and_final_text():
    model = create_chat_model(profile())

    def chunk(delta):
        return model._convert_chunk_to_generation_chunk(
            {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]}, AIMessageChunk, None
        ).message

    streamed = chunk({"role": "assistant", "reasoning_content": "saved reasoning part 1 "})
    streamed += chunk({"reasoning_content": "and part 2", "content": "Waiting for the Expert."})
    answer = message_chunk_to_message(streamed)
    dispatch = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "dispatch reasoning"},
        tool_calls=[
            {"id": "task1", "name": "task", "args": {
                "subagent_type": "ocean_process_expert", "description": "B1: question"}}
        ],
    )
    messages = [
        HumanMessage(content="question"),
        dispatch,
        ToolMessage(content='{"summary":"answer","report_path":"/task/report.md","outputs":[]}',
                    tool_call_id="task1"),
        answer,
    ]
    serde = JsonPlusSerializer()
    restored = serde.loads_typed(serde.dumps_typed(messages))
    payload = model._get_request_payload(restored)
    assert payload["messages"][-1]["role"] == "assistant"
    assistants = [m for m in payload["messages"] if m["role"] == "assistant"]
    assert [m["reasoning_content"] for m in assistants] == [
        "dispatch reasoning",
        "saved reasoning part 1 and part 2",
    ]
    assert assistants[1]["content"] == "Waiting for the Expert."
    assert "tool_calls" not in assistants[1]


TOOL = {"type": "function", "function": {"name": "read_file", "description": "Read a file.",
                                         "parameters": {"type": "object", "properties": {}}}}


def test_with_tools_every_assistant_message_carries_reasoning_and_none_is_invented():
    """DeepSeek rejects a request with tools when any assistant message lacks reasoning_content.
    A message no DeepSeek reasoning produced, such as the call-limit notice the agent framework
    adds before a handoff, gets an empty one; without tools such a message is sent as it is."""
    model = create_chat_model(profile())
    notice = AIMessage(content="Model call limits exceeded: run limit (100/100)")
    thought = AIMessage(content="answer", additional_kwargs={"reasoning_content": "real reasoning"})
    conversation = [HumanMessage(content="q"), notice, thought, HumanMessage(content="next")]
    with_tools = [m for m in model._get_request_payload(conversation, tools=[TOOL])["messages"]
                  if m["role"] == "assistant"]
    assert [m["reasoning_content"] for m in with_tools] == ["", "real reasoning"]
    without = [m for m in model._get_request_payload(conversation)["messages"] if m["role"] == "assistant"]
    assert "reasoning_content" not in without[0] and without[1]["reasoning_content"] == "real reasoning"


def test_a_figure_read_by_a_tool_reaches_deepseek_as_an_image():
    from deepagents.middleware.filesystem import _scrub_unsupported_multimodal_content

    call = AIMessage(content="", additional_kwargs={"reasoning_content": "open the figure"},
                     tool_calls=[{"id": "r1", "name": "read_file", "args": {"file_path": "/f.jpg"}}])
    figure = ToolMessage(content_blocks=[{"type": "image", "base64": "aGVsbG8=", "mime_type": "image/jpeg"}],
                         tool_call_id="r1", name="read_file")
    text = ToolMessage(content=[{"type": "text", "text": "plain"}], tool_call_id="r2", name="execute")
    answer = AIMessage(content="It is a red circle.", additional_kwargs={"reasoning_content": "looked"})
    for name in ("deepseek-flash", "deepseek-v4-flash"):
        model = create_chat_model(profile(model=name))
        # LangChain's profile calls deepseek-v4-flash text-only; the agent would then replace the image.
        assert _scrub_unsupported_multimodal_content([figure], model) == [figure]
        # Chat Completions takes images in user messages: the image follows the tool result.
        sent = model._get_request_payload([HumanMessage(content="q"), call, figure, answer], tools=[TOOL])
        roles = [m["role"] for m in sent["messages"]]
        assert roles == ["user", "assistant", "tool", "user", "assistant"]
        tool, image = sent["messages"][2], sent["messages"][3]
        assert tool["tool_call_id"] == "r1" and "follows in the next message" in tool["content"]
        assert {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,aGVsbG8="}} in image["content"]
    pro = create_chat_model(profile(model="deepseek-v4-pro"))
    assert _scrub_unsupported_multimodal_content([figure], pro) != [figure]  # Pro reads no images
    # A text-only result is sent as before.
    plain = create_chat_model(profile(model="deepseek-flash"))._get_request_payload(
        [HumanMessage(content="q"), call.model_copy(update={"tool_calls": [
            {"id": "r2", "name": "execute", "args": {}}]}), text])
    assert isinstance(plain["messages"][-1]["content"], str)


def test_images_follow_all_parallel_tool_results():
    model = create_chat_model(profile(model="deepseek-flash"))
    calls = AIMessage(content="", tool_calls=[
        {"id": "original", "name": "read_file", "args": {"file_path": "/original.png"}},
        {"id": "generated", "name": "read_file", "args": {"file_path": "/generated.png"}},
        {"id": "metadata", "name": "read_file", "args": {"file_path": "/metadata.json"}},
    ])
    image = {"type": "image", "base64": "aGVsbG8=", "mime_type": "image/png"}
    results = [ToolMessage(content_blocks=[image], tool_call_id="original"),
               ToolMessage(content_blocks=[image], tool_call_id="generated"),
               ToolMessage(content="labels", tool_call_id="metadata")]
    sent = model._get_request_payload([HumanMessage(content="Compare"), calls, *results], tools=[TOOL])
    assert [m["role"] for m in sent["messages"]] == ["user", "assistant", "tool", "tool", "tool", "user"]
    assert [m["tool_call_id"] for m in sent["messages"][2:5]] == ["original", "generated", "metadata"]
    assert len([b for b in sent["messages"][-1]["content"] if b.get("type") == "image_url"]) == 2
