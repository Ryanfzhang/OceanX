# Bounded Research-Policy Self-Improvement for OceanX — Plan v3

Date: 2026-09-29 · Status: implemented, then simplified 2026-09-30 (proposals adopted by the Coordinator; suggestions, replay, meta-model policy proposals and proxy scorers parked); 2026-10-01: approved lessons are written into the skills each role already reads, not into a prompt; 2026-10-02 (owner's decision): lessons and learned helper functions (tools) are maintained by the meta-agent inside marked regions of the skills and take effect without an approval step, tools are kept or dropped by call counts, the owner can mark any item right or wrong, and the research policy is fixed to v2-nested, so the statements below that a human merges every change now hold for the policy only; experiments not yet run — see docs/research-policy-operations.md · History: v1 draft → v2 after Codex review → v3 comprehensive
Owner: ryanfanzhang · Reviewers: Codex, Claude

## 0. Summary

OceanX's research tree records what was asked and what came back, but not why a branch was chosen,
what it cost, or whether it mattered, and each tree is discarded after its task. This plan makes the
tree a complete **trajectory record** and makes the **research search policy** (how candidates are
ranked and budget is allocated; later expansion and stopping) a versioned object that a meta-agent may
propose improvements to. Proposals are accepted only against **frozen external criteria**, and a human
merges every change. This is bounded self-refinement with a human on the loop (Chen et al. 2026,
arXiv:2607.07663), not open-ended RSI.

Two research questions decide whether the later phases are worth building: whether a learned ranking
beats the Coordinator's own judgement (RQ1), and whether explicit hypothesis nodes improve mechanism
attribution (RQ2).

## 1. Scope

In scope: research tree data model, structured delegation, event and cost logging, Coordinator tree
view, versioned search policy, meta-agent proposal loop, evaluation for policy acceptance.

Out of scope: LLM-authored Skills, Expert prompt evolution, model fine-tuning, benchmark-wide
evaluator hardening (only the minimal frozen gate in §8 is required), any self-edit of evaluators.

## 2. Current state (v3 tree) and drawbacks

Files: `src/oceanx/research/tree.py` (schema `oceanx-research-tree/v3`), `tree_tools.py`
(`update_research_tree`), `graphs.py` (Coordinator/Expert graphs, result binding), `runtime.py`
(`OCEAN_EXPLORATION_POLICY`).

1. **No decision data.** No per-node cost, no history (JSON overwritten; only a revision counter),
   reasons only on `close`, no outcomes, no human feedback.
2. **Single result.** `attach_result` overwrites; reruns, re-reviews and other Experts are lost.
3. **Fragile binding.** Node found by regex `B\d+` in task text (`graphs.py`). DeepAgents
   `TaskToolSchema` has only `description` and `subagent_type`: no structured channel.
4. **Questions only.** Competing mechanisms and verdicts live in report prose.
5. **Context cost.** Each tool call returns the full JSON projection (~5.4k chars for 9 nodes).
6. **Fixed policy.** `frontier()` = shallowest selected + prose rules; nothing versioned or learnable.

## 3. Research questions

Engineering items (§5) just need building. These five are genuine research, ordered by priority.

**RQ1 — Learned ranking vs. Coordinator judgement (go/no-go for Phases 3–4).**
Hypothesis: a policy trained on logged outcomes reaches decision-changing nodes at lower cost.
Metric: cost (tokens) per `decision-changing` node; number of `misleading-or-wasteful` executions;
task-level quality under the frozen criteria. Design: paired live runs, same query/data/model/budget,
policy A vs B, ≥ N tasks (N fixed at the Phase 3 gate). If no improvement → stop at Phase 2.

**RQ2 — Hypothesis-explicit trees and mechanism fidelity (most ocean-specific).**
Hypothesis: representing competing mechanisms as hypothesis nodes increases discriminating questions
and reduces "right answer, wrong mechanism". Metric: share of executed questions that link to ≥ 2
hypotheses with opposite expected outcomes; mechanism-fidelity score judged separately from result
correctness; human label distribution. Design: A/B v3 tree vs hypothesis tree on mechanism questions
(e.g. Campeche warm anomaly, Q07–Q24 subset).

**RQ3 — Off-policy evaluation of research search.**
Question: can propensity-logged candidate snapshots predict live outcomes, and how much randomized
exploration is needed? Metric: rank correlation between offline estimate and paired live result;
exploration cost. Generalizes beyond OceanX.

**RQ4 — Can proxy scorers predict human labels (direction evaluation)?**
Candidates: Coordinator model, a second model family, Jev. Metric: ranking accuracy and calibration
(Brier score) against frozen held-out labels. Relates to SoundnessBench's finding that frontier models
are over-optimistic direction evaluators.

**RQ5 — Frame lock-in and productive abandonment.**
Questions: are closed branches later vindicated? Does cross-task policy learning narrow tree shape?
Metrics: closed-branch vindication rate; tree-shape diversity across tasks over policy versions.

## 4. Modification boundary

The meta-agent may change **how OceanX chooses what to research**. It may never change **how that
choice is judged** or **what is recorded about it**. It only proposes; a human merges.

| Meta-agent may propose changes to | Meta-agent may never modify |
|---|---|
| Candidate ranking rules / features / weights (policy object) | Acceptance criteria, held-out tasks, budgets, failure limits |
| Budget allocation across frontier nodes (parallelism, order) | Human labels and label definitions |
| Diversity-trigger thresholds (conflict / uncertainty) | Logging, telemetry, event schema, cost attribution |
| Selection-guidance text split out of `OCEAN_EXPLORATION_POLICY` | Replay/evaluation harness; randomized-exploration budget |
| Later: expansion and stopping rules (live-run evaluation only) | Tree validation rules (e.g. no completion without a report) |
| Phase 4: proxy-scorer features (validated on frozen labels only) | Sandbox, permissions, Expert call limits (60/48), read-only data |
| | Skills, Expert prompts, its own instructions |

Enforcement: policy files live in a directory the meta-agent can write; everything in the right column
is read-only to it (filesystem permissions, as with `/skills/`), and acceptance runs in a harness it
cannot invoke with modified code.

## 5. Architecture

### 5.1 Layers

| Layer | Contents | Seen by model |
|---|---|---|
| Canonical store (`workspace.sqlite3`) | nodes, attempts, links, events — one transaction per mutation | no |
| Export | `research_tree.json`, per-task JSONL (derived) | no |
| Coordinator view | compact text rendering (§5.5) | yes |
| Improvement data | cost, outcomes, labels, policy version, selection propensities | never |

### 5.2 Data model (tree schema v4)

**Node**: `id, parent, kind (question | hypothesis), text, why_it_matters, relation, dependencies,
origin, branch_key, status, close_reason`.

- Only `kind=question` (question/test) nodes can be selected, enter `frontier()`, and be delegated.
- `kind=hypothesis` is a non-delegable claim with `verdict` (`supported | refuted | unresolved`) set
  only by the Coordinator; every verdict change is an event.
- Evidence: directed typed links question → hypothesis, `supports | refutes | inconclusive` + note.
  Existing link types remain for question ↔ question.

**Attempt** (replaces single `result`): `delegation_id, attempt_id, node_id, expert_role, agent_key,
summary, decision_limit, report_ref, output_refs[], status, started_at, ended_at`.

### 5.3 Structured delegation

New OceanX tool `delegate_question(node_id, subagent_type, description)` wrapping native `task`.
It validates the node is on the frontier, issues `delegation_id/attempt_id`, and passes them via
config into the Expert graph. IDs propagate to `AgentRun` (`research/services.py`), model-call
telemetry (`research/metering.py` → `model_call_observations`), `code_executions`, and task-result
records. Regex binding in `graphs.py` is removed. The tool description stays as close as possible to
native `task` to avoid shifting Coordinator behaviour.

### 5.4 Events, outcomes, labels

- Event per mutation: `task_id, node_id, tree_revision, policy_version, ts, type, reason`
  (reason required on select / complete / close / verdict / decline-to-explore).
- Selection event stores the candidate set with the policy's ranking and selection probability.
- Post-task outcomes per node/attempt: tokens, calls, code runs, wall time, cited in final report,
  spawned children, triggered reopen/conflict.
- Human labels: top-level branches, finally adopted nodes, random sample of closed nodes;
  values `decision-changing | informative-but-not-decisive | misleading-or-wasteful`.
  Captured in the desktop tree panel.

### 5.5 Coordinator view

- One line per node; `why` only for live candidates; deps / relation / close reason only if meaningful.
- Completed question: Result + one-line `decision_limit` + Further analysis.
- Hypothesis: claim + verdict + supporting/refuting node IDs. Finished subtrees fold to one line.
- Tool response: `revision + changed nodes + full frontier + all live candidates`; automatic full compact
  view on revision gap, after summarization, or on request.
- Introduced only through A/B against the v3 view.

## 6. Policy object

Versioned, content-addressed directory (like Skill snapshots), e.g. `policies/<sha>/`:
`ranking.yaml` (features, weights, tie-breaks), `budget.yaml` (parallelism, per-round allocation),
`diversity.yaml` (trigger thresholds), `guidance.md` (selection text injected into the Coordinator
prompt). The active version is recorded on every event. v0 = today's behaviour, extracted without change.

Ranking features available from the store: node depth, relation, number of hypotheses a question
discriminates, parent decision_limit, sibling results, estimated cost from similar past nodes,
Coordinator's own priority. The Coordinator still makes the final select; the policy supplies an
ordered, annotated candidate list.

## 7. Meta-agent loop

1. **Input:** finished tasks' stores (trees, attempts, events, outcomes, labels), current policy,
   previous proposals with results.
2. **Output:** a policy diff + rationale + predicted effect, as a pull request / proposal file.
3. **Screen:** offline replay on candidate snapshots — only ranking among executed candidates,
   importance-weighted with logged propensities.
4. **Accept:** paired live runs under the frozen harness; human reviews metrics and merges.
5. **Archive:** every proposal (accepted or rejected) with scores, to avoid re-proposing failures.

The meta-agent runs offline, never inside a research task, and uses a different model family from the
Coordinator where possible.

## 8. Evaluation design

- **Frozen acceptance (gate before Phase 3):** held-out task set, token/time budgets, failure-rate
  ceiling, label definitions, task-level quality check (human review of final answers on held-out
  tasks; numerical oracles where available). Stored outside the meta-agent's reach.
- **Behavioural probes (Phase 2):** injected conflicting evidence → correct reopen/verdict change;
  no conflict → no spurious reopen; cheap first-delegation probe for delegation-tool changes.
- **Paired live runs:** same query, data, model, budget; randomize order; report per-task deltas,
  not just means; small N means effects must be large to count.
- **Randomized exploration:** a fixed small share of selections picks a lower-ranked candidate;
  size set by human, logged with propensity.
- **Statistics caveat:** single runs prove nothing (as already noted in Campeche monitoring);
  pre-register metric and N before each comparison.

## 9. Phases

**Phase 1 — Record (no behaviour or context change).** ~2–3 weeks (rough)
Work: tree tables in `backend/schema.sql` + store APIs; `ResearchTree` backed by SQLite with JSON
export; attempts; events with reasons; `delegate_question` wrapper; ID propagation to AgentRun /
metering / code executions / results; outcome computation at task end; policy v0 extracted.
Tests: schema and transactions (crash between tree and event impossible), binding robustness,
attribution joins, v3 view unchanged, first-delegation probe unchanged.
Exit: one Campeche run with complete, joinable attempts/events/costs; no behaviour regression.

**Phase 2 — Representation (RQ2).** ~2–3 weeks
Work: hypothesis nodes, directed evidence links, verdict events; "propose or reconsider a distinct
mechanism each round, may decline with reason"; conflict-triggered diversity; compact view;
label UI in desktop.
Tests: probes in §8; A/B compact vs v3 view on the same tasks.
Exit: probes pass; compact view non-inferior; RQ2 A/B run on ≥ 3 mechanism questions with labels.

**Gate — Freeze acceptance.** Define held-out tasks, budgets, failure limits, N for RQ1, label
protocol; freeze and move outside meta-agent reach.

**Phase 3 — Ranking and budget policy (RQ1, RQ3, RQ5).** ~4+ weeks, label-limited
Work: policy object active in selection; randomized exploration; offline replay harness;
meta-agent proposal loop; paired live-run harness.
Exit: one policy version that beats v0 on RQ1 metrics in paired runs, human-merged — or a documented
negative result that stops Phases 3b/4.
Phase 3b (later): expansion and stopping rules, live-run evaluation only.

**Phase 4 — Proxy scorers (RQ4).** After enough labels
Compare Coordinator model, second model family, Jev as scorers of candidate value against frozen
held-out labels. Meta-agent may propose features; validation only on frozen labels.

## 10. Risks and guards

| Risk | Guard |
|---|---|
| Replay mistaken for full-policy evaluation | replay only ranks executed candidates; acceptance by live runs |
| Evaluator drift via self-edited metrics | §4 boundary; frozen acceptance; read-only enforcement |
| Selection bias (unpicked candidates unlabelled) | propensity logging + randomized exploration |
| Goodhart on `cited_in_final` | weak signal only; human labels are ground truth |
| Forced exploration / manufactured reopens | decline-with-reason; conflict-triggered diversity; probe-based exits |
| Tree and log diverge on crash | SQLite canonical, single transaction; JSON export only |
| Same-model self-confirmation | meta-agent and later Discussion Partner on a second model family |
| Delegation wrapper shifts Coordinator behaviour | mirror native `task` description; first-delegation probe |
| Label burden too high | label only top-level, adopted, and sampled closed nodes |
| Policy lock-in across tasks | RQ5 diversity tracking; archive of rejected proposals |

## 11. Decisions so far

- Tree = trajectory carrier; policy = improved object (Codex).
- Hypotheses non-delegable; evidence via directed typed links; verdict history kept (Codex).
- `attempts[]` replace single `result` (Codex).
- OceanX delegation wrapper rather than patching DeepAgents (Codex).
- Keep a one-line limitation in the view; delta + full frontier, not pure diff (Codex).
- SQLite canonical; tree also moves into SQLite for atomicity (Claude).
- Propensity logging + randomized exploration (Claude).
- Evaluator freeze is a gate before Phase 3, not a blocker for Phases 1–2 (Claude, per owner priority).
- Jev evaluated only in Phase 4 as one proxy scorer among several.

## 12. Open questions

1. Share of selections given to randomized exploration.
2. Minimum label volume and N of paired runs before RQ1 is decidable.
3. Move the Discussion Partner to a second model family in Phase 2 or later?
4. Should the Coordinator see the policy's ranking scores, or only the ordered list (anchoring risk)?
5. Where policies live: in the repo (reviewed via PR) or in the workspace store?
