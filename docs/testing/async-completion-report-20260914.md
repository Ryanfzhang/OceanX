# Async completion and file-backed Coordinator delivery

## Reference and scope

The notification mechanism follows LangChain's
[completion notifier reference](https://github.com/langchain-ai/async-deep-agents/blob/main/graphs/python/src/middleware/completion_notifier.py):
send a new user-role completion/error message to the supervisor thread using
`client.runs.create`. Agent Server schedules the resumed run. This is a reference
implementation, not an importable default completion hook in DeepAgents 0.7.9.

OceanX's only completion adaptation uses a root-graph callback because its Expert consists of
author, file persistence and a thin check. An author's model-loop completion is
too early. The former explicit notification node and separate failure callback
are replaced by one completion/error callback surrounding that graph. The callback
only creates the parent wake-up message from the reference implementation; it does
not read or patch native `async_tasks`, mirror status, update the research tree, or
feed a local queue. The desktop observes subsequent runs from Agent Server directly.
`team_work_records` are UI/usage/evidence projections only. No local scheduler or
model polling loop is introduced.

The native DeepAgents tool contract is left intact: after `start_async_task` the
Coordinator stops and does not immediately poll. A completion message supplies one
exact task ID, and the resumed Coordinator calls `check_async_task` once to import
the native terminal receipt. Normal report publication does not cancel or drain the
thread. Run cancellation is reserved for an explicit cancelled foreground request.

## Delivery boundary

An empty tool-call list is not a research deliverable. Coordinator receives a
backend-assigned `report.md` under its writable directory, unique per user request.
It writes the synthesis using the existing native file tools. The delivered text
comes from that file, not from its final conversational acknowledgement.

The Coordinator—not a backend child-status gate—decides when the research is ready for
synthesis. When it finishes, a missing, empty or unchanged assigned report is a delivery
error, not a successful report. Previously saved Expert evidence is preserved. There is
no new finish tool, scientific content classifier or automatic retry loop.
The file check verifies persistence only; it cannot assess scientific quality or
guarantee that a model wrote an adequate synthesis.

## Regression coverage

- Whole-graph completion/error sends a notification; inner author completion does not.
- Notifications use the new-event message role and preserve native task identity.
- Reports, not “waiting”/“saved” acknowledgements, determine published text.
- Missing, stale and empty final reports cannot mark research complete.
- Isolated Agent Server tests exercise native dispatch, follow-up, report reads,
  persistence/reviewer failures, restart persistence and the desktop WebSocket path.

Tests use a deterministic local model and synthetic evidence. They verify the
integration, not DeepSeek's scientific or conversational behavior on the real query.

Validation on 2026-09-14:

- `test_agent_server_integration.py`: 13 passed, including WebSocket false-completion regression (140.61 s).
- `test_execution_efficiency.py`, `test_research_run_projection.py`,
  `test_deepseek_handoff.py`, `test_research_handoff_contract.py`: 29 passed.
- `test_current_team_contract.py` and `test_deepseek_handoff.py`: 62 passed
  (overlaps the preceding group; counts are not additive).
- Python compilation and `git diff --check`: passed.

The running desktop backend must be restarted to load these changes. Existing task
reports are not regenerated or rewritten by this migration.
