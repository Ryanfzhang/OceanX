from __future__ import annotations

from langchain_core.messages import HumanMessage

from oceanx.model_config import (
    OceanModelProfile,
    probe_profile_vision,
    profile_supports_vision,
)


def _profile(
    *, model: str, base_url: str | None, image_inputs: bool | None = None
) -> OceanModelProfile:
    return OceanModelProfile(
        name="test",
        label="Test",
        provider="openai",
        model=model,
        base_url=base_url,
        credential_slot="test",
        api_key="test-key",
        image_inputs=image_inputs,
    )


def test_official_deepseek_flash_supports_images() -> None:
    assert profile_supports_vision(
        _profile(model="deepseek-flash", base_url="https://api.deepseek.com")
    )


def test_deepseek_pro_does_not_inherit_flash_vision() -> None:
    assert not profile_supports_vision(
        _profile(model="deepseek-v4-pro", base_url="https://api.deepseek.com")
    )


def test_flash_name_on_an_unknown_endpoint_is_not_assumed_multimodal() -> None:
    assert not profile_supports_vision(
        _profile(model="deepseek-flash", base_url="https://models.example.test/v1")
    )


def test_saved_probe_result_overrides_model_name_fallback() -> None:
    assert not profile_supports_vision(
        _profile(
            model="deepseek-flash",
            base_url="https://api.deepseek.com",
            image_inputs=False,
        )
    )


def test_vision_probe_uses_an_image_message(monkeypatch) -> None:
    received = []

    class FakeBoundModel:
        def invoke(self, messages):
            received.extend(messages)

    class FakeModel:
        def bind(self, **kwargs):
            assert kwargs == {"max_tokens": 8}
            return FakeBoundModel()

    def fake_model(profile, *, request_timeout=None):
        assert request_timeout == 10
        return FakeModel()

    monkeypatch.setattr("oceanx.model_config.create_chat_model", fake_model)
    assert probe_profile_vision(_profile(model="fixture", base_url=None)) is True
    assert isinstance(received[0], HumanMessage)
    assert any(part.get("type") == "image_url" for part in received[0].content)
