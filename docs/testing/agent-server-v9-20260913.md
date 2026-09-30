# Agent Server migration: implementation and observed validation

Date: 2026-09-13 (Asia/Hong_Kong). This document distinguishes engineering
verification from the unsuccessful paid-model research run. It is not a claim that
research quality, latency or token efficiency has improved.

## Implemented replacement

- Desktop and batch launch the same local Agent Server. Native DeepAgents async
  tasks own real child threads/runs and same-thread follow-up.
- Deleted the custom OceanTeamOrchestrator execution path, dispatch/subagent wrapper,
  old review runner, WorkPlan/CoordinatorTodo validation and budget wind-down.
- The remaining domain records describe execution/files/UI and permissions; models
  do not fill these records as delegation forms. There is no separate result index.
- No Data Expert. Computational Experts inspect supplied data and choose methods.
- Persistent, isolated Jupyter kernels and stable Expert directories; canonical
  report.md updated by its author. Review uses a separate kernel and the configured
  Coordinator API. Final delivery explicitly finishes open branches.
- Provider failure recovery now lives at the model call, including summaries, not
  at an outer graph replay loop. Transient errors wait until recovery/cancellation;
  bad credentials, exhausted provider credit and invalid requests fail explicitly.

Source snapshot before migration: `/private/tmp/oceanx-before-agent-server-20260913.tar.gz`.
User datasets and existing result directories were not deleted.

## Engineering evidence

The integration suite runs actual local Agent Server processes with a deterministic
model, not mock HTTP endpoints. It covers native dispatch, same-thread continuation,
server restart with persisted conversation, a single canonical report, author/reviewer
kernel separation, model failure, report-persistence failure notification, and desktop
WebSocket delivery of the final answer. Kernel tests include state reuse, isolation and
cancellation of a busy Python process. The restart test does not claim Python RAM
survives a server restart or that arbitrary mid-run crash recovery has been validated.

Model-call retry tests exercise six transient failures before success on the same
request, permanent failure without retry, cancellation during waiting and summary
retries with preserved input/configuration. They do not use a paid API.

Frontend: 196 tests passed; both TypeScript checks passed, using the ARM Node binary
in the oceanx Conda environment. Default x86 Node cannot use the installed ARM Rollup
binary; no dependency directory was deleted to mask that mismatch.

The selected ARM Conda environment was updated using requirements.txt. A real launch,
desktop handshake, workspace/task creation and read-only CMEMS directory attachment
then succeeded without invoking a model. Startup evidence:
`/var/folders/pg/qv_z4htj61g2xtrcj5k8ws740000gn/T/oceanx-conda-server-xf304u26`.

Final Python regression: **546 passed, 3 skipped**, with four upstream NumPy/Zarr
warnings, in 111.29 seconds. JUnit evidence: `/private/tmp/oceanx-v9-regression.xml`.
This includes the five real Server integration scenarios and persistent-kernel tests.
The built wheel was inspected: all 11 research modules, kernels and model-call retry
module are present; retired orchestrator/dispatch/subagent/review/recovery modules
are absent. Final process inspection found no remaining test Server or kernel.

## Paid Campeche run: failed, no completed scientific delivery

Question: “What mechanisms drive the formation and persistence of seasonal warm
anomalies in the Bay of Campeche, using the provided one-year GLORYS12 dataset?”

Data: `/Users/ryanzhang/Code/CMEMS_oceanmind`, read-only. The directory actually
contains 2025 plus early 2026 files; the one-year wording is not proof of the files'
coverage. Coordinator used configured DeepSeek v4 Pro; Experts used v4 Flash.
No all-Pro model change was made.

Run directory:
`output/campeche-agent-server-v9-live-20260913/query/attempt-1789247031626260000-c47cba22/`

Evidence: `result.json`, `events.jsonl`, `state/workspace.sqlite3`,
`state/agent-server.log`, and the per-Expert code/log/result files in `workspace/`.

The request ran from 21:03:57.689 to 21:23:57.046 UTC on September 12: **19m59s**.
It started Physics and Statistics concurrently, with no Data Expert. Both performed
calculations in persistent kernels, but neither delivered its scientific report before
an OpenAIConnectionError. The final request status is failed. Saved report.md files
are explicit execution-failure notices, not scientific answers or successful recovery.
No artifact review ran because the authors did not reach completed delivery.

| Role | Model calls (failed) | Recorded input tokens | Recorded output tokens | Cache-read tokens | Sum of model-call seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Coordinator | 8 (6) | 12,490 | 2,618 | 7,296 | 132.59 |
| Physics | 60 (1) | 2,467,574 | 135,184 | 2,104,704 | 666.87 |
| Statistics | 71 (1) | 3,080,431 | 158,802 | 2,187,904 | 757.91 |

Known total: **5,560,495 input + 296,604 output tokens**. Failed calls without usage
metadata are unknown, not zero. Cache-read tokens are included in input tokens, not
added again; token totals are not dollar costs. Summary calls are included: Physics
4 and Statistics 8. Parallel durations must not be added to infer request wall time.

Python: 106 calls, 76 successful and 30 failed, totaling 215.18 seconds of recorded
kernel execution across both Experts. This excludes snapshot/archive overhead in
that loaded build; those timestamps were extended afterward. Therefore the remainder
of wall time must not all be labeled “model thinking”. Logs include array-shape and
indexing errors, a shadowed time symbol, removed NumPy API usage and signature/CSV
errors. Successful execution does not establish numerical correctness.

The first Physics message still enumerated four mechanisms and a suite of diagnostics;
Statistics also received detailed method issues. Thus native subagents did **not**, by
themselves, eliminate checklist-style delegation. There was no completed evidence return
on which to evaluate Coordinator deepening or a research-tree benefit.

## Fixes driven by this run and remaining limits

The run exposed an incomplete retry migration: Experts could fail on a transient API
connection error, while Coordinator still used the old four-retry outer wrapper.
This wrapper has since been deleted and model-level retries added for both roles and
summaries. Unit/integration tests verify the revised mechanism; the failed paid run
predates that fix and must not be presented as a successful post-fix research test.

The implementation uses the pinned single-host development Agent Server runtime,
not a production PostgreSQL/Redis deployment. macOS/Linux persistent-kernel sandboxes
are supported; Windows persistent-kernel migration is not complete. Packaged desktop
applications need rebuilding/restarting to load this source version.

The engineering migration is separate from the unresolved empirical questions:
successful full research delivery, cost reduction, better decomposition and evidence-led
follow-up still need a successful paid-model run. Do not infer them from passing tests.
