# Research-policy self-improvement — implementation and operator guide

Implements `docs/research-tree-rsi-plan.md` (v3, simplified 2026-09-30; lessons and tools revised
2026-10-02). The improvement loop is bounded: a meta-agent maintains lessons and tools inside the places
the skills reserve for them, code enforces the rules, every change is logged, and the owner can mark any
item right or wrong. The research policy itself changes only by a reviewed code change.

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
- **Meta-agent**: runs outside tasks, at most once a day after a research task (or on request). It
  reads the saved records of finished tasks and the skills that take lessons, then keeps, revises,
  retires and adds lessons, and writes helper functions (tools) for code that Experts wrote again and
  again. It writes no prompt and changes nothing outside the marked regions of the skills.

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

OceanX runs `v2-nested` (`DEFAULT_POLICY`). `OCEANX_RESEARCH_POLICY` selects another bundled policy
for an experiment arm or a paired run; the desktop has no policy switch. A new policy, or a new
default, is a code change reviewed like any other, then compared with paired runs.

## Modules (`src/oceanx/research/`)

| Module | Role |
|---|---|
| `tree_store.py` | Per-task `research_tree.sqlite3`: tree, events, attempts, outcomes, labels; one transaction per mutation |
| `tree.py` | Schema v4: questions, hypotheses, verdicts, evidence links, `decline`, Expert proposals and `from_proposal` adoption |
| `tree_view.py` | Compact text view: one line per node, Result/Limit/proposals, folded finished branches, deltas, 40-node cap |
| `tree_tools.py` | `update_research_tree` (always compact text; hypothesis actions only if the policy enables them) |
| `delegation.py` | `node_id` on the native `task` tool, delegation/attempt IDs, `delegated` events |
| `policy.py` | Load, validate and select bundled policies |
| `outcomes.py` | Per-node cost, code runs, citation, children, proposals made/adopted, reopen/conflict, skills opened; the Coordinator's own calls count on the root |
| `labels.py` | Auto and judge labels, the small human review set, judge–human agreement |
| `memory.py` | Per-task digests (outline, decision history, outcomes, labels), process measures of a finished tree (`run_measures`), weekly consolidation and archiving |
| `referee.py` | An independent reading of each finished task's final answer (what the question asks for and the answer lacks, conclusions stronger than their support), kept as evidence for the lesson review |
| `lessons.py` | The meta-agent's review of each skill's lessons (keep, revise, retire, add), the rules code enforces, the owner's marks and the change log |
| `toolbook.py` | The helper functions a task mounts, the call counter, usage statistics, and tools learned from repeated code (static check, sandboxed test, independent review) |
| `../skill_regions.py` | The marked regions of a SKILL.md (`oceanx:lessons`, `oceanx:tools`) and how they are filled |
| `metering.py` | One record per model call: tokens, node attribution, and which skills the call opened |
| `acceptance.py` + `resources/evals/research_policy_acceptance.yaml` | Frozen criteria with a hash lock |
| `paired_runs.py` | Paired live runs and frozen-criteria evaluation |
| `review.py`, `cli.py` | The project's library as the desktop and the CLI use it (update, mark, overview, frozen snapshots) and `ocean research ...` commands |

## Labels without rating everything

When a task finishes, log rules label each executed node (`auto`). `ocean research judge-labels`
adds a leave-one-out model judgement (`judge`). The root is never labelled: it holds the answer and
is not a branch. A node whose proposed follow-ups were adopted counts as having moved the tree,
wherever those follow-ups were placed. The owner may label nodes with `ocean research label`; this is
optional, and the desktop no longer asks for it. Effective label: human > judge > auto.
`ocean research judge-agreement --runs <dirs>` reports how often the judge matches the owner.

## Lessons, tools and memory

- **Digests.** A finished task is summarised into `.oceanx/research/digests/<task_key>.json`
  (tens of KB). Per question it keeps the wording, why it was added, who proposed it, when it was
  created, every delegation with its start and whether it reported, the result and its stated
  limits, the follow-ups it proposed and which question adopted each, cost, citation and label.
  It also keeps which lessons the task was shown and which it named, which helper functions it
  could call and how often it called each. The meta-agent reads digests only. Digests written
  before this history was kept stay readable and are rebuilt while their raw store exists.
