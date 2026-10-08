# Evaluation: how runs are made, stored and judged

One experiment answers two questions with one set of test runs:

1. **Transfer of what was learned:** does the library learned on one evolution set improve research on the
   test suite? The library is the lessons written into the skills and the helper functions (tools) that
   analysis code can call.
2. **A second round:** does the library revised after a second evolution set, itself run with the first
   library, improve it further?

Each question is answered twice: by the judged score of the answer, and by a measure of how
the research went. Lessons are about tree decisions and analysis choices, and tools are about code that
fails or is written again, so an unchanged run with a better-worded answer would not count as learning.

The arms differ in lessons and tools together. The experiment says whether the library helps. Which half
helped can only be read from the process measures (lessons named, helper calls, failed code runs).

## Run settings and comparison limits

- OceanX benchmark runs use `OCEANX_FIGURE_DELIVERY=static`: when the researcher requested a
  visual, or a figure is necessary scientific evidence, Experts save it as an ordinary PNG image.
  OceanX's interactive plotting interface is not exposed to the models; the desktop's interactive
  mode is unchanged. Reading one of these images gives the model a JPEG preview bounded to 1024 px
  on its longest edge, while the full-resolution result remains on disk. A preview that cannot be
  made (a missing or corrupt file) is an ordinary error message, as for any other file. In these runs
  the Coordinator also cannot re-delegate a node that already has a result just to publish a figure
  the researcher's question did not ask for; the desktop keeps the prompt rule alone.
- OceanX benchmark runs have one skill that the desktop does not have:
  `benchmarking/skills/scientific-figure-style`, which says how to choose and draw a figure saved as an
  image file and names no plotting interface. The two data Experts get it, and one sentence added to their
  policy points to it. `benchmark_agent_server.py` installs both in the benchmark's own Agent Server
  process; OceanX's code and packaged skills are unchanged. `arm.json` and each attempt's
  `model_protocol.json` list it under `benchmark_skills`.
- Each arm's agent is told to report what it has before it runs out. OceanX: the research time budget
  below. Claude Code: its prompt says the run is one turn and nothing resumes after the final response.
  Finch: its prompt states the runner's tools, inputs and limits, and the worker says when 10, 5, 3, 2 and
  1 steps remain. An attempt that still ends without a final answer is judged on what it kept
  (`evaluation/CODEX_JUDGE.md`); no substitute answer is written for it.
- The Expert's last, tool-free delivery call may issue an extra provider request if its first
  reply contains tool markers rather than a report. Context compaction requests are counted
  separately as summary calls. Both appear in the per-call ledger and belong in time and token totals;
  the Expert call limit (60 on the desktop; `BENCH_OCEANX_EXPERT_CALL_LIMIT`, 10 to 60, in benchmark runs
  and recorded in `arm.json`) is not an exact count of all provider requests. At a lower limit the report
  checkpoint falls at half of it and the wind-down at four fifths, as at 30 and 48 of 60.
- A model reply whose tool-call arguments are valid JSON plus stray closing brackets is repaired and the tool runs;
  a reply with no runnable tool call is asked for once more. Before this, one such reply ended the Coordinator and
  failed the whole question (Q07 of the 40-call batch, after 21 seconds).
- `BENCH_OCEANX_MAX_PARALLEL_EXPERTS=3`: data Experts that may work at once; a Search Expert has its own slot
  (`BENCH_OCEANX_MAX_PARALLEL_SEARCH_EXPERTS=1`), so up to four Experts run together. Watch memory in the first run
  with this setting; `arm.json` records both. The desktop has the same setting under Settings, Research runtime
  (1 to 4, default 2); it travels with each request (`session.submit.max_parallel_experts`).
- Experts work in the background of the Coordinator's run. A `task` call returns when the next running Expert
  finishes, not when the slowest of its batch has, and `await_experts` is how the Coordinator waits: for the next
  one, for named nodes, or for all. The Coordinator decides whether to continue one node's own line at once or to
  wait for several results that a new question depends on; it cannot finish while an Expert is running. Each
  Expert's own `task` tool run still ends with its own receipt. Elapsed times of runs made before this change
  (every batch waited for its slowest Expert) are not comparable with later ones.
- Before the final answer the Coordinator reads every returned node's complete Result and Evidence and limitations
  with `update_research_tree(changes=[], view='results')`. The ordinary tree view clips each Result to 320 characters
  and each limit to one sentence, which hid a correction in Q08 of the 40-call batch (0.879 to 0.778 m/s) from the final
  answer. Experts begin a Result that changes an earlier node's number with `Corrects B1.x: ...`.
