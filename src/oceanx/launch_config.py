"""Launcher configuration translated into existing native model profiles."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

_ROLES = ("coordinator", "expert")
_FIELDS = {"provider", "model", "base_url", "api_key", "api_key_env", "max_tokens", "image_inputs"}


@dataclass(frozen=True, repr=False)
class ModelConfig:
    # Credentials must never appear in repr, logs or the browser's config response.
    roles: dict = field(repr=False)
    namespace: str = "web"

    def status(self):
        profiles = {
            role: {"profile": f"ocean-{self.namespace}-{role}", "label": f"{self.namespace.capitalize()} {role}",
                   "provider": profile["provider"], "model": profile["model"],
                   "configured": bool(profile["api_key"]),
                   "imageInputs": bool(profile["image_inputs"])}
            for role, profile in self.roles.items()
        }
        return {**profiles, "configured": all(p["configured"] for p in profiles.values())}

    def materialize(self, directory: Path) -> Path:
        """Use the existing model loader without modifying the existing user settings."""
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink():
            raise ValueError("Model state must not be a symlink")
        directory.chmod(0o700)
        profiles, credentials, slots = {}, {}, {}
        for role, profile in self.roles.items():
            slot = f"ocean-{self.namespace}-{role}"
            slots[role] = slot
            profiles[slot] = {"label": f"{self.namespace.capitalize()} {role}", "provider": profile["provider"],
                              "default_model": profile["model"], "base_url": profile["base_url"],
                              "image_inputs": profile["image_inputs"], "credential_slot": slot}
            credentials[f"profile:{slot}"] = {"api_key": profile["api_key"]}
        # Native profiles have one output-token limit shared by both roles.
        payload = {"active_profile": slots["coordinator"], "role_profiles": slots,
                   "profiles": profiles, "max_tokens": self.roles["coordinator"]["max_tokens"]}
        for filename, value in (("settings.json", payload), ("credentials.json", credentials)):
            fd, temporary = tempfile.mkstemp(dir=directory)
            try:
                with os.fdopen(fd, "w") as stream:
                    json.dump(value, stream)
                    stream.write("\n")
                os.replace(temporary, directory / filename)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return directory.resolve()


def parse_model_config(payload: dict, *, namespace: str = "web") -> ModelConfig:
    common = payload.get("model", {})
    overrides = payload.get("models", {})
    if not isinstance(common, dict) or not isinstance(overrides, dict) or set(overrides) - set(_ROLES):
        raise ValueError("Invalid model tables")
    roles = {}
    for role in _ROLES:
        override = overrides.get(role, {})
        if not isinstance(override, dict) or (set(common) | set(override)) - _FIELDS:
            raise ValueError(f"Unknown model setting for {role}")
        raw = {**common, **override}
        # An override may switch from an environment credential to a literal, or vice versa.
        if "api_key" in override and "api_key_env" not in override:
            raw.pop("api_key_env", None)
        if "api_key_env" in override and "api_key" not in override:
            raw.pop("api_key", None)
        provider, model = raw.get("provider"), raw.get("model")
        if not isinstance(provider, str) or provider not in {"deepseek", "openai", "anthropic"}:
            raise ValueError(f"Set a supported provider for {role}: deepseek, openai or anthropic")
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"Set a model ID for {role}")
        endpoint = raw.get("base_url")
        if endpoint is not None:
            if not isinstance(endpoint, str):
                raise ValueError(f"Invalid base_url for {role}")
            try:
                url = urlsplit(endpoint)
                valid = (url.scheme in {"http", "https"} and url.hostname and not url.username
                         and not url.password and not url.query and not url.fragment)
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(f"Invalid base_url for {role}")
        if ("api_key" in raw) == ("api_key_env" in raw):
            raise ValueError(f"Set exactly one of api_key or api_key_env for {role}")
        key = raw.get("api_key")
        if "api_key_env" in raw:
            name = raw["api_key_env"]
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError(f"Invalid api_key_env for {role}")
            key = os.environ.get(name)
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"No API key configured for {namespace} {role}")
        limit = raw.get("max_tokens", 65_536)
        if type(limit) is not int or limit < 24_576:
            raise ValueError("max_tokens must be an integer of at least 24576 (native model limit)")
        images = raw.get("image_inputs")
        if images is not None and not isinstance(images, bool):
            raise ValueError(f"image_inputs must be true or false for {role}")
        roles[role] = {"provider": provider, "model": model.strip(), "base_url": endpoint,
                       "api_key": key.strip(), "max_tokens": limit, "image_inputs": images}
    if roles["coordinator"]["max_tokens"] != roles["expert"]["max_tokens"]:
        raise ValueError("Both roles must use the same max_tokens (native model limit)")
    return ModelConfig(roles, namespace=namespace)

