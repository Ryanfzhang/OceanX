"""One Finch episode. Imported/executed only in the separate Finch interpreter.

Keep the upstream ReAct agent and notebook tools. Adapt only model routing,
container mounts/limits, usage recording and delivery; never import OceanX skills.
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


def container_config(spec):
    """The only writable host mount is this attempt's work directory."""
    binds = [f"{spec['workspace']}:/workspace:rw"]
    binds += [f"{m['source']}:{m['target']}:ro" for m in spec["mounts"]]
    return {"Image": spec["image"], "Cmd": ["sleep", "infinity"],
            "WorkingDir": "/workspace", "User": f"{spec['uid']}:{spec['gid']}",
            "Env": ["HOME=/tmp", "USER=finch", "LOGNAME=finch",
                    "MPLCONFIGDIR=/tmp/matplotlib", "IPYTHONDIR=/tmp/ipython"],
            "HostConfig": {"Binds": binds, "NetworkMode": "none", "ReadonlyRootfs": True,
                "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"],
                "PidsLimit": 256, "Memory": spec["memory_bytes"],
                "NanoCpus": int(spec["cpus"] * 1_000_000_000),
                "Tmpfs": {"/tmp": "rw,nosuid,nodev,size=1g"}}, "Tty": True}


def workspace_file(path, workspace):
    """Finch's host-side notebook IO must not follow model-created symlinks."""
    path, workspace = Path(path), Path(workspace)
    if not path.resolve().is_relative_to(workspace.resolve()) or any(
            p.is_symlink() for p in (path, *path.parents) if p != workspace.parent):
        raise ValueError("Notebook path must remain inside the attempt workspace without symlinks")
    return path


def notebook_command(command, timeout):
    # nbconvert otherwise has a separate default 30-second cell limit, unrelated
    # to Finch's outer notebook deadline. Use this arm's explicit execution budget.
    if command[:2] == ["jupyter", "nbconvert"] and "--execute" in command:
        return [*command, f"--ExecutePreprocessor.timeout={max(1, int(timeout))}"]
    return command


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


def install_model(config):
    """Explicit endpoint/provider; no inherited defaults or credential lookup."""
    import ldp.graph.common_ops as common
    from lmi import LiteLLMModel
    endpoint = config.endpoint(config.oceanx_api)
    original = common.LLMModel
    def configured_model(config):
        settings = {"name": config["name"], "model_list": [{
            "model_name": config["name"], "litellm_params": {
                "model": provider_model, "api_base": endpoint.url,
                "api_key": endpoint.api_key, "max_tokens": max_tokens}}],
            "router_kwargs": {"num_retries": 2}}
        return LiteLLMModel(name=config["name"], config=settings)
    provider_model = f"{config.oceanx_api}/{config.model}"
    max_tokens = config.max_tokens
    common.LLMModel = configured_model
    return lambda: setattr(common, "LLMModel", original)


async def episode(attempt, config):
    import aiodocker
    import fhda.config as cfg
    from fhda import prompts
    from fhda.data_analysis_env import DataAnalysisEnv
    from fhda.notebook_env import NBEnvironment, NBEnvironmentState
    from fhda.utils import NBLanguage
    from ldp.agent import AgentConfig

    spec = json.loads((attempt / "worker.json").read_text())
    workspace = Path(spec["workspace"])
    cfg.USE_DOCKER = True
    NBEnvironment.EXEC_TIMEOUT = spec["execution_timeout"]
    original_start = NBEnvironmentState.start_container
    original_run = NBEnvironment.run_notebook
    original_exec = NBEnvironment._exec_cmd
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
        # Upstream recursively lists on the host; links created inside Docker must
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

    async def execute_command(environment, command):
        return await original_exec(environment, notebook_command(command, spec["execution_timeout"]))

    NBEnvironmentState.save_nb, NBEnvironmentState.reload_nb = save_notebook, reload_notebook
    NBEnvironment._list_dir = list_directory
    NBEnvironment._exec_cmd = execute_command

    async def start_container(state):
        state.docker_client = aiodocker.Docker()
        state.container = await state.docker_client.containers.run(
            config=container_config(spec), name=spec["container_name"])
        append_json(attempt / "transcript.jsonl", {"type": "container.started",
                                                  "name": spec["container_name"]})
    NBEnvironmentState.start_container = start_container
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
        NBEnvironmentState.start_container = original_start
        NBEnvironment.run_notebook = original_run
        NBEnvironment._exec_cmd = original_exec
        NBEnvironmentState.save_nb, NBEnvironmentState.reload_nb = original_save, original_reload
        NBEnvironment._list_dir = original_list
    return {"status": status, "stop_reason": reason, "steps": steps}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--attempt", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
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