- Only the user's own question authorizes dataset acquisition. The Coordinator and Expert prompts say so;
  an assignment that says an Expert "is authorized" is not a request (Q08 of the 40-call batch downloaded WOA18
  and Argo on the Coordinator's own authorization and used them in the answer).
- `BENCH_TIMEOUT_SECONDS` supplies OceanX's research budget: after 75% no new Expert assignment
  starts. This is a run setting that changes Coordinator behavior, not merely an external timeout;
  disclose it alongside the commit, model, delivery mode and other run settings.
- Finch-local has no literature-search agent; it is not the full Robin system.
  Claude Code's search depends on its configured tools. OceanX consults Search Expert on demand
  for definitions, methods or published mechanisms the data context does not settle. These search
  capabilities are not identical; report them when comparing methods. Search Expert has one
  independent slot by default and therefore does not occupy either data-analysis slot.
- Failure categories describe observed messages, not blame. A read-only refusal may correctly
  protect another node's evidence, and a timeout may reflect slow computation. Inspect logs before
  assigning a cause; collection completeness and a successful run do not establish scientific correctness.

## The process

| Phase | What happens | Who |
|---|---|---|
| 0. Prepare | Data downloaded and staged; references computed and rubrics frozen | Codex; owner signs off |
| 1. Evolve, round 1 | Evolution set A (E01-E12) runs with nothing learned; the model judge labels the tree nodes; the meta-agent reviews the runs once; the resulting lessons and tools are frozen as L1 | Codex; the owner may look and mark |
| 2. Evolve, round 2 | Evolution set B (E13-E24) runs with L1; nodes labelled; the meta-agent keeps, revises, retires and adds; the result is frozen as L2 | Codex; the owner may look and mark |
| 3. Test | Pre-registration frozen. Test suite (Q01-Q30) runs in three arms, nothing learned | Codex |
| 4. Judge | Outputs blinded; Codex scores every attempt against the frozen rubric; the model judge labels the test trees | Codex |
| 5. Decide | Paired comparisons of scores and of the process metric; pre-registered rules applied; report written | Codex; owner decides |

Arms (fixed in the pre-registration):

| Arm | Library | Used for |
|---|---|---|
| B | none (L0): the packaged skills and helper functions | control for L1 |
| C1 | frozen snapshot L1 | treatment for L1; control for L2 |
| C2 | frozen snapshot L2 | treatment for L2 |

Every arm runs the default research policy, `v2-nested`. The policy is fixed, so the experiment does not
compare policies: the earlier arm A (`v0-coordinator-bfs`) is no longer run, and the other arms keep their
letters.

## Storage

```text
$RUNS_ROOT/<experiment>/
  evolution/A/r<k>/arm-E1/<E01..E12>/attempt-*/   round 1: set A, nothing learned (arm.json at arm level)
  evolution/B/r<k>/arm-E2/<E13..E24>/attempt-*/   round 2: set B, library L1
  evolution/.oceanx/research/                     digests, lessons, tools and their change logs, of both rounds
  test/r<k>/arm-B|arm-C1|arm-C2/<Q01..Q30>/attempt-*/
$EVAL_ROOT/<experiment>/
  preregistration.yaml (+ .sha256)             frozen before the test phase
  rubrics/<task>.json                          frozen rubrics (template + reference values + answer key)
  references/<task>/                           evaluator scripts and outputs (private-data derived)
  blind/<blind_id>/                            what the judge reads
  blind_map.json                               blind ID -> arm, run; the judge opens it only after scoring
  scores/<blind_id>.json                       Codex score files
  report/                                      summary.json, report.md, process.json and process.md
$EVAL_ROOT/library/L1/     frozen after round 1: lessons.json, tools.json, snapshot.json (version and
                           SHA-256), lessons-changes.jsonl and tools-changes.jsonl (what changed and why)
$EVAL_ROOT/library/L2/     frozen after round 2, same files
```

`arm.json` records arm, policy, the version and SHA-256 of the library snapshot, git commit (and whether the
tree was dirty), OceanX version, package versions and the parallel-Expert limit. It is written when the arm
folder is first used; `launches.jsonl` beside it has one line per launch (commit, settings, questions).

Launched from a settings file (RUNNING.md), an arm folder is `BENCH_OUTPUT_ROOT/<experiment>/runs/<arm>/`,
with the same `<question>/attempt-*/` folders inside.

### What every attempt keeps

The rubric score is one reading of a run. Everything needed for another reading is kept in the attempt
folder, so a later evaluation needs no new runs.

| Kept | Where in the attempt folder | What it gives |
|---|---|---|
| Query, status and wall time | `query.json`, `result.json` | Time consumed: setup, analysis and total |
| Final answer | `answer.md` | What the judge scores |
| Every agent's files | `workspace/OceanX Tasks/<task>/agents/` | The final report, one `report.md` per answered question, the code, its logs and the outputs |
| Earlier versions of a report | `agents/<agent>/.runtime/report-history/<question>/<attempt>.md` | What each attempt delivered, when a question was asked again and its report rewritten |
| Research tree | `agents/coordinator/research_tree.sqlite3` | Every question, each decision with its time and reason, every attempt, the cost per question and the labels |
| Model-call ledger | `state/workspace.sqlite3`, table `model_call_observations` | Tokens (input, cached input, output), duration, role, question and skills opened for every model call, failed ones included |
| Code runs | `state/workspace.sqlite3`, table `code_executions` | State and duration of every code run |
| Agent conversations, whole | `state/.langgraph_api/.langgraph_checkpoint.*.pckl` | Every message and tool call, in the agent framework's own format; read them with the library versions in `arm.json` |
| Agent conversations, readable part | `agents/<agent>/.runtime/context/conversation_history/session_*.md` | The messages an agent's context dropped when it was compacted, as text. A short conversation has no such file |
| Event stream and logs | `events.jsonl`, `backend.log`, `state/agent-server.log` | What the desktop would have shown, and server diagnostics |
| Arm identity | `arm.json`, `arm_library.json`, `model_protocol.json` | Policy, lessons and tools, commit, package versions and model |
| Skills and helper functions as given | `agents/<agent>/.runtime/skills/*/skills/<skill>/SKILL.md`, `agents/<agent>/.runtime/executions/<run>/code/oceanx_array_ops.py` | What each agent could read and call: the skills with the arm's lessons and tool list written in, and the helper module with the arm's learned functions |
| Helper calls | `agents/<agent>/.runtime/executions/<run>/tool-calls.log`, and `tool_calls` in each code run's record | Which helper functions each code run called |

```bash
python benchmarking/evaluation/evaluate.py inventory --runs <arm folders> --out <report folder>
```

`inventory` writes `run_record.json` and `run_record.md` into every attempt:
- time (total, model calls, code runs) and tokens by role;
- one row per question of the research tree: who answered it, its label, its attempts, its minutes and
  tokens (an attempt that returned no report is counted), the skills its Expert opened, and the path of
  its report;
- every Markdown file by kind, the size of the saved conversations, and the disk use;
- what is missing.

`inventory.md` lists every attempt with these totals. Run it after each phase; a completed attempt with
something missing is a finding to report before any more runs are made.

**An attempt delivers whatever it kept.** A status other than `completed` does not mean an empty hand.
The attempt folder keeps the Expert reports, the notebook, the outputs and the agent's messages; the blind
export copies them (for Claude Code also `partial_answer.md` when there is no `answer.md`); and the judge
scores them (`evaluation/CODEX_JUDGE.md`, "Attempts that end without a final answer"). No substitute
answer is assembled, and no status is changed. Each runner also gives its agent a last stage in which it is
told to report what it has:

- OceanX: the runner sets the research time budget from the case's time limit, so after three quarters of
  it the Coordinator starts no new assignment and is told to write its final report. OceanX itself is not
  changed for the benchmark.
- Claude Code: the prompt says the run is one turn, that nothing resumes after the final response, and to
  report what it has if time is short. A report delivered despite a refused tool call is a completed
  attempt; the refusals stay in `permission_denials`.
- Finch: the prompt states the runner's facts (code runs only through `edit_cell`, there is no shell tool,
  the inputs are visible only to notebook code, the step and replay limits), and the worker tells the agent
  when 10, 5, 3, 2 and 1 steps remain and to submit its answer.

