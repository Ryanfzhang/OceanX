"""One Finch episode. Imported/executed only in the separate Finch interpreter.

Keep the upstream ReAct agent and notebook tools. Adapt only model routing,
native sandbox execution, usage recording and delivery; never import OceanX skills.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import sys
import time
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from uuid import uuid4

from finch_sandbox import execute_notebook, kernel_check


def json_value(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def append_json(path, value):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, default=json_value) + "\n")
        stream.flush()


def save_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def normalized_usage(raw):
    """LiteLLM's OpenAI-normalized usage; cache is a subset of prompt tokens."""
    raw = json_value(raw) or {}
    def number(value):
        return value if type(value) is int and value >= 0 else None
    details = raw.get("prompt_tokens_details") or {}
    return {"input_tokens": number(raw.get("prompt_tokens")),
            "output_tokens": number(raw.get("completion_tokens")),
            "cached_input_tokens": number(details.get("cached_tokens"))}


def dependency_check():
    if sys.version_info < (3, 12):
        raise ValueError("Finch requires a separate Python 3.12+ interpreter (--python)")
    import litellm
    from fhda.data_analysis_env import DataAnalysisEnv
    from fhda.notebook_env import NBEnvironmentState
    from ldp.agent import AgentConfig
    del DataAnalysisEnv, NBEnvironmentState, AgentConfig, litellm
    versions = {dist.metadata["Name"].lower(): dist.version
                for dist in importlib.metadata.distributions() if dist.metadata.get("Name")}
    # These are the agent interfaces used by the pinned Finch checkout/tutorial.
    if versions["ldp"] != "0.26.0" or versions["fhaviary"] != "0.19.0":
        raise ValueError("Install the pinned Finch dependencies: ldp==0.26.0, fhaviary==0.19.0")
    return {"python": sys.version.split()[0], "libraries": dict(sorted(versions.items()))}


def workspace_file(path, workspace):
    """Finch's host-side notebook IO must not follow model-created symlinks."""
    path, workspace = Path(path), Path(workspace)
    if not path.resolve().is_relative_to(workspace.resolve()) or any(
            p.is_symlink() for p in (path, *path.parents) if p != workspace.parent):
        raise ValueError("Notebook path must remain inside the attempt workspace without symlinks")
    return path


def install_meter(attempt, secret):
    """Meter raw router responses once, including malformed-action retries.

    Do not sum LLMResult per-choice counts, which repeat the same request usage.
    No API kwargs/configuration is written to the transcript.
    """
    import litellm
    original = litellm.Router.acompletion
    def redact(text):
        return text.replace(secret, "<REDACTED>") if secret else text

    @wraps(original)
    async def measured(router, *args, **kwargs):
        call_id = uuid4().hex
        started = time.monotonic()
        append_json(attempt / "transcript.jsonl", {
            "type": "model.request", "call_id": call_id,
            "messages": kwargs.get("messages", args[1] if len(args) > 1 else [])})
        record = {"call_id": call_id, "role": "finch", "state": "failed",
                  "started_at": datetime.now(UTC).isoformat()}
        try:
            response = await original(router, *args, **kwargs)
            usage = getattr(response, "usage", None)
            record.update(state="completed", model=getattr(response, "model", None),
                          usage=normalized_usage(usage))
            append_json(attempt / "transcript.jsonl", {"type": "model.response",
                "call_id": call_id, "choices": [json_value(c) for c in response.choices]})
            return response
        except BaseException as exc:
            record["error"] = redact(str(exc))[:2000]
            raise
        finally:
            record["duration_seconds"] = time.monotonic() - started
            append_json(attempt / "model_calls.jsonl", record)
    litellm.Router.acompletion = measured
    return lambda: setattr(litellm.Router, "acompletion", original)


def model_compatibility(config):
    """Keep Finch's explicit ReAct reasoning and mandatory action selection.

    DeepSeek thinking rejects required/named tool choices. Disable that provider
    feature for the entire Finch conversation, not just the failing call: the
    pinned message interfaces also do not replay DeepSeek reasoning_content.
    This is an explicit baseline mode, never an error-triggered fallback.
    """
    extra = ({"thinking": {"type": "disabled"}}
             if config.oceanx_api == "openai" and config.model.startswith("deepseek-") else {})
    return {"agent_reasoning": "upstream_two_call_react", "tool_choice": "upstream_required",
            "provider_thinking": "disabled" if extra else "provider_default",
            "request_extra_body": extra}


