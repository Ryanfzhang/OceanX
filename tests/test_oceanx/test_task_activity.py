"""The activity a running task records, which the desktop and the web page show after a refresh or
reconnect (request-activity.ts): a tool failure must not outlive the work that follows it."""
from types import SimpleNamespace

from oceanx.agent_contract import ToolExecutionCompleted, ToolExecutionStarted
from oceanx.backend.router import TOOL_FAILURE_ACTIVITY, OceanRequestRouter


class _Store:
    def __init__(self) -> None:
        self.activities: list[str] = []

    def transition_task_workflow(self, *, request_id, state, activity, failure_fingerprint=None):
        assert (request_id, state) == ("req", "working")
        self.activities.append(activity)


def _router() -> OceanRequestRouter:
    router = object.__new__(OceanRequestRouter)  # only the activity bookkeeping is exercised
    router.store, router._after_tool_failure = _Store(), set()
    router._task_id = lambda request: "task"
    return router


def test_a_tool_failure_is_cleared_by_the_work_that_follows():
    """Server run of 2026-10-26: an analysis error at 20:33 stayed on the page ("Adjusting after a
    tool error") while the agent went on running its scripts through the shell successfully."""
    router, request = _router(), SimpleNamespace(request_id="req")

    def started(tool):
        router._update_task_workflow_for_event(request, ToolExecutionStarted(tool_name=tool, tool_input={}))

    def finished(tool, error=False):
        router._update_task_workflow_for_event(
            request, ToolExecutionCompleted(tool_name=tool, output="IndexError" if error else "ok", is_error=error))

    finished("ocean_expert_run_code", error=True)
    started("execute")  # a script run through the shell is the agent's code too
    finished("execute")
    assert router.store.activities == [TOOL_FAILURE_ACTIVITY, "Expert running code", "Expert interpreting the code result"]
    # A step that records no activity of its own still ends a failure the page shows ...
    finished("execute", error=True)
    finished("read_file")
    assert router.store.activities[-2:] == [TOOL_FAILURE_ACTIVITY, "Working on the request"]
    # ... and otherwise writes nothing.
    finished("read_file")
    started("ls")
    assert len(router.store.activities) == 5 and not router._after_tool_failure