Four rules follow:
- **Keep attempt folders whole.** Do not prune `state/` or `workspace/`: the ledger, the conversations, the
  reports and the code live there.
- **Tokens come from the ledger.** The total OceanX reports when a run ends covers the Coordinator's own
  stream only and is zero in practice, and a failed or timed-out attempt reports none. `blind`, `summarize`
  and `inventory` therefore sum the ledger. Most input tokens are served from the provider's cache, so the
  record keeps cached input separately.
- **Conversations are complete only after the Agent Server stops cleanly.** The framework's periodic write
  is not reliable: the desktop's checkpoint files went 22 hours without one while a two-hour task ran.
  `run_oceanx.py` therefore waits up to two minutes for the backend to stop before it kills it; the backend
  gives its Agent Server 30 seconds. `inventory` reports "agent conversations" as missing when the
  checkpoint files hold almost nothing, and "end of agent conversations" when they were last written
  before the last model call ended. The checkpoints stay in the framework's format; no portable export is
  made.
- **Large scratch arrays are disposable after validated collection.** In one E10 run the 29 files
  over 10 MB were 5.44 of the 5.4 GB in scratch, and the other 126 files, which include every script
  and the tables the reports cite, were 24 MB. `inventory` reports each attempt's disk use and its
  scratch share. What the collector deletes, and when it deletes nothing, is described below.