- **Readings.** A digest cannot show what the final answer left out or overstated: the agents
  that wrote the answer also wrote the records. So before a review, a model that saw none of the
  work reads each newly finished task's research question and final answer
  (`.oceanx/research/referee/<task_key>.json`). One call lists what the question asks for, from
  the question alone and once per question; a second reads the answer against that list and
  notes what is missing or partial, conclusions stronger than the support the answer gives, and
  superseded numbers still used. A reading is evidence, not a rule: in a hand check of five
  answers about one finding in three was wrong, so a lesson still needs the same kind of finding
  in tasks on 3 different questions. At most 20 tasks are read in one update; a call that fails
  twice or does not return in 300 s leaves its task for the next update.
- **Marked regions.** A skill reserves a place for what the project learns:

  ```text
  <!-- oceanx:lessons max=4 for="coordinator" about="which follow-ups were worth asking ..." -->
  <!-- /oceanx:lessons -->
  <!-- oceanx:tools max=40 -->
  <!-- /oceanx:tools -->
  ```

  `max` is how many items a task is shown in the region, `about` what belongs there, and `for` whose records
  the meta-agent reads. The author of the skill decides both; the meta-agent can only fill the
  region. Six skills take lessons: `research-trajectory-planning` (Coordinator, 4),
  `ocean-analysis-design` (6), `ocean-physical-consistency-review` (6), `ocean-dataset-diagnosis` (4),
  `hypothesis-experiment-design` (3) and `claim-grounded-writing` (3). `xarray-array-ops` has the
  tools region. A skill without a region takes nothing, and no marker ever reaches a reader.
- **Runtime.** Each task's skill library is generated from the packaged skills, the lessons and
  the tools; the packaged files are never modified, so two runs of one OceanX version can differ in
  the library alone. Lessons are written only in research mode. A lesson is one line under a
  heading that marks it as learned, with its condition and its id. The tools region lists each
  helper function with its signature and the first paragraph of its docstring, written from the
  code. The version of the lessons and tools a task ran with is appended to the policy version on
  every tree event.
- **Reading the skills.** What was learned reaches an agent only by its opening the skill, and
  an agent opens a skill only when it is told to: in 34 benchmark runs up to 2026-10-08 Experts
  opened the skills that hold lessons in about 2% of their questions, and the helper list in 3
  of 468. So a research task names to each reader the skills that now carry something learned
  (`ProjectResearch.learned_in`): a data Expert is told, before its first calculation, to read
  in one step every skill of its role that holds a lesson, and `xarray-array-ops` when it lists a
  learned function; the Coordinator reads `claim-grounded-writing` before the final answer when it
  holds a lesson (its planning skill is always named). A model call that only reads files under
  `/skills` is not counted in an Expert's call budget, up to six such calls a run, so reading
  what was learned takes nothing from the analysis. A project that has learned nothing names no
  skill.
- **Upkeep.** After a research request the backend refreshes digests and call counts (no model
  call). At most once a day it also lets the meta-agent review; **Review → Update now** does the
  same on request. Nothing runs when `OCEANX_LIBRARY_FROZEN` is set (experiment arms).
- **Lessons.** One model call per skill that takes lessons. The call gets the skill as its
  readers get it, what the reader is told elsewhere, the lessons other skills carry (one idea
  belongs in one skill), the lessons the owner marked wrong, and the
  role's view of the records (about 200k characters, one run of every question before any repeat),
  each with the reading of its final answer where one exists.
  It judges every current lesson (keep, revise, retire) and may add at most 2. Code enforces:
  - a new lesson needs supporting tasks from at least 3 different questions (with fewer, a skill
    without lessons is not reviewed at all);
  - a lesson contradicted by as many questions as support it is retired, whatever the model said;
  - the project keeps every lesson that passed; a task is shown at most the region's `max` of a
    skill's lessons, so the library can go on growing while a reader's page stays short;
  - ≤40 words with no task keys or node IDs, and an applies-when of ≤25 words.

  What passes takes effect at once. The order within a skill is: lessons the owner marked right,
  then best supported (questions for minus questions against), then most recently confirmed.
