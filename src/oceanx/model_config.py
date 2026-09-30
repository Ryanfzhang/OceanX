"""OceanX-native model profiles and credential storage."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

ProviderKind = Literal["anthropic", "openai", "deepseek"]
ModelRole = Literal["coordinator", "expert"]


@dataclass(frozen=True)
class OceanModelProfile:
    name: str
    label: str
    provider: ProviderKind
    model: str
    base_url: str | None
    credential_slot: str
    api_key: str
    max_tokens: int = 65_536
    image_inputs: bool | None = None


@dataclass(frozen=True)
class OceanModelSetup:
    provider: ProviderKind
    model: str
    base_url: str | None
    api_key: str | None


def ocean_config_dir() -> Path:
    override = os.environ.get("OCEANMIND_CONFIG_DIR", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".oceanmind"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _load_settings_payload() -> dict[str, Any]:
    return _read_json(ocean_config_dir() / "settings.json")


def _profile_payload(
    settings: dict[str, Any], *, role: ModelRole = "coordinator"
) -> tuple[str, dict[str, Any]]:
    role_profiles = settings.get("role_profiles")
    profiles = settings.get("profiles")
    if isinstance(role_profiles, dict):
        role_profile = role_profiles.get(role)
        if (
            isinstance(role_profile, str)
            and isinstance(profiles, dict)
            and isinstance(profiles.get(role_profile), dict)
        ):
            return role_profile, dict(profiles[role_profile])
    active = str(settings.get("active_profile") or "ocean-desktop-api")
    if isinstance(profiles, dict) and isinstance(profiles.get(active), dict):
        raw = dict(profiles[active])
        return active, raw
    provider = str(settings.get("provider") or settings.get("api_format") or "anthropic")
    return active, {
        "label": "OceanX model",
        "provider": provider,
        "api_format": settings.get("api_format", provider),
        "default_model": settings.get("model", "claude-sonnet-4-6"),
        "last_model": settings.get("model"),
        "base_url": settings.get("base_url"),
        "credential_slot": active,
    }


def _normalized_provider(raw: dict[str, Any]) -> ProviderKind:
    provider = str(raw.get("provider") or raw.get("api_format") or "anthropic").lower()
    if provider == "deepseek":
        return "deepseek"
    if provider in {"openai", "openai_codex", "moonshot", "dashscope"}:
        return "openai"
    return "anthropic"


def _credential_candidates(*, provider: ProviderKind, slot: str) -> list[tuple[Path, str]]:
    path = ocean_config_dir() / "credentials.json"
    provider_key = "openai" if provider in {"openai", "deepseek"} else "anthropic"
    keys = [f"profile:{slot}", slot, provider_key]
    return [(path, key) for key in keys]


def _stored_api_key(*, provider: ProviderKind, slot: str) -> str:
    path = ocean_config_dir() / "credentials.json"
    stored = _read_json(path)
    # A role-specific desktop credential is the user's explicit choice and
    # must not be shadowed by a process-wide provider environment variable.
    # The generic provider entry remains a legacy fallback below.
    for key in (f"profile:{slot}", slot):
        entry = stored.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("api_key"), str):
            value = entry["api_key"].strip()
            if value:
                return value
    env_name = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }[provider]
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    provider_key = "openai" if provider in {"openai", "deepseek"} else "anthropic"
    for key in (provider_key,):
        entry = stored.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("api_key"), str):
            value = entry["api_key"].strip()
            if value:
                return value
    # Keyring remains optional because not every desktop environment provides
    # a usable backend.
    try:
        import keyring

        for _, key in _credential_candidates(provider=provider, slot=slot):
            value = keyring.get_password("oceanmind", f"{key}:api_key")
            if value:
                return value
    except Exception:  # noqa: BLE001, S110 - keyring backends fail heterogeneously
        pass
    return ""


def load_model_profile(
    role: ModelRole = "coordinator", *, require_api_key: bool = True
) -> OceanModelProfile:
    settings = _load_settings_payload()
    name, raw = _profile_payload(settings, role=role)
    provider = _normalized_provider(raw)
    model = str(raw.get("last_model") or raw.get("default_model") or settings.get("model") or "")
    if not model:
        model = "claude-sonnet-4-6" if provider == "anthropic" else "gpt-5.4"
    slot = str(raw.get("credential_slot") or name)
    api_key = _stored_api_key(provider=provider, slot=slot)
    if require_api_key and not api_key:
        raise ValueError(f"No API key is configured for the active {provider} profile")
    base_url = raw.get("base_url")
    return OceanModelProfile(
        name=name,
        label=str(raw.get("label") or "OceanX model"),
        provider=provider,
        model=model,
        base_url=str(base_url).strip() if isinstance(base_url, str) and base_url.strip() else None,
        credential_slot=slot,
        api_key=api_key,
        max_tokens=max(24_576, int(settings.get("max_tokens") or 65_536)),
        image_inputs=raw.get("image_inputs") if isinstance(raw.get("image_inputs"), bool) else None,
    )


def save_desktop_model_profiles(
    *, setups: dict[ModelRole, OceanModelSetup], probe_vision: bool = False
) -> OceanModelProfile:
    if set(setups) != {"coordinator", "expert"}:
        raise ValueError("Every OceanX model role must be configured")
    root = ocean_config_dir()
    root.mkdir(parents=True, exist_ok=True)
    slots: dict[ModelRole, str] = {
        "coordinator": "ocean-desktop-coordinator",
        "expert": "ocean-desktop-expert",
    }
    existing_keys = {
        role: load_model_profile(role, require_api_key=False).api_key for role in slots
    }
    profiles: dict[str, dict[str, Any]] = {}
    for role, setup in setups.items():
        if setup.provider not in {"openai", "anthropic", "deepseek"}:
            raise ValueError("Unsupported model provider")
        slot = slots[role]
        profiles[slot] = {
            "label": {
                "coordinator": "Coordinator API",
                "expert": "Expert API",
            }[role],
            "provider": setup.provider,
            "api_format": "anthropic" if setup.provider == "anthropic" else "openai",
            "default_model": setup.model,
            "last_model": setup.model,
            "base_url": setup.base_url,
            "credential_slot": slot,
        }
    payload = {
        "active_profile": slots["coordinator"],
        "role_profiles": slots,
        "max_tokens": 65_536,
        "profiles": profiles,
    }
    settings_path = root / "settings.json"
    settings_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    credentials_path = root / "credentials.json"
    credentials = _read_json(credentials_path)
    changed_credentials = False
    for role, setup in setups.items():
        next_key = setup.api_key if setup.api_key is not None else existing_keys[role]
        if next_key:
            credentials[f"profile:{slots[role]}"] = {"api_key": next_key}
            changed_credentials = True
    if changed_credentials:
        credentials_path.write_text(json.dumps(credentials, indent=2) + "\n", encoding="utf-8")
        credentials_path.chmod(0o600)
    if probe_vision:
        probed: dict[tuple[str, str, str | None, str], bool | None] = {}
        changed_capabilities = False
        for role, slot in slots.items():
            profile = load_model_profile(role)
            probe_key = (profile.provider, profile.model, profile.base_url, profile.api_key)
            if probe_key not in probed:
                probed[probe_key] = probe_profile_vision(profile)
            result = probed[probe_key]
            if result is not None:
                profiles[slot]["image_inputs"] = result
                changed_capabilities = True
        if changed_capabilities:
            settings_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return load_model_profile("coordinator")


def save_desktop_model_profile(
    *,
    provider: ProviderKind,
    model: str,
    base_url: str | None,
    api_key: str | None,
) -> OceanModelProfile:
    """Backward-compatible migration helper for the former single API form."""

    return save_desktop_model_profiles(
        setups={
            "coordinator": OceanModelSetup(provider, model, base_url, api_key),
            "expert": OceanModelSetup(provider, model, base_url, api_key),
        }
    )


class OceanChatDeepSeek(ChatDeepSeek):
    """Keep genuine provider reasoning across tools, checkpoints and follow-ups.

    ChatDeepSeek extracts streamed reasoning_content; the installed integration
    does not yet serialize it on subsequent requests. Never synthesize it.
    """

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)
        for message, serialized in zip(messages, payload["messages"], strict=True):
            if isinstance(message, AIMessage) and "reasoning_content" in message.additional_kwargs:
                serialized["reasoning_content"] = message.additional_kwargs["reasoning_content"]
        return payload


def create_chat_model(
    profile: OceanModelProfile, *, request_timeout: float | None = None
) -> BaseChatModel:
    common: dict[str, Any] = {
        "model": profile.model,
        "api_key": profile.api_key,
        "max_tokens": profile.max_tokens,
        "streaming": True,
        "max_retries": 0,  # Deep Agent model/summary middleware owns the single retry layer.
    }
    if profile.provider == "anthropic":
        if request_timeout is not None:
            common["timeout"] = request_timeout
        if profile.base_url:
            common["base_url"] = profile.base_url
        return ChatAnthropic(**common)
    if request_timeout is not None:
        common["request_timeout"] = request_timeout
    if profile.base_url:
        common["base_url"] = profile.base_url
    # Older saved profiles name the wire format "openai" even for DeepSeek's
    # own endpoint. Keep their model, credentials and URL; select its adapter.
    if profile.provider == "deepseek" or urlparse(profile.base_url or "").hostname == "api.deepseek.com":
        return OceanChatDeepSeek(**common)
    return ChatOpenAI(**common)


_VISION_PROBE_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _exception_status_code(error: BaseException) -> int | None:
    """Extract an HTTP status without depending on one provider SDK."""

    current: object | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status_code", None)
        if isinstance(status, int):
            return status
        response = getattr(current, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    return None


def probe_profile_vision(profile: OceanModelProfile) -> bool | None:
    """Test image input through the configured adapter.

    ``None`` means the probe was inconclusive (for example a timeout, invalid
    credential, or rate limit). Only a provider response that rejects the
    request shape is evidence that image input is unsupported.
    """

    message = HumanMessage(
        content=[
            {"type": "text", "text": "Reply OK."},
            {"type": "image_url", "image_url": {"url": _VISION_PROBE_IMAGE}},
        ]
    )
    try:
        create_chat_model(profile, request_timeout=10).bind(max_tokens=8).invoke([message])
    except Exception as error:  # noqa: BLE001 - provider SDKs expose different errors
        status = _exception_status_code(error)
        if status in {400, 404, 405, 415, 422}:
            return False
        return None
    return True


def profile_supports_vision(profile: OceanModelProfile) -> bool:
    """Return whether this exact provider/model pairing accepts image input.

    LangChain's model profiles do not cover every OpenAI-compatible model. In
    particular, DeepSeek's current public Flash model is multimodal but has no
    adapter profile, so an adapter-only lookup incorrectly reports ``False``.
    Keep the explicit official-endpoint mapping here rather than guessing from
    a generic model name used by an arbitrary compatible endpoint.
    """

    if not all(hasattr(profile, field) for field in ("model", "api_key", "max_tokens")):
        return False
    if profile.image_inputs is not None:
        return profile.image_inputs
    capabilities = getattr(create_chat_model(profile), "profile", None)
    if isinstance(capabilities, dict) and capabilities.get("image_inputs"):
        return True
    hostname = (urlparse(profile.base_url or "").hostname or "").lower()
    model = profile.model.strip().lower()
    return hostname == "api.deepseek.com" and model in {
        "deepseek-flash",
        "deepseek-v4-flash",
        "deepseek-v4-flash-vision-exp",
    }


__all__ = [
    "ModelRole",
    "OceanModelProfile",
    "OceanModelSetup",
    "ProviderKind",
    "create_chat_model",
    "load_model_profile",
    "ocean_config_dir",
    "probe_profile_vision",
    "profile_supports_vision",
    "save_desktop_model_profile",
    "save_desktop_model_profiles",
]