### OceanX delivery and collection

If a follow-up attempt leaves its question's nonempty `report.md` unchanged, OceanX
delivers that report and its original Summary; a short closing reply is added only to
the Coordinator receipt. The closing reply becomes the report only when no nonempty
report exists, for the Discussion Partner, or when it contains a nonempty `## Summary`.
Without closing prose, the receipt explicitly says so and gives the model-call stop reason.
If an Expert reaches model call 30 without saving a report, analysis tools pause until it writes a
defensible partial `report.md`; it may then continue analysis and update the report. This is a
checkpoint, not a lower replacement for the call limit.
Every Expert is told its call budget in its instructions, and each call after the first ends its last tool
result with a line such as `[Budget: model call 13 of 40; 20 left for analysis, then 8 only to finish the
report.]`. The line is added to that request only and is never saved in the conversation, so the cached
prompt prefix does not change. This applies to the desktop's Experts too.

Every OceanX attempt delivers ordinary images, as the Claude Code and Finch arms do:
`run_oceanx.py` starts the backend with `OCEANX_FIGURE_DELIVERY=static` and records
`figure_delivery` in `arm.json`. No prompt, tool description or skill the OceanX models read
names OceanX's plotting interface. A final figure is an image file (`.png`, `.jpg`, `.jpeg`,
`.svg`, `.pdf`) that an Expert saves under its node's `outputs/` folder; exploratory plots stay
in `scratch/`, and a file name starting with `_` or `.` is a draft. The result store lists
each delivered image as a `file` result (`render_status: "static"`), the Expert receipt lists
them under `Saved figures (cite these paths):`, and the collector copies them into the
figure gallery and rewrites the cited absolute paths to links.

The OceanX runner automatically creates a new `runs/OceanX/collected/collection-*`
folder after the batch. Open its `index.md`, then each attempt's `review.md` for the
answer, figure gallery, registered result data and links to saved reports/code.
The collector reads `outputs.json.task_results`; it does not discover results by
scanning ordinary NetCDF files, run models, rerun analysis, or modify the original answer.
After a completed attempt has a final answer and collection finishes without errors, the collector
deletes the files over 10 MB in every node's `scratch/` folder: the intermediate arrays, which were
99.6% of the 5.4 GB of one E10 run. Scripts, tables and notes under 10 MB stay, because reports cite
them and a recorded command only calls a script by name. `scratch_cleanup.json` lists every file
removed with its size, and the counts and bytes released and kept. Reports, code, registered outputs
and runtime records are never touched. If a final answer or any nested Expert report cites a scratch
folder by its absolute path, nothing is removed and the reason is recorded. If a removal fails part
way, the status is `partial` and the list shows what went. The collector now deletes files:
do not run it on an older run folder whose scratch you still want to inspect. Later inventory still
reports the released byte count from this record.

`summary.json` and each `collection_manifest.json` distinguish runtime status from
collection status. `collection_status=complete` means the available answer and
registered files were collected without errors, **not** scientific correctness or
verified reproducibility. Missing previews, files, checksum mismatches and invalid
indexes are reported explicitly. Notebook availability is a separate field.

When saved per-execution notebooks exist, `execution_record.ipynb` groups their
original cells and outputs by agent. It can include failed attempts and original
server paths; it is **not** a clean, end-to-end `analysis.ipynb`. No missing cells
are invented or repaired. Collection is for review, not an additional scientific
completion step or an automatic increase in benchmark scores.

Existing attempts can be recollected without rerunning them:

```bash
python benchmarking/server/collect_oceanx.py --run /import/home3/share/oceanx-bench/methods-public-r1/runs/OceanX
```

Replace `--run` with the saved OceanX method folder to review. Every collection uses
a new directory and preserves previous attempts and collections. Historical receipt
formats remain readable only when no current task-result index is present.

## Running arms

The commands are in [RUNNING.md](RUNNING.md): section 1 for an arm without a library (B), section 4 for an
arm with one (C1 with L1, C2 with L2). No `--policy` is passed: every arm runs the default, `v2-nested`,
and `arm.json` records it.

