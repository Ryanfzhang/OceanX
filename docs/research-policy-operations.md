# Research-policy self-improvement — implementation and operator guide

Implements `docs/research-tree-rsi-plan.md` (v3, simplified 2026-09-30). The improvement loop is
bounded: models propose, logs and a frozen A/B test measure, and a human decides every change.

## Roles

- **Backend**: saves and maintains the tree and its log. It never writes the Research Tree section
  and never creates nodes on its own.
- **Experts**: answer their node. The numbered items under `Further analysis` in their Summary
  (at most 3, one per line or run together as `1. … 2. …` or `(1) … (2) …`) are saved on the node
  as proposals `B1.2#1`, `B1.2#2`, …; they are not nodes.
- **Coordinator**: every decision. It adopts a proposal only by adding a node with
  `from_proposal: "B1.2#1"` (wording may change); a node whose origin is an Expert proposal is
  refused without it, so adoption is always counted. Unadopted proposals lapse. It selects,
  declines (which closes the candidate with its reason), closes and sets verdicts, binds each
  `task` call to a node with `node_id`, reads
  `view=full` once and writes the final `## Research Tree` section.

## Policies

A policy is a small bundled folder (`resources/policies/<name>/`): `policy.yaml` with
`hypotheses` (enable hypothesis nodes and verdicts) and `frontier` (`shallowest` | `any_depth`),
plus `guidance.md` appended to the Coordinator prompt. With `hypotheses: false` the tree tool does
not offer `set_verdict`, `refutes`/`inconclusive` links or hypothesis nodes at all.

| Policy | Purpose |
|---|---|
| `v0-coordinator-bfs` | Baseline: question nodes only, shallowest-first frontier, no guidance |
| `v1-hypotheses` | Hypothesis nodes, directed evidence links, verdicts; competing-explanations guidance |
| `v2-nested` | Follow-ups placed under the question they continue; `any_depth` frontier, so a nested follow-up starts once its own parent and dependencies have answers instead of waiting for every shallower question |

Nesting and the frontier mode go together: under `shallowest`, a correctly nested follow-up waits for
every unrelated shallower question, so `v2-nested` is the arm to use when follow-ups should nest.

Selection: `OCEANX_RESEARCH_POLICY` > project choice (**Review → Policies**, stored in
`.oceanx/research/active_policy`) > `v0-coordinator-bfs`. A new policy is a code change reviewed
like any other, then compared with paired runs.

## Modules (`src/oceanx/research/`)

| Module | Role |
|---|---|
| `tree_store.py` | Per-task `research_tree.sqlite3`: tree, events, attempts, outcomes, labels; one transaction per mutation |
| `tree.py` | Schema v4: questions, hypotheses, verdicts, evidence links, `decline`, Expert proposals and `from_proposal` adoption |
| `tree_view.py` | Compact text view: one line per node, Result/Limit/proposals, folded finished branches, deltas, 40-node cap |
| `tree_tools.py` | `update_research_tree` (always compact text; hypothesis actions only if the policy enables them) |
| `delegation.py` | `node_id` on the native `task` tool, delegation/attempt IDs, `delegated` events |
| `policy.py` | Load, validate and select bundled policies |
| `outcomes.py` | Per-node cost, code runs, citation, children, proposals made/adopted, reopen/conflict |
| `labels.py` | Auto and judge labels, the small human review set, judge–human agreement |
| `memory.py` | Per-task digests, weekly consolidation and archiving |
| `lessons.py` | Lesson proposals from digests, validation, approval, rendering |
| `acceptance.py` + `resources/evals/research_policy_acceptance.yaml` | Frozen criteria with a hash lock |
| `paired_runs.py` | Paired live runs and frozen-criteria evaluation |
| `review.py`, `cli.py` | Desktop facade and `ocean research ...` commands |

## Labels without rating everything

When a task finishes, log rules label each executed node (`auto`). `ocean research judge-labels`
adds a leave-one-out model judgement (`judge`). The owner labels only a small review set
(top-level branches, cited nodes, auto/judge disagreements, two closed nodes) in
**Review → Branch labels**. Effective label: human > judge > auto.
`ocean research judge-agreement --runs <dirs>` reports how often the judge matches the owner;
when it is high, fewer human labels are needed.

## Lessons and memory

- **Digests.** A finished task is summarised into `.oceanx/research/digests/<task_key>.json`
  (outline, outcomes, labels; a few KB). Lesson mining reads digests only.
- **Cleanup.** After agent requests the backend consolidates at most weekly (no model calls):
  refresh digests, gzip raw stores of finished tasks older than 30 days, and return lessons not
  reviewed for 90 days as retire proposals.
- **Lessons.** The meta model proposes at most 5 per run: ≤40 words, applies-when ≤25 words,
  ≥3 supporting tasks that exist in the digests, ≤12 active per role. The owner edits, approves
  or rejects them in **Review → Lessons**.
- **Runtime.** Coordinator lessons are appended to the policy guidance in its prompt. Expert
  lessons are the `method-lessons` skill for the analysis Experts. The lesson-set version is
  appended to the policy version on every tree event.
- **Meta model.** `role_profiles.meta` in model settings if present, else the Expert profile.

## Operator workflow

1. Run tasks normally, or with `OCEANX_RESEARCH_POLICY=v1-hypotheses`.
2. Label the review set in the desktop (or `ocean research label --tree ... --node B1.2
   --label decision-changing --labeler <you>`); optionally `judge-labels`.
3. Edit `research_policy_acceptance.yaml` (all values are drafts) and
   `ocean research freeze-acceptance --owner <you>`.
4. `ocean research pairs --queries <held_out.jsonl> --output <dir> --policy-a v0-coordinator-bfs
   --policy-b v1-hypotheses`, rate each case once (`{case, better: A|B|same}` JSONL), then
   `ocean research evaluate-pairs --output <dir> --quality <file>`.
5. If it passes, activate the policy in **Review → Policies**.

## Known limitations

- Acceptance values are placeholders and there is no held-out query set yet (owner decisions).
- Expansion and stopping are Coordinator judgement plus policy guidance; there is no rule engine
  or per-branch budget beyond the Expert call limit.
- Parked until paired runs justify them: suggested candidate order, logged propensities,
  randomised exploration, offline replay, meta-model policy proposals, proxy scorers.

## Verification status

Research modules are tested in isolation (`test_research_*`, run with a pytest stand-in because
PyPI was unreachable from the development sandbox). Not yet run: the full `tests/test_oceanx`
suite, anything needing DeepAgents/LangGraph (middleware inside a real graph, `graphs.py`, router
handlers), the desktop dialog in a running app, and any live model run.
