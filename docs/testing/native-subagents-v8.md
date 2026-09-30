# Native subagents v8

## Scope and run status

The user requested stopping `campeche-fixed-outputs-20260913` and replacing dispatch, removing
the Data role, and keeping assignments at complete-subquestion granularity. The test parent
(52047) and backend (52049) were stopped and verified absent. Its heartbeat was paused.
Research files were retained. No new paid API research run was started.

## Implementation

- `agent.py` registers compiled LangGraph subagents with `create_deep_agent`.
- DeepAgents `SubAgentMiddleware` owns the actual `task` tool, isolated incoming messages,
  parallel tool dispatch and return ToolMessages. It is not an `ocean_assign` rename.
- `team/subagents.py` supplies the supported compiled-runnable adapter; `backend/router.py`
  binds each native invocation to supplied sources, the original query and an execution ID.
  These IDs are backend facts, not additional model input fields.
- `execute_work` retains execution, model telemetry, cancellation, same-type review/repair and
  durable report saving. There is no old dispatch-list conversion in the active path.
- Data is absent from the profile catalog and native registry. Dataset diagnosis guidance is
  available to the physical/statistical analysis roles. Experts cannot spawn further subagents.
- New calls have isolated conversations, as native task does; follow-up descriptions can
  reference prior report paths. One invocation still has a fixed writable output directory.
- The policy fingerprint is bumped to `native-subagents-v8`, so a new runtime does not resume
  the old tool schema's conversation. Models and scientific resource budgets were not changed.

## Verification

Offline tests exercise the installed DeepAgents middleware with deterministic fake model
responses (no network/API spending): real parallel task execution, same-role isolation,
request/tool IDs, compact file handoff, failed-branch isolation and model-visible tool names.
Backend tests cover source binding, original query, idempotent task replay, file-based follow-up
and rejection of the removed Data role. Existing tests cover artifact review and fixed outputs.
The native endpoint's actual WorkOrder is also passed through the real review gate and report
saving lifecycle, verifying that the routing change does not silently bypass review.

Final command: `.venv/bin/python -m pytest tests/test_oceanx tests/test_sandbox -q --tb=short`.
Result: **653 passed, 3 skipped, 4 warnings**, 57.78 seconds. The first combined run was blocked
by the outer host sandbox (`sandbox_apply: Operation not permitted` and loopback bind denial);
rerunning with permission to launch the project's sandbox passed. No application permissions
were weakened. Final log: `/tmp/oceanx-native-subagents-v8-verified.log`.

These tests establish executable plumbing, not spontaneous scientific behavior. No live run of
this version has demonstrated shorter runtime, fewer tokens, better answers, or reliably broader
question-level delegation. Restart the backend before evaluating v8; do not resume the stopped run.