- Each repeat is a results folder of its own (another `BENCH_EXPERIMENT`). Run the arms of a repeat at the
  same time on the same questions, so time-dependent effects (provider load, web search results) hit all
  arms equally. With limited memory, run them one after another and keep the order.
- Every arm uses the same per-attempt time limit (`BENCH_TIMEOUT_SECONDS`, three hours by default),
  recorded in the pre-registration. A timed-out attempt scores 0, so a limit that is too short penalises
  the arm that explores more.
- Use the same commit, policy, `benchmarking/.env` model and literature mode (`search_only`) for every arm. No merges
  or setting changes until the test phase ends.
- A failed, timed-out or empty attempt scores 0 and is reported separately. Do not re-run a failed
  attempt for a better score. The runner would let you: with `--resume` (the default) it gives a new
  attempt to every question whose latest attempt did not complete, and `--no-resume` runs completed
  questions again. Which attempts count is fixed in the pre-registration, not by the runner.

### Nothing is learned during benchmarking

- Each attempt starts with empty OceanX state (its own state folder), so no memory, digest, lesson or
  tool carries over between attempts.
- `run_oceanx.py` freezes the library of every attempt (`OCEANX_LIBRARY_FROZEN`): no attempt reviews its
  lessons, learns a tool or counts calls into its library. In the desktop app the same upkeep runs after
  every research task.
- Arms C1 and C2 copy their frozen snapshot into each attempt. The attempt records the SHA-256 of
  `lessons.json` and `tools.json` before and after; `evaluate.py library-check --runs <test folder>` must
  report nothing changed.
- Learning happens only in the evolution project, between rounds, with `research_cli.py consolidate
  --review`. Never run it on a folder that contains test-suite runs: the library must come from evolution
  records only.

## References and frozen rubrics (phase 0)

The rubric in the repository is a template with status `draft`: the expected value and the tolerance of
every finding and answer-key item, and the expected verdict of every candidate cause, wait to be filled
(215 places in the 30 rubrics). Before judging, the evaluator computes each of them from the same inputs
the agents get, fills a copy of the rubric under `$EVAL_ROOT/<experiment>/rubrics/`, and freezes it. The
rules, the file formats and the order of work are in
[evaluation/CODEX_REFERENCES.md](evaluation/CODEX_REFERENCES.md). `evaluate.py rubric-check --rubrics
<folder> --references <folder>` says whether each frozen rubric is ready: every place filled, nothing else
changed from the repository's rubric, the reference work present and unchanged.

Papers still checked from the abstract only: Q01, Q03 and Q06. Before their rubrics are frozen, confirm
each finding, the region, the window and the definitions from the paper (the owner provides the PDF) and
record where in the paper each was confirmed; otherwise the abstract wording stands. Two rubrics name a
detail to confirm first: the transport section of Q03 and the typhoon's passage dates in Q06. For Q05 and
Q06, record whether the CMOMS forcing contains the typhoon; if it does not, "not reproduced" is the valid
reference.

Reference outputs of the CMOMS questions contain numbers derived from CMOMS: they stay in `$EVAL_ROOT` and
are never committed.

## Before the test phase

For a comparison that will be reported:

- **Environment.** `check_setup.py` and `python -m pytest benchmarking/tests` pass on the server, and
  `test_finch_upstream.py` passes in the Finch environment. The working tree is clean; every arm uses that
  commit. No code or setting changes while a method is running.
- **Smoke.** Each method runs one evolution question in an experiment of its own. Check the reports, the
  figures, the token and time records and the conversations (`evaluate.py inventory`). Smoke records do
  not enter the lesson review.
- **References.** Every rubric of the questions to be run is frozen (phase 0).
- **Noise pilot.** One arm, three questions (a paper task, an open problem with an answer key, a
  disagreement question), two repeats each, judged blind. It sets the repeats of the test phase: one if the
  median absolute difference between the repeats is at most 5 points, two if at most 10, three otherwise.
- **Judge calibration.** Three attempts of the pilot are judged twice, in separate sessions, without
  reading the first scores. No criterion may differ by more than one level, and the owner accepts the
  three pairs.
- **Learning pilot,** before the evolution rounds: three questions of set A (E01, E05, E08), one run each,
  labelled and reviewed in a folder of its own. Go on only if the runs finish in time, the Coordinator
  opened its planning skill in at least two of them, the owner finds at least one lesson that is a
  research-tree or analysis decision holding for all three and not already in its skill, and every learned
  tool passed its test in the sandbox. Nothing of the pilot is frozen.
