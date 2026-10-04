"""Subprocess fixture: real Agent Server/Deep Agents, deterministic model, no API credits."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from oceanx.research.services import parse_expert_receipt


def assignment_text(node, question, *, parent_question="None", parent_answer="None", parent_report="None"):
    return (f"Question ({node}): {question}\n\n"
            f"Parent question: {parent_question}\n\n"
            f"Parent answer: {parent_answer}\n\n"
            f"Parent report: {parent_report}")

class FixtureModel(FakeMessagesListChatModel):
    names: set[str] = Field(default_factory=set)

    def bind_tools(self, tools, **kwargs):
        self.names = {t.name if hasattr(t, "name") else t["name"] for t in tools}
        return self

    async def _agenerate(self, messages, **kwargs):
        await asyncio.sleep(30 if os.environ.get("OCEAN_FIXTURE_MODE") == "cancel" else 0.05)
        return self._generate(messages, **kwargs)

    def _generate(self, messages, **kwargs):
        def call(name, args):
            return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": str(uuid4()), "type": "tool_call"}])
        if "task" in self.names:
            assert "finish_research" not in self.names
            if os.environ.get("OCEAN_FIXTURE_MODE") in {"gateway", "gateway_followup", "gateway_missing_report"}:
                system_prompts = [m.text for m in messages if isinstance(m, SystemMessage)]
                assert any("Literature acquisition mode: search_only" in text
                           for text in system_prompts), system_prompts
            receipts = [m for m in messages if isinstance(m, ToolMessage) and m.name == "task"]
            if not receipts:
                role = ("ocean_process_expert"
                        if os.environ.get("OCEAN_FIXTURE_MODE") in {
                            "code", "long_report", "missing_report"
                        }
                        else "scientific_discussion_partner")
                answer = call("task", {"subagent_type": role, "description": assignment_text(
                    "B1", "Explain whether formation and persistence are different questions. Remember CAMPECHE_ONE.")})
            elif os.environ.get("OCEAN_FIXTURE_MODE") == "gateway_followup" and len(receipts) < 3:
                parent_summary, parent_report = parse_expert_receipt(receipts[0].text)
                question = (assignment_text(
                    "B1.1", "Follow up the first result.",
                    parent_question="B1: Explain whether formation and persistence are different questions.",
                    parent_answer=parent_summary, parent_report=parent_report or "None")
                    if len(receipts) == 1 else assignment_text(
                        "B2", "Explore an independent alternative."))
                answer = call("task", {"subagent_type": "scientific_discussion_partner",
                                       "description": question})
            else:
                if os.environ.get("OCEAN_FIXTURE_MODE") in {"coordinator_missing_report", "gateway_missing_report"}:
                    return ChatResult(generations=[ChatGeneration(message=AIMessage(
                        content="I'm now waiting on the Ocean Process Expert. No further action."))])
                assigned = re.search(r"Backend-assigned final report file: ([^\n]+)", "\n".join(
                    m.text for m in messages if isinstance(m, SystemMessage))).group(1)
                saved = [m for m in messages if isinstance(m, ToolMessage)
                         and m.name in {"write_file", "edit_file"}]
                if not saved:
                    receipt, _report_path = parse_expert_receipt(receipts[-1].text)
                    answer = call("write_file", {"file_path": assigned, "content":
                        "# Fixture synthesis\n\n## Summary\n\n" + receipt})
                else:
                    assert saved[-1].status != "error", saved[-1].text
                    answer = AIMessage(content="Saved the report.")
        else:
            if os.environ.get("OCEAN_FIXTURE_MODE") == "failure":
                raise RuntimeError("Injected provider failure for notification test")
            humans = [m.text for m in messages if isinstance(m, HumanMessage)]
            assignment = humans[-1]
            system_prompts = [m.text for m in messages if isinstance(m, SystemMessage)]
            if os.environ.get("OCEAN_FIXTURE_MODE") == "missing_report":
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Done without saving."))])
            if "ocean_expert_run_code" in self.names:
                assert "ocean_load_skill" not in self.names and "ocean_list_skills" not in self.names
                skill_reads = [m for m in messages if isinstance(m, ToolMessage) and m.name == "read_file"]
                if not skill_reads:
                    assert any("xarray-array-ops" in m.text for m in messages if isinstance(m, SystemMessage))
                    answer = call("read_file", {"file_path": "/skills/xarray-array-ops/SKILL.md"})
                    return ChatResult(generations=[ChatGeneration(message=answer)])
                assert "ao.self_test()" in skill_reads[0].text
                last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
                computed = [m for m in messages[last_human + 1:] if isinstance(m, ToolMessage) and m.name == "ocean_expert_run_code"]
                if not computed:
                    code = ("import oceanx_array_ops as ao\nprint(ao.self_test())\n"
                            "temperatures = [1, 2, 3]\nprint('CREATED', temperatures)\n"
                            "from pathlib import Path\nPath('evidence.txt').write_text('mean=2')\n")
                    answer = call("ocean_expert_run_code", {"purpose": "Verify persistent and isolated scientific execution", "code": code})
                    return ChatResult(generations=[ChatGeneration(message=answer)])
                # The budget line a real model reads after the result is not part of the result.
                result_text = re.sub(r"\n\n\[Budget: [^\]]*\]$", "", computed[-1].text)
                try:
                    payload = json.loads(result_text)
                except ValueError:
                    raise AssertionError(f"Unexpected code result: {computed[-1].text}") from None
                assert payload.get("state") == "succeeded", payload
            finding = "Formation and persistence need not have the same explanation. Marker CAMPECHE_ONE."
            summary = ("Result: " + finding + "\n"
                       "Evidence and limitations: Fixture evidence is deliberately bounded.\n"
                       "Further analysis: Test the unresolved alternative.")
            body = finding
            if os.environ.get("OCEAN_FIXTURE_MODE") == "long_report":
                body += "\n" + "海洋证据与局限。" * 1500
            assert "ocean_deliver" not in self.names
            if "write_file" in self.names:
                assigned = re.search(r"Backend-assigned report file: ([^\n]+)", "\n".join(
                    m.text for m in messages if isinstance(m, SystemMessage))).group(1)
                last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
                saved = [m for m in messages[last_human + 1:] if isinstance(m, ToolMessage)
                         and m.name in {"write_file", "edit_file"}]
                if not saved:
                    heading = "# Formation and persistence"
                    body = f"{heading}\n\n## Summary\n\n{summary}\n\n## Analysis\n\n{body}"
                    # Use the actual native filesystem tool for both initial and follow-up writes.
                    path = Path(assigned)
                    if path.exists():
                        return ChatResult(generations=[ChatGeneration(message=call("edit_file", {
                            "file_path": assigned, "old_string": path.read_text(), "new_string": body}))])
                    return ChatResult(generations=[ChatGeneration(message=call("write_file", {
                        "file_path": assigned, "content": body}))])
                assert saved[-1].status != "error", saved[-1].text
                answer = AIMessage(content="Done.")
            else:
                answer = AIMessage(content=f"## Summary\n\n{summary}\n\n## Analysis\n\n{body}")
        answer.usage_metadata = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        return ChatResult(generations=[ChatGeneration(message=answer)])


def install():
    from oceanx import agent, deep_runtime
    from oceanx.model_config import OceanModelProfile
    from oceanx.research import app, graphs
    profile = OceanModelProfile("fixture", "Fixture", "openai", "fixture", None, "fixture", "not-a-real-key")
    graphs.load_model_profile = lambda *args, **kwargs: profile
    agent.load_model_profile = lambda *args, **kwargs: profile
    deep_runtime.create_chat_model = lambda *args, **kwargs: FixtureModel(responses=[])
    deep_runtime._configure_native_harness("fixturemodel")
    os.environ["OCEAN_SANDBOX_PYTHON"] = sys.executable
    original = app.app.router.lifespan_context

    @asynccontextmanager
    async def seeded(application):
        async with original(application):
            from oceanx.research.services import host
            h = host()
            root = Path(os.environ["OCEAN_STATE_DIRECTORY"]) / "workspace"
            root.mkdir(exist_ok=True)
            await h.stdio.handle_line(json.dumps({"protocol_version": 2, "request_id": "req_fixture_handshake", "type": "system.handshake", "payload": {"client_kind": "desktop", "client_version": "test", "supported_protocol_versions": [2]}}))
            cl = h.stdio.client
            await h.stdio.handle_line(json.dumps({"protocol_version": 2, "request_id": "req_fixture_open", "type": "workspace.open", "payload": {"path": str(root)}, "context": {"client_id": cl.client_id, "session_id": cl.session_id, "workspace_id": "ws_fixture"}, "expected_workspace_revision": 0}))
            if h.store.get_research_task("task_fixture") is None:
                h.store.create_research_task(workspace_id="ws_fixture", task_id="task_fixture", title="Agent Server integration")
            yield
    app.app.router.lifespan_context = seeded


if __name__ == "__main__":
    install()
    from oceanx.research.server import main
    main()
