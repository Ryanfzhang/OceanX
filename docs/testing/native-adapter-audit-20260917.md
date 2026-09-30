# Native DeepAgents integration audit — 2026-09-17

Scope: current working tree, DeepAgents 0.7.9 and LangGraph 1.2.11. No production
logic was edited for this audit. No paid API calls or existing research tasks
were used. Reproduction harness: `/private/tmp/oceanx-native-audit-20260917.py`.

## Confirmed findings

### 1. Completion notification precedes the native terminal run status

`src/oceanx/research/notifications.py:56` wakes the parent from `on_chain_end`.
Agent Server marks the native run successful after graph streaming returns;
DeepAgents `check_async_task` only reads the final message when the native run
status is `success`. The wake-up currently instructs the Coordinator to check once.

Reproduced with the real local Agent Server, existing deterministic fixture model,
and a two-second delay after notification creation but before the graph callback
returns. The delay exposes the ordering window; task state was not patched.

```json
{
  "native_child_status": "success",
  "coordinator_cached_status": "running",
  "parent_runs": ["success", "success"],
  "research_complete": false,
  "last_message": "Waiting for the Expert; this is not a final answer."
}
```

This proves the current integration can strand the parent. It does not by itself
identify the cause of any particular historical task. Notification needs to follow
the server's committed terminal status, without creating another task-state store.

### 2. Desktop stream continuation can select a previous request's run

`src/oceanx/research/gateway.py:34` selects the oldest unseen run across the whole
thread; `seen` is reset for every submitted request. It does not restrict selection
to the current request. A focused reproduction supplied one current completed run
and an older failed run; `_next_native_run({current_id})` selected the older failure.
The caller treats that run's error as fatal. Native continuation observation must
be scoped to the current submitted request.

### 3. Thin review inherits the author's consumed model-call allowance

`src/oceanx/research/graphs.py:154` restores usage by `agent_run_id` alone.
`AgentRun.as_review()` keeps that ID, but review sets a smaller limit of eight.
The restored count includes the author's calls.

Reproduced by running the actual graph builder with eight recorded author calls
and capturing its review middleware. The review starts with `used=8, limit=8`;
the model handler is never invoked and the result is:

```text
Handoff failed: No model allowance remains for a handoff.
```

Retaining the agreed call limits requires separating author and review accounting,
not silently resetting either during reconstruction.

### 4. The old local conversation checkpoint remains a delivery gate

`src/oceanx/backend/router.py:2712` still commits the entire engine conversation to
the product database as part of successful completion. Agent Server already owns
the conversation checkpoint. `src/oceanx/backend/store.py:1405` rejects this
duplicate when its JSON exceeds 2 MiB.

A direct reproduction of that commit precondition raises:

```text
Task checkpoint payload exceeds the hard limit
```

This is a confirmed failure condition, not a claim that the current conversation
has exceeded it. Product completion should not depend on this second restorable
model-memory copy. The user-facing transcript is already separately stored.

### 5. Literature acquisition preferences are written into an ignored context path

`src/oceanx/backend/router.py:1908` sets a prompt containing
`literature_acquisition_mode`. `ServerGraphStream.handles_context=True` then makes
`DeepAgentEngine._input_messages()` omit and clear that context. The new graph
build reconstructs dataset context but does not receive the acquisition preference.

Reproduced using the actual prompt builder and input transformation: a
`search_only` prompt produces only the user's question as input, with no preference.
The preference needs to travel through the actual Agent Server configuration;
the obsolete prompt-refresh path should be removed once its needed inputs move.

## Distinctions checked

- No active `UCB`, `team_work_records`, `work_order_id`, `result_summary`,
  `ocean_deliver`, or `finish_research` references were found in production Python.
- The installed summarizer already has native retry support. No missing-retry
  claim is made here.
- The installed middleware stack replaces custom middleware by its registered
  name. The configured filesystem/summarization overrides do not by themselves
  mean two copies execute.
- Research-tree evidence, assigned report paths, and scientific execution are
  product capabilities; their presence alone does not establish a second scheduler.

## Validation

Four focused reproductions and one isolated real-server ordering reproduction
confirmed the findings above. The diagnostic server was stopped after the test.
Desktop sidecar verification, frontend type checks, source compilation, and
`git diff --check` also passed. Those checks do not invalidate the five reproduced
integration failures. The previous eleven-mode integration fixture uses a single
parent request and short Expert rounds, so it does not cover these cases.