- **Pre-registration.** Copy `experiments/preregistration.example.yaml` (for the comparison of methods,
  `methods.example.yaml`), fill in the commit, the model, the judge, the repeats, the time limit and the
  library paths, and freeze it with `evaluate.py freeze --prereg <file>`. No frozen file changes after
  that, and no rule changes after results are seen.
- **Partial runs** are allowed. Say which questions were left out and why, and do not call the result the
  full suite.
- **While the runs go.** Never prune an attempt folder. If two or more attempts of one arm fail for the
  same infrastructure reason, stop and report. Ask the owner when the cost passes the estimate by half.

Claude Code's tools include host Bash, not a filesystem sandbox; Finch has a network-disabled calculation
sandbox and no literature-search agent. What an agent sees can leave the server through the model provider
in every method: use an approved endpoint for confidential CMOMS data.

## Judging (phase 4)

```bash
python benchmarking/evaluation/evaluate.py blind --runs <every arm folder of the test phase> \
  --out $EVAL_ROOT/<experiment>/blind --map $EVAL_ROOT/<experiment>/blind_map.json
```

Codex then follows `evaluation/CODEX_JUDGE.md` for every blind folder and writes `scores/<blind_id>.json`.
Afterwards:

```bash
python benchmarking/evaluation/evaluate.py validate --scores $EVAL_ROOT/<experiment>/scores
```

## Analysis (phase 5)

```bash
python benchmarking/evaluation/evaluate.py summarize --prereg $EVAL_ROOT/<experiment>/preregistration.yaml \
  --map $EVAL_ROOT/<experiment>/blind_map.json --scores $EVAL_ROOT/<experiment>/scores \
  --out $EVAL_ROOT/<experiment>/report
```

For each comparison, the per-task score difference is averaged over repeats. The report gives the mean
difference over tasks with a 95% bootstrap interval, wins and losses, the reduction in tokens and in time,
and whether the pre-registered rule is met. It also gives the difference by question type (paper verification, open
problem) and by data access (private CMOMS, public). Read these rows before concluding:
- a policy can help open problems and do nothing for paper verification;
- lessons learned on public reanalyses may help public questions more than the unseen CMOMS questions.

The owner receives `report.md`, `process.md` and each repeat's `inventory.md`; for each comparison the
score result and the process result side by side, with the spread between repeats of the control arm; the
five largest per-task differences in each direction, each with a line on why; the failures by arm; and the
total cost. Proposals for a next experiment go in a section of their own.

The rubric total is the main result. `evaluation/ASPECT_SCORES.md` divides it into six indicators for
open problems and six others for paper verification (each made of the judged criteria, counts the judge
records, and for robustness the share of questions delivered at the first attempt), for one six-axis chart
per task type.

### Process measures

The score says how good the answer is. These measures say how the research tree got there. They come
from each attempt's tree store, after the model judge has labelled the test trees:

```bash
find "$RUNS_ROOT/<experiment>/test" -name research_tree.sqlite3 \
  -exec python benchmarking/server/research_cli.py judge-labels --tree {} \;
python benchmarking/evaluation/evaluate.py process --runs <every arm folder of the test phase> \
  --prereg $EVAL_ROOT/<experiment>/preregistration.yaml --out $EVAL_ROOT/<experiment>/report
```

| Measure | What it says |
|---|---|
| Tokens in non-decisive questions (`nondecisive_token_share`) | Share of the Experts' tokens spent on questions that did not change the answer. **The pre-registered process metric; lower is better.** |
| Last decisive result (`last_decisive_fraction`) | When the last decisive question finished, as a share of the run's time. Work after it did not change the answer. |
| Follow-ups adopted | How many of the Experts' proposed follow-ups the Coordinator pursued |
| Attempts without a report | Delegations that returned nothing |
| Skills opened | Whether the Coordinator opened its planning skill, and the share of questions whose Expert opened an analysis skill. A lesson can only act if the skill that holds it was opened. |
| Code runs that failed (`code_failure_share`) | Share of the attempt's code runs that did not succeed. This is what helper functions are meant to lower. |
| Helper calls (`helper_calls`) | Calls the analysis code made to the helper functions. A tool can only act if it is called. |
| Lessons named (`lessons_cited`) | Lessons the agents named in a reason or a report. It is the agents' own word that a lesson changed what they did, so it is counted, not trusted as proof. |

The last two are "n/a" only for runs made before OceanX logged them.

