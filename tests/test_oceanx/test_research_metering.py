"""Model-call metering: nested Expert calls keep their own role, failures keep their cause."""
import asyncio
import uuid
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from oceanx.research.metering import INSIDE_EXPERT, CallMeter

CONFIG = {"configurable": {"request_id": "request", "thread_id": "thread"}}


class _Store:
    def __init__(self):
        self.records = {}

    def record_model_call(self, record):
        self.records[record["call_id"]] = dict(record)


def _start(meter, run_id):
    return meter.on_chat_model_start({}, [[]], run_id=run_id, metadata={})


def test_coordinator_meter_leaves_expert_calls_to_the_expert_meter():
    store = _Store()
    coordinator = CallMeter(store, CONFIG, "coordinator")
    expert = CallMeter(store, CONFIG, "ocean_process_expert", SimpleNamespace(
        agent_run_id="ocean-process-x", node_id="B1.3", delegation_id="d", attempt_id="a"))
    own, nested = uuid.uuid4(), uuid.uuid4()

    async def scenario():
        await _start(coordinator, own)
        token = INSIDE_EXPERT.set(True)
        try:
            await _start(expert, nested)
            # The Coordinator's callbacks are inherited by the Expert run; firing after the
            # Expert's own meter, they used to overwrite the record with role "coordinator".
            await _start(coordinator, nested)
        finally:
            INSIDE_EXPERT.reset(token)

    asyncio.run(scenario())
    assert store.records[str(own)]["role"] == "coordinator"
    assert store.records[str(nested)]["role"] == "ocean_process_expert"
    assert store.records[str(nested)]["node_id"] == "B1.3"


def test_failed_call_records_the_transport_cause_chain():
    store = _Store()
    meter = CallMeter(store, CONFIG, "coordinator")
    run_id = uuid.uuid4()
    try:
        try:
            raise TimeoutError("connect")
        except TimeoutError as connect:
            raise ConnectionError("transport") from connect
    except ConnectionError as transport:
        error = RuntimeError("provider timeout")
        error.__cause__ = transport

    async def scenario():
        await _start(meter, run_id)
        await meter.on_llm_error(error, run_id=run_id)

    asyncio.run(scenario())
    record = store.records[str(run_id)]
    assert (record["state"], record["error_type"]) == ("failed", "RuntimeError")
    assert record["error_causes"] == ["ConnectionError", "TimeoutError"]


def test_a_call_records_which_skills_it_opened():
    store = _Store()
    meter = CallMeter(store, CONFIG, "coordinator")
    run_id = uuid.uuid4()
    message = AIMessage(content="", tool_calls=[
        {"name": "read_file", "id": "1",
         "args": {"file_path": "/skills/research-trajectory-planning/SKILL.md", "limit": 1000}},
        {"name": "read_file", "id": "2", "args": {"file_path": "/work/report.md"}},
        {"name": "update_research_tree", "id": "3", "args": {"changes": []}}])

    async def scenario():
        await _start(meter, run_id)
        await meter.on_llm_end(SimpleNamespace(generations=[[SimpleNamespace(message=message)]]),
                               run_id=run_id)

    asyncio.run(scenario())
    assert store.records[str(run_id)]["skills_read"] == ["research-trajectory-planning"]
