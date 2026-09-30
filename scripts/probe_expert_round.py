"""Paid, isolated Expert handoff probe using production build/tools/quota (no Coordinator).

The host is seeded in-process for this component test; Agent Server notification
routing is covered separately by test_agent_server_integration.py.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import HumanMessage


async def main(root):
    from oceanx.backend.events import BackendClient
    from oceanx.backend.host import OceanBackendHost
    from oceanx.research import services
    from oceanx.research.graphs import ExpertPreparation, build

    root.mkdir(parents=True, exist_ok=False)
    workspace = root / "workspace"
    workspace.mkdir()
    h = services._active_host = OceanBackendHost(root / "state", write_frame=lambda _: None)
    started = time.monotonic()
    try:
        async def discard_event(event):
            if event.type in {"system.error", "request.failed"}:
                raise RuntimeError(event.model_dump_json())
        client = BackendClient(transport="stdio", expected_client_kind="desktop", sender=discard_event)
        await h.event_bus.register(client)
        await h.router.handle_payload(client, {"protocol_version": 2, "request_id": "req_probe_handshake",
            "type": "system.handshake", "payload": {"client_kind": "desktop", "client_version": "probe",
                                                     "supported_protocol_versions": [2]}})
        await h.router.handle_payload(client, {"protocol_version": 2, "request_id": "req_probe_open",
            "type": "workspace.open", "payload": {"path": str(workspace)},
            "context": {"client_id": client.client_id, "session_id": client.session_id,
                        "workspace_id": "ws_round_probe"}, "expected_workspace_revision": 0})
        task = h.store.create_research_task(workspace_id="ws_round_probe", title="Narrow Expert handoff probe")
        question = ("这是独立的小范围计算测试，不是机制研究。给定连续五天温度为 "
                    "20、21、22、23、24 摄氏度，均值和极差各是多少？用 Python 核对，"
                    "将结果保存为一个小文件，交付一句结论和证据路径。不需要图。")
        config = {"configurable": {"workspace_id": "ws_round_probe", "workspace_path": str(workspace),
            "task_id": task.task_id, "request_id": "req_round_probe", "thread_id": str(uuid4()),
            "run_id": str(uuid4()), "original_question": question, "question": question},
            "recursion_limit": float("inf")}
        order = h.research.order(config, "statistical_inference_expert")
        graph = await build(config, "statistical_inference_expert", order=order,
                            middleware=[ExpertPreparation(config, order)])
        result = await graph.ainvoke({"messages": [HumanMessage(content=question)]}, config=config)
        last = result["messages"][-1]
        _, report = h.research.save_answer(order, last.text,
            error=last.text if last.additional_kwargs.get("oceanx_delivery_error") else None)
        (root / "messages.json").write_text(json.dumps(
            [m.model_dump(mode="json") for m in result["messages"]], ensure_ascii=False, indent=2))
        calls = h.store.list_model_calls(order.parent_request_id)
        measurement = {"scope": "isolated production Expert build; no review or Coordinator",
            "seconds": time.monotonic()-started, "report": str(report),
            "delivered": last.additional_kwargs.get("oceanx_delivered", False),
            "model_calls": len(calls), "effective_calls": sum(c.get("counts_toward_round", True) for c in calls),
            "input_tokens": sum((c.get("usage") or {}).get("input_tokens", 0) for c in calls),
            "output_tokens": sum((c.get("usage") or {}).get("output_tokens", 0) for c in calls)}
        (root / "measurement.json").write_text(json.dumps(measurement, ensure_ascii=False, indent=2))
        print(json.dumps(measurement, ensure_ascii=False))
    finally:
        await h.close()
        services._active_host = None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    asyncio.run(main(parser.parse_args().output.resolve()))