How to read them:
- **With the score.** Fewer non-decisive tokens with a lower score is not an improvement.
- **Against the noise.** The report gives, next to each comparison, the mean spread of the metric between
  repeats of the control arm. A difference smaller than that spread is noise.
- **As a proxy.** "Decisive" is the model judge's label for each question (would the conclusion change
  without it), made without knowing the arm. It uses the offline meta model (DeepSeek Flash by
  default), not a human or the independent rubric judge.
- **Before a null result.** If the skills were rarely opened, the lessons were not tested. If no helper was
  called, the tools were not tested.

## The research policy

A research policy is the set of rules the Coordinator follows for its research tree. OceanX runs
`v2-nested`: each follow-up is placed under the question it continues and starts as soon as its own parent
has an answer. The owner fixed this on 2026-10-02, so the experiment does not compare policies and every
arm runs `v2-nested`.

Where the policy is set:
- **The default:** `DEFAULT_POLICY` in `src/oceanx/research/policy.py`, changed only in a reviewed commit.
  The desktop app has no policy switch.
- **Benchmark runs:** nothing to pass. `arm.json` records the policy every arm ran with; check that it says
  `v2-nested`.

Two other policies stay in the code for paired runs outside this experiment: `v0-coordinator-bfs` (the
shallowest open questions first) and `v1-hypotheses` (hypothesis nodes). `run_oceanx.py --policy <name>`
selects one for such a run.

## Labels: what they are and how they are used

A label says how much one research-tree node (one question an Expert answered) mattered:

| Label | Meaning |
|---|---|
| decision-changing | Its result changed the final answer or the next research decisions |
| informative-but-not-decisive | Useful context, but the conclusions would be the same without it |
| misleading-or-wasteful | Wrong, or costly without informing anything |

Every executed node gets an automatic label from simple rules when the task ends. `judge-labels` adds a
model judgement, made without knowing the arm. The owner can label any node as well; this is optional. The
label that counts is the owner's, then the model's, then the automatic one.

```bash
python benchmarking/server/research_cli.py show --tree <tree path>          # tree, outcomes, current labels
python benchmarking/server/research_cli.py label --tree <tree path> --node B1.3 \
  --label decision-changing --labeler <your name> --note "changed the mechanism conclusion"
```

(tree path: `<attempt>/workspace/OceanX Tasks/<task folder>/agents/coordinator/research_tree.sqlite3`)

**A label changes nothing by itself.** It is part of the record the meta-agent reads, and it defines the
pre-registered process metric. `judge-agreement` reports how often the model's labels match the owner's.

## How OceanX learns: lessons and tools

What OceanX learns is kept in two marked places of the skills its agents already read. Nothing is added to
a prompt, and the packaged skill files are never changed: each task's copy of the skills is generated.
Arms B, C1 and C2 run the same commit and differ only in what stands in those two places.

**Where.** A skill reserves a region with a marker line, for example
`<!-- oceanx:lessons max=4 for="coordinator" about="..." -->`. The marker says how many lessons the skill
holds and what they are about. Six skills take lessons (the Coordinator's planning skill and five analysis
skills); `xarray-array-ops` has the tools region, which lists the helper functions that analysis code calls
as `ao.<name>`. A skill without a region takes nothing.

**Records.** `consolidate` writes one digest per finished run. For each question it holds who proposed it,
when it was created and run, every retry, its result and stated limits, its cost, its label, and which of
its proposed follow-ups were adopted or dropped. The digest also holds which lessons the run was shown,
which it named, which helper functions it could call and how often it called each.

**Lessons.** With `consolidate --review` the meta-agent makes one model call per skill that takes lessons.
It reads the skill as its readers get it and the records, then:
- judges every current lesson: keep, revise or retire;
- may add at most two lessons to that skill.

What it decides takes effect at once. Code, not the model, enforces these rules:
- a new lesson needs supporting runs from at least three different questions (two repeats of one question
  count once);
- a lesson contradicted by as many questions as support it is retired, whatever the model said;
- a skill never holds more lessons than its region allows; when it is full, a new lesson must be better
  supported than the weakest one, which it replaces;
- a lesson is at most 40 words with an explicit "applies when" condition, and names no task or node.

The instructions exclude programming advice, findings about one region or process, and anything the skill
already says.

**Tools.** The same update counts the helper calls of every finished run and then:
- takes a function that no run called for 20 runs in a row off the skill's list (a packaged function stays
  importable; a learned one is retired);
- looks for small functions the Experts wrote again in runs of at least three different questions, and asks
  the meta-agent for general versions of them, at most three per review, each with a test.