def install_model(config):
    """Explicit endpoint/provider; no inherited defaults or credential lookup."""
    import ldp.graph.common_ops as common
    from lmi import LiteLLMModel
    endpoint = config.endpoint(config.oceanx_api)
    compatibility = model_compatibility(config)
    original = common.LLMModel
    def configured_model(config):
        # Finch's pinned LiteLLM predates Flash: qualify the alias as well as the
        # routed model so provider discovery never relies on its stale model list.
        settings = {"name": provider_model, "model_list": [{
            "model_name": provider_model, "litellm_params": {
                "model": provider_model, "api_base": endpoint.url,
                "api_key": endpoint.api_key, "max_tokens": max_tokens,
                **({"extra_body": compatibility["request_extra_body"]}
                   if compatibility["request_extra_body"] else {})}}],
            "router_kwargs": {"num_retries": 2}}
        return LiteLLMModel(name=provider_model, config=settings)
    provider_model = f"{config.oceanx_api}/{config.model}"
    max_tokens = config.max_tokens
    common.LLMModel = configured_model
    return lambda: setattr(common, "LLMModel", original)


async def episode(attempt, config):
    import fhda.config as cfg
    from fhda import prompts
    from fhda.data_analysis_env import DataAnalysisEnv
    from fhda.notebook_env import NBEnvironment, NBEnvironmentState
    from fhda.utils import NBLanguage
    from ldp.agent import AgentConfig

    spec = json.loads((attempt / "worker.json").read_text())
    workspace = Path(spec["workspace"])
    cfg.USE_DOCKER = False
    NBEnvironment.EXEC_TIMEOUT = spec["execution_timeout"]
    original_start, original_close = NBEnvironmentState.start_kernel, NBEnvironmentState.close
    original_run = NBEnvironment.run_notebook
    original_local = NBEnvironment._run_notebook_local
    original_save, original_reload = NBEnvironmentState.save_nb, NBEnvironmentState.reload_nb
    original_list = NBEnvironment._list_dir

    def save_notebook(state):
        workspace_file(state.nb_path, workspace)
        return original_save(state)

    def reload_notebook(state):
        workspace_file(state.nb_path, workspace)
        return original_reload(state)

    def list_directory(environment, path):
        workspace_file(path, workspace)
        # Upstream recursively lists on the host; links created inside the sandbox must
        # not expose host directories or cause a recursion cycle.
        index = {}
        for p in sorted(Path(path).iterdir()):
            if p.is_symlink():
                continue
            if p.is_dir():
                index.setdefault("directories", {})
                index[p.name] = list_directory(environment, p)
            else:
                index.setdefault("files", []).append(p.name)
        return index

    NBEnvironmentState.save_nb, NBEnvironmentState.reload_nb = save_notebook, reload_notebook
    NBEnvironment._list_dir = list_directory

    async def no_host_kernel(state):
        # Kernels exist only inside a namespace for each complete notebook replay.
        # Never start upstream's unsandboxed local kernel.
        pass

    async def run_local(environment):
        workspace_file(environment.state.nb_path, workspace)
        log = attempt / f"notebook-execution-{uuid4().hex}.log"
        code, tail = await execute_notebook(spec, log)
        if code:
            raise ValueError(f"Sandboxed notebook failed (exit code {code}): {tail}")
        environment.state.reload_nb()
        return "Executed all cells."

    NBEnvironmentState.start_kernel, NBEnvironmentState.close = no_host_kernel, no_host_kernel
    NBEnvironment._run_notebook_local = run_local
    async def measured_execution(environment):
        execution_id, started = uuid4().hex, time.monotonic()
        append_json(attempt / "code_runs.jsonl", {"execution_id": execution_id,
            "state": "running", "started_at": datetime.now(UTC).isoformat()})
        record = {"execution_id": execution_id, "state": "failed"}
        try:
            result = await original_run(environment)
            errors = [output.get("ename", "NotebookError")
                      for cell in environment.state.nb.cells
                      for output in cell.get("outputs", []) if output.get("output_type") == "error"]
            record.update(state="failed" if errors else "succeeded", errors=errors)
            return result
        except TimeoutError:
            record["state"] = "timed_out"
            raise
        finally:
            record["duration_seconds"] = time.monotonic() - started
            append_json(attempt / "code_runs.jsonl", record)
    NBEnvironment.run_notebook = measured_execution
    restore_meter = install_meter(attempt, config.endpoint(config.oceanx_api).api_key)
    restore_model = install_model(config)
    environment = DataAnalysisEnv(problem_id="benchmark-case",
        problem=((attempt / "submitted_prompt.txt").read_text()
                 + "\n" + prompts.CHAIN_OF_THOUGHT_AGNOSTIC
                 + "\n" + prompts.GENERAL_NOTEBOOK_GUIDELINES), eval_mode=None,
        nb_path=workspace / NBEnvironment.NOTEBOOK_NAME, work_dir=workspace,
        language=NBLanguage.PYTHON, system_prompt=prompts.CAPSULE_SYSTEM_PROMPT_QUERY,
        use_tmp_work_dir=False, allow_download_from_gcs=False)
    steps, status, reason = 0, "failed", "step_limit"
    try:
        observations, tools = await environment.reset()
        environment.state.save_nb()
        agent = AgentConfig(agent_type="ReActAgent", agent_kwargs={
            "llm_model": {"name": config.model, "temperature": spec["temperature"],
                "max_tokens": config.max_tokens, "parallel_tool_calls": False,
                "num_retries": 3}, "hide_old_env_states": True}).construct_agent()
        state = await agent.init_state(tools)
        for steps in range(1, spec["max_steps"] + 1):
            append_json(attempt / "transcript.jsonl", {"type": "observations", "step": steps,
                                                      "messages": observations})
            action, state, _ = await agent.get_asv(state, observations)
            append_json(attempt / "transcript.jsonl", {"type": "action", "step": steps,
                                                      "message": action.value})
            observations, _, done, truncated = await environment.step(action.value)
            save_json(attempt / "progress.json", {"steps": steps, "done": done})
            if done:
                answer = environment.state.answer
                text = answer if isinstance(answer, str) else (
                    json.dumps(answer, ensure_ascii=False, indent=2) if answer is not None else "")
                if text.strip():
                    (attempt / "answer.md").write_text(text, encoding="utf-8")
                    status, reason = "completed", None
                else:
                    reason = "empty_answer"
                break
            if truncated:
                reason = "environment_truncated"
                break
    finally:
        # submit_answer may already close the upstream env. Avoid a second removal.
        if hasattr(environment, "state") and not environment.state.done:
            await environment.close()
        restore_meter()
        restore_model()
        NBEnvironmentState.start_kernel, NBEnvironmentState.close = original_start, original_close
        NBEnvironment.run_notebook = original_run
        NBEnvironment._run_notebook_local = original_local
        NBEnvironmentState.save_nb, NBEnvironmentState.reload_nb = original_save, original_reload
        NBEnvironment._list_dir = original_list
    return {"status": status, "stop_reason": reason, "steps": steps}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--kernel-check", action="store_true")
    parser.add_argument("--attempt", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    if args.kernel_check:
        print(json.dumps(kernel_check()))
        return 0
    if args.check:
        print(json.dumps(dependency_check()))
        return 0
    if args.attempt is None or args.config is None:
        parser.error("--attempt and --config are required")
    dependency_check()
    # Importing the configuration module does not import OceanX or its skills.
    from benchmark_config import load_config
    config = load_config(args.config)
    try:
        result = asyncio.run(episode(args.attempt, config))
    except Exception as exc:  # noqa: BLE001 — persist terminal failure for the supervisor
        key = config.endpoint(config.oceanx_api).api_key
        message = str(exc).replace(key, "<REDACTED>")
        result = {"status": "failed", "stop_reason": "worker_error",
                  "error": f"{type(exc).__name__}: {message[:2000]}"}
        print(result["error"], file=sys.stderr)
    save_json(args.attempt / "worker_result.json", result)
    return int(result["status"] != "completed")


if __name__ == "__main__":
    sys.exit(main())
