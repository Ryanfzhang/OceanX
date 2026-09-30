"""Provider payload regression for native synchronous task receipts."""

import pytest
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
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
    # No empty/guessed reasoning is inserted for synthetic or older messages.
    legacy = model._get_request_payload(
        [HumanMessage(content="q"), AIMessage(content="old answer")]
    )
    assert "reasoning_content" not in legacy["messages"][-1]