A proposed function is mounted only if all three checks pass: a static check (one pure function, no file,
network or printing, a short list of allowed imports), its own test run in the sandbox, and a review by a
second model call that looks for a numerical or scientific error.

**The owner.** No approval step stands between the meta-agent and the library. The owner can read every
lesson and tool and mark it right (it stays, whatever later records say) or wrong (it goes and is not
proposed again):

```bash
python benchmarking/server/research_cli.py library --project <evolution project>
python benchmarking/server/research_cli.py mark --project <evolution project> --kind lesson --id L003 \
  --wrong --reviewer <your name>
python benchmarking/server/research_cli.py mark --project <evolution project> --kind tool --id area_mean \
  --right --reviewer <your name>
```

Every change, by the meta-agent, a rule or the owner, is logged with its reason in
`.oceanx/research/lessons/changes.jsonl` and `.oceanx/research/tools/changes.jsonl`.

**Was it used?** Every model call records the skills it opened, every code run the helper functions it
called, and every run the lessons it named. Check these before reading a null result as "the library does
not help".

## The library: two rounds of learning (phases 1 and 2)

Both rounds use one evolution project, `$RUNS_ROOT/<experiment>/evolution`, so the second round sees the
first round's records, lessons and tools. The meta-agent reviews once per round, after the round's runs.
The commands, ready to copy, are in [RUNNING.md](RUNNING.md), section 3.

### Round 1: set A yields L1

1. **Run** set A as arm E1 (no library), two repeats.
2. **Model labels:** `research_cli.py judge-labels --tree <tree>` for every tree of the round.
3. **Review:** `research_cli.py consolidate --project $RUNS_ROOT/<experiment>/evolution --review
   --retention-days 3650`. This creates `evolution/.oceanx/research/` with one digest per run, counts the
   helper calls and lets the meta-agent write lessons and tools. `--retention-days 3650` keeps every attempt
   folder whole: with the default, tree stores older than 30 days are moved into the project's archive.
4. **Read** the result: `research_cli.py library --project ...`. The owner may mark items right or wrong
   (optional). Mark wrong any lesson or tool that names a test-suite region (South China Sea, Gulf of
   Mexico, East China Sea, Arabian Sea), paper or phenomenon.
5. **Freeze:** `research_cli.py snapshot --project ... --output $EVAL_ROOT/library/L1`, then make the folder
   read-only. A snapshot is never edited.

### Round 2: set B, run with L1, yields L2

1. **Run** set B as arm E2 (`--library $EVAL_ROOT/library/L1`), two repeats. Leave the
   evolution project alone while these runs are going, so its library stays equal to L1.
2. **Model labels**, as in round 1.
3. **Review** with the same `consolidate --review` command. The meta-agent now reads:
   - the records of both sets, each marked as run with or without lessons;
   - each skill with its L1 lessons, and for each lesson in how many runs it was shown and named.

   It keeps, revises or retires each L1 lesson and may add new ones. A new lesson still needs support from
   three different questions; these may come from either set. The call counts of the set B runs decide
   which tools stay listed.
4. **Read** and optionally mark, as in round 1.
5. **Freeze** as `$EVAL_ROOT/library/L2`.

If round 2 changes nothing, the two `snapshot.json` files show the same version. Report that, and leave arm
C2 out of the pre-registration.

The offline meta-agent and node-label judge use the same `BENCH_MODEL` and `DEEPSEEK_API_KEY`
from `benchmarking/.env` as all analysis methods (DeepSeek Flash by default). `research_cli.py`
installs this configuration only in its process. Freeze the model across evolution rounds;
there is no separate meta-model setting. The independent scientific rubric judge is unchanged.

## Why this design

- **Fair comparison:** all arms share the same period, data, model, commit, policy, time limit and judge,
  so the differences come from the library.
- **The library answers are about generalisation:** lessons and tools come only from the evolution suite
  (two other regions, other kinds of problems, no CMOMS data), and each snapshot is frozen before any test
  run. No kind of problem appears in more than two evolution questions, so the three-question rule can only
  be met by something that holds across kinds of problems (`DESIGN.md`, "Evolution suite").
- **Each round is measured on its own:** C1 against B shows what one round of learning gives, and C2
  against C1 shows what the second round adds. A single library arm could not separate the two.
- **The library is judged where it acts:** lessons are written into skills and tools are called from code,
  so the experiment checks that the skills were opened and the helpers called, and compares the research
  process, not only the final answers.
- **Decisions cannot follow the results:** the pre-registration and the rubrics are frozen before the test
  runs, so the decision rules cannot be tuned after the scores are known.