- **Tools.** A tool is a function of `oceanx_array_ops.py`, called as `ao.<name>`. The Python
  kernel has `ao` imported; a script imports it itself. The mounted module is the packaged file,
  the project's learned functions and a counter that logs each call analysis code makes
  (`tool-calls.log` in the execution folder; a helper called by another helper is not counted).
  - *Elimination by use.* A function no task called for 20 tasks in a row leaves the list. A
    packaged function stays importable; a learned one is retired. A new function is listed ahead
    of the others for its first 10 tasks.
  - *Learning.* Experts name one calculation differently from task to task (an area mean was
    `amean`, `wm`, `am` and `gw` within a single task), so repeated code is collected per task: a
    function the task defined at least twice, or whose name another task also used, at most 8 per
    task. The meta-agent matches these entries across tasks by what they compute and may turn
    them into at most 3 general functions per review, each with a test and each replacing entries
    from tasks on at least 3 different questions. A function is mounted only if all of these
    pass: a static check (one
    pure function with a docstring, ≤60 lines, imports limited to numpy, xarray, pandas, scipy, gsw
    and math, no file, network, printing or global state), its test run in the sandbox, and a
    review by a second model call that looks for a numerical or scientific error.
- **The owner.** **Review** in the desktop lists every lesson and tool with its evidence, how
  often it was shown, named or called, and the latest changes. Two buttons mark an item right (it
  stays whatever later records say; a retired one comes back) or wrong (it goes and is not
  proposed again). The same from the shell: `ocean research library --project <dir>` and
  `ocean research mark --project <dir> --kind lesson|tool --id <id> --right|--wrong --reviewer <you>`.
  Every change is logged with its reason in `lessons/changes.jsonl` and `tools/changes.jsonl`;
  `lessons/skills/` and `tools/learned/` hold readable exports that tasks do not load.
- **Cleanup.** The same upkeep gzips raw stores of finished tasks older than 30 days.
- **Meta model.** `role_profiles.meta` in model settings if present, else the Expert profile.

## Operator workflow

1. Run tasks normally, or with `OCEANX_RESEARCH_POLICY=v1-hypotheses`.
2. Optionally label nodes (`ocean research label --tree ... --node B1.2
   --label decision-changing --labeler <you>`) and run `judge-labels`.
3. Edit `research_policy_acceptance.yaml` (all values are drafts) and
   `ocean research freeze-acceptance --owner <you>`.
4. `ocean research pairs --queries <held_out.jsonl> --output <dir> --policy-a v0-coordinator-bfs
   --policy-b v1-hypotheses`, rate each case once (`{case, better: A|B|same}` JSONL), then
   `ocean research evaluate-pairs --output <dir> --quality <file>`.
5. If it passes, change `DEFAULT_POLICY` in a reviewed commit.

## Known limitations

- Acceptance values are placeholders and there is no held-out query set yet (owner decisions).
- Expansion and stopping are Coordinator judgement plus policy guidance; there is no rule engine
  or per-branch budget beyond the Expert call limit.
- Parked until paired runs justify them: suggested candidate order, logged propensities,
  randomised exploration, offline replay, meta-model policy proposals, proxy scorers.

## Verification status

Covered by tests (`tests/test_oceanx`, no model): region parsing and filling, the lesson rules, the
owner's marks, the call counter on the kernel path and the script path, usage statistics and
elimination, the static check, a real sandboxed test run, admission with a stand-in reviewer, the
library requests through the backend router, and frozen snapshots.

Not yet run: a live meta-agent review with a real model, a live task that calls a learned tool, and
the desktop dialog in a running app. The reading of final answers has unit tests only; the two prompts
it uses now were written after the trial of 2026-10-09 and have not been run with a model.
