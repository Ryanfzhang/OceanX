# OceanX native-task architecture

This is the current implementation boundary. Earlier scheduler, work-order, review-loop,
result-summary and visualization-agent designs are not compatibility modes.

## One execution system

Desktop and headless clients launch the same local LangGraph Agent Server. The Coordinator is one
checkpointed DeepAgent run. It delegates with DeepAgents' synchronous native `task` tool; the child
finishes before the tool returns its compact receipt to that same Coordinator run. OceanX does not
enqueue a callback, resume a second Coordinator run, mirror child lifecycle in SQLite, or wrap the
native tool in another scheduler.

Each task description contains one scientific question, why its answer matters, its Research Tree
node when applicable and relevant evidence paths. It does not prescribe an analysis or figure
checklist. Independent nodes on the ready frontier can be emitted as parallel task calls in one
Coordinator turn; the research policy decides whether deeper ready nodes wait for shallower ones.
A dependent node waits for its evidence dependency.

Native task model contexts are isolated. Questions under the same root tree branch share one
backend-assigned working directory and persistent Python kernel so durable files and in-memory
arrays can be reused. Independent roots remain isolated. Experts never read another agent's private
conversation history; they receive explicit evidence paths instead.

## Research Tree

The tree is a scientific decision document, not an execution state machine. A node records:

- its question and why the answer matters;
- parent, dependency and relation to nearby questions;
- the evidence or report that motivated it;
- candidate, selected, completed, closed or failed scientific status;
- the latest report observation and cross-links such as support, refute, conflict or dependency;
- optionally, competing-mechanism hypotheses (claims, never delegated) with Coordinator verdicts.

The Coordinator owns Observe, Ideate and Select. It may deepen a completed branch, open a sibling
alternative, or add a new root direction. Candidate directions are nodes, not a second candidate
queue. The tree never starts, resumes, cancels or monitors an agent. A closed or failed parent blocks
its descendants until the Coordinator explicitly reopens it.

The tree is stored per task in `research_tree.sqlite3` together with an append-only decision log,
every Expert attempt, per-node outcomes (tokens, code runs, citation) and labels; the JSON file is an
export. None of that log is shown to a model. The backend only saves and maintains the tree. An
Expert's numbered Further analysis items (at most three) are saved as proposals such as `B1.2#1`;
they become nodes only when the Coordinator adds one with `from_proposal`. The Coordinator makes
every decision, binds each `task` call to a node with an optional `node_id`, and writes the final
Research Tree section. Whether hypothesis nodes are enabled, the frontier mode and extra Coordinator
guidance come from a bundled research policy (`resources/policies/`, default `v0-coordinator-bfs`).
Policy comparison, research memory digests and human-approved lessons are described in
`docs/research-policy-operations.md`.

## Expert output and handoff

Every Expert writes one backend-assigned `report.md`. It begins with a short `## Summary` containing
the core result, the main limitation or unresolved alternative and the most consequential next
question, if one exists. The remaining report structure is the Expert's choice.

The native task receipt contains only that Summary, `report.md` path, saved `.nc` paths and the tree
node identifier. The Coordinator normally decides from the Summary and opens the full report only
when synthesis or the next scientific choice needs more evidence. Report completion automatically
observes the referenced tree node; the model does not repeat that update.

Analysis Experts inspect attached data themselves. There is no Data Expert. The Literature &
Reproduction Expert handles literature and explicitly requested acquisition. The Scientific
Discussion Partner is read-only and can challenge a Coordinator interpretation on demand. There is
no automatic Reviewer or author/reviewer loop.

## Results and visualization

Experts persist ordinary reusable arrays as ordinary data files. A user-facing figure is declared
explicitly with `oceanx.scientific_view.ScientificFigure`: the Expert supplies the computed arrays,
axes, panels, layers and scientific scales, and `figure.save()` writes one self-describing NetCDF.
The Workbench supplies good default styling and interaction unless the Expert deliberately overrides
a supported style field. There is no Visualization Expert, no scientific template layer and no
separate figure specification file. Ordinary NetCDF files are never promoted to UI results.

When a configured Expert model supports vision, it may inspect the generated preview only when the
image itself is scientific evidence needed for reasoning, such as a spatial pattern. Preview review,
visual warnings and a post-save repair phase are not part of figure delivery.

## Tools and Skills

Coordinator and executing Experts use DeepAgents' native filesystem tools. Executing Experts also
use the native execution tool backed by OceanX's sandbox and persistent kernel. Attached sources and
other agents' evidence are read-only; each branch workspace is writable. The Discussion Partner has
only read-only filesystem tools.

Method Skills are role-scoped, read-only and loaded through DeepAgents' native Skills mechanism only
when useful. They explain how to perform ocean, statistical or literature methods; they never encode
Coordinator delegation rules. Runtime runs do not rewrite Skills from accumulated experience.

## Reliability and limits

Provider retry occurs around the failed model call, so Python and filesystem tools are not replayed.
Retryable connection failures are recorded but do not consume the Expert call allowance. Each Expert
task has a 60-call execution ceiling, enters an evidence-read/report-write wind-down inside the
same DeepAgents run at 48 calls (analysis tools requested after that are refused without running),
and reserves a final no-tool delivery call. An Expert that ends without report.md hands back an
explicit no-report receipt, never the raw text of that final call. Repeating the same
normalized execution failure three times also triggers
handoff. These are liveness boundaries, not scientific acceptance rules or a whole-project budget.

DeepAgents owns conversation checkpointing and native summarization. OceanX does not maintain a
second context summary, result summary, team work record, work-order object or async-task table.
The product database stores final product state, file/provenance records, usage/timing facts and a
compact UI projection only.

## Validation

Engineering validation covers synchronous native task return, same-run Coordinator continuation,
canonical report creation, tree observation, fixed root-branch workspaces, result API validation,
deterministic previews, provider retry, cancellation and desktop delivery. Paid-model research
quality, latency and token use remain empirical evaluation questions rather than architecture claims.
