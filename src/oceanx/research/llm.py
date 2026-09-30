"""The meta model used offline (lesson mining, branch judging); never inside a research task."""
from __future__ import annotations

import json
import re
from collections.abc import Callable


def parse_json_object(text: str) -> dict:
    """The first JSON object in a model reply (models sometimes add prose around it)."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("The model returned no JSON object.")
    return json.loads(match.group(0))


def default_llm(role: str = "meta") -> Callable[[str], str]:
    """The ``meta`` role profile when configured (``role_profiles.meta`` in the model settings,
    e.g. a second model family), otherwise the Expert profile."""
    from oceanx.model_config import _load_settings_payload, create_chat_model, load_model_profile

    if role == "meta" and "meta" not in (_load_settings_payload().get("role_profiles") or {}):
        role = "expert"
    model = create_chat_model(load_model_profile(role))
    return lambda prompt: model.invoke(prompt).text


__all__ = ["default_llm", "parse_json_object"]
