# Evaluation: how runs are made, stored and judged

One experiment answers three questions with one set of test runs:

1. **Policy:** should the default research policy be `v0-coordinator-bfs` or `v2-nested`?
2. **Lesson transfer:** do lessons learned on one evolution set improve research on the test suite?
3. **A second round:** do lessons revised after a second evolution set, itself run with the first
   lessons, improve it further?

Questions 2 and 3 are each answered twice: by the judged score of the answer, and by a measure of how
the research tree went. Lessons are about tree decisions, so an unchanged tree with a better-worded
answer would not count as learning.

## The process

| Phase | What happens | Who |
|---|---|---|
| 0. Prepare | Data downloaded and staged; references computed and rubrics frozen | Codex; owner signs off |
| 1. Evolve, round 1 | Evolution set A (E01-E12) runs without lessons; tree nodes labelled; lessons mined, reviewed and frozen as L1 | Codex runs; **owner labels and approves** |
| 2. Evolve, round 2 | Evolution set B (E13-E24) runs with L1; nodes labelled; lessons added or retired; the result frozen as L2 | Codex runs; **owner labels and approves** |
| 3. Test | Pre-registration frozen. Test suite (Q01-Q30) runs in four arms, nothing evolving | Codex |
| 4. Judge | Outputs blinded; Codex scores every attempt against the frozen rubric; the model judge labels the test trees | Codex |
| 5. Decide | Paired comparisons of scores and of the process metric; pre-registered rules applied; report written | Codex; owner decides |

Arms (fixed in the pre-registration):

| Arm | Policy | Lessons | Used for |
|---|---|---|---|
| A | v0-coordinator-bfs | none | control for the policy comparison |
| B | v2-nested | none (L0) | treatment for policy; control for L1 |
| C1 | v2-nested | frozen snapshot L1 | treatment for L1; control for L2 |
| C2 | v2-nested | frozen snapshot L2 | treatment for L2 |

## Storage

```text
$RUNS_ROOT/<experiment>/
  evolution/A/r<k>/arm-E1/<E01..E12>/attempt-*/   round 1: set A, no lessons (arm.json at arm level)
  evolution/B/r<k>/arm-E2/<E13..E24>/attempt-*/   round 2: set B, lessons L1
  evolution/.oceanx/research/                     digests, lesson proposals and decisions of both rounds
  test/r<k>/arm-A|arm-B|arm-C1|arm-C2/<Q01..Q30>/attempt-*/
$EVAL_ROOT/<experiment>/
  preregistration.yaml (+ .sha256)             frozen before the test phase
  rubrics/<task>.json                          frozen rubrics (template + reference values + answer key)
  references/<task>/                           evaluator scripts and outputs (private-data derived)
  blind/<blind_id>/                            what the judge reads
  blind_map.json                               blind ID -> arm, run; the judge opens it only after scoring
  scores/<blind_id>.json                       Codex score files
  report/                                      summary.json, report.md, process.json and process.md
$EVAL_ROOT/lessons/L1/lessons.json (+ SHA256, approvals.json)   frozen after round 1
$EVAL_ROOT/lessons/L2/lessons.json (+ SHA256, approvals.json)   frozen after round 2
```

Every attempt folder holds `query.json`, `result.json` (status, time, tokens), `answer.md`,
`model_protocol.json` and the task workspace. `arm.json` records arm, policy, lesson version and SHA-256,
git commit (and whether the tree was dirty), OceanX version and the parallel-Expert limit.

## Running arms

```bash
python benchmarking/server/run_oceanx.py --queries <suite.jsonl> --output <arm folder> \
  --arm A --policy v0-coordinator-bfs                      # arm A
  --arm B --policy v2-nested                               # arm B
  --arm C1 --policy v2-nested --lessons $EVAL_ROOT/lessons/L1  # arm C1
  --arm C2 --policy v2-nested --lessons $EVAL_ROOT/lessons/L2  # arm C2
```

- One JSONL per repeat with the task order shuffled (`seed = repeat number`). Run the four arm processes
  in parallel on the same JSONL, so time-dependent effects (provider load, web search results) hit all arms
  equally. With limited memory, run them one after another per repeat and keep the order.
- Every arm uses the same per-attempt time limit, set when the JSONL is prepared (`--timeout`, three hours
  by default) and recorded in the pre-registration. A timed-out attempt scores 0, so a limit that is too
  short penalises the arm that explores more.
- Use the same commit, `benchmark.yaml` model and literature mode (`search_only`) for every arm. No merges
  or setting changes until the test phase ends.
- A failed, timed-out or empty attempt scores 0 and is reported separately. Do not re-run a failed
  attempt for a better score. `--resume` only completes attempts that never finished.

### Nothing evolves during benchmarking

- Each attempt starts with empty OceanX state (its own state folder), so no memory, digest or lesson
  carries over between attempts.
- Arms C1 and C2 copy their frozen snapshot into each attempt. The attempt records the lesson file's
  SHA-256 before and after; `evaluate.py lessons-check --runs <test folder>` must report nothing changed.
- During the test phase, do not run `consolidate`, `lesson-decide` or anything else that edits lessons.

## References and frozen rubrics (phase 0)

The rubric in the repository is a template with status `draft`. Before judging, the evaluator makes a
frozen copy per task under `$EVAL_ROOT/<experiment>/rubrics/`:

1. Write the reference scripts in `$EVAL_ROOT/<experiment>/references/<task>/`:
   - paper verification: one calculation per finding, following its `how_to_test`;
   - open problems: one calculation per answer-key item, following its `procedure`.

   Run them on the same inputs the agents get, plus the evaluator-only data where the rubric names it.
2. Fill the frozen copy:
   - `expected` and the final `tolerance` for every finding and every answer-key item (the suggested
     tolerances unless the owner changes them);
   - for disagreement questions, the expected verdict of each candidate cause.
3. Paper tasks: confirm each finding against the paper text. Q02, Q04, Q05, Q07 and Q10 were read in full
   when the catalogue was written. Q01, Q03, Q06, Q08 and Q09 were checked from the abstract only: confirm
   their regions, windows and definitions from the paper (the owner provides the PDF) and record where in
   the paper each was confirmed. Otherwise the abstract wording in the rubric stands. Two rubrics name a
   detail to confirm first: the transport section of Q03 and the typhoon's passage dates in Q06.
4. Set `status: "frozen"`, `frozen.references_sha256` (SHA-256 of the reference outputs), date and name.
   From then on the frozen rubric is read-only.

Reference outputs contain numbers derived from CMOMS: they stay in `$EVAL_ROOT` and are never committed.

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
difference over tasks with a 95% bootstrap interval, wins and losses, token reduction, and whether the
pre-registered rule is met. It also gives the difference by question type (paper verification, open
problem) and by data access (private CMOMS, public). Read these rows before concluding:
- a policy can help open problems and do nothing for paper verification;
- lessons learned on public reanalyses may help public questions more than the unseen CMOMS questions.

### Process measures

The score says how good the answer is. These measures say how the research tree got there. They come
from each attempt's tree store, after the model judge has labelled the test trees:

```bash
for tree in $(find $RUNS_ROOT/<experiment>/test -name research_tree.sqlite3); do
  python benchmarking/server/research_cli.py judge-labels --tree "$tree"
done
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

How to read them:
- **With the score.** Fewer non-decisive tokens with a lower score is not an improvement.
- **Against the noise.** The report gives, next to each comparison, the mean spread of the metric between
  repeats of the control arm. A difference smaller than that spread is noise.
- **As a proxy.** "Decisive" is the model judge's label for each question (would the conclusion change
  without it), made without knowing the arm. It is the same model as the runs, not a human.
- **Before a null result.** If the skills were rarely opened, the lessons were not tested.

## How the research policy is chosen

A research policy is the set of rules the Coordinator follows for its research tree.

- **v0-coordinator-bfs** (current default) runs the shallowest open questions first: a follow-up waits
  until every question above it has finished.
- **v2-nested** puts each follow-up under the question it continues and starts it as soon as its own parent
  has an answer.
- **v1-hypotheses** adds hypothesis nodes. It is not part of this experiment.

How the choice is made:

1. Arms A and B run the same 30 questions with everything else identical. Codex scores each answer
   without knowing the arm.
2. For each question, take B's score minus A's (averaged over repeats). Average over the questions and
   compute a 95% bootstrap interval.
3. Pre-registered rule: adopt v2-nested if it is **not worse by more than 2 points** (the interval's lower end
   is at least -2) **and** it is either better on average or at least 15% cheaper in tokens. Otherwise keep v0.

Example: mean B-A = +3.1 points, 95% interval [-0.8, +6.9], 21 wins and 7 losses, tokens -9%. The lower end is
above -2 and the mean is above 0, so v2-nested is adopted.

Applying the decision:
- **Benchmark runs:** pass `--policy`.
- **The desktop app:** choose it in **Review → Policies**.
- **Everyone's default:** change `DEFAULT_POLICY` in `src/oceanx/research/policy.py` in a reviewed commit.

## User labels: what they are and how they are used

A label is your judgement of one research-tree node (one question an Expert answered) from an evolution run:

| Label | Meaning |
|---|---|
| decision-changing | Its result changed the final answer or the next research decisions |
| informative-but-not-decisive | Useful context, but the conclusions would be the same without it |
| misleading-or-wasteful | Wrong, or costly without informing anything |

Every executed node gets an automatic label from simple rules when the task ends. `judge-labels` adds a model
judgement. You label only a small **review set** per run:
- the top-level branches;
- the nodes cited in the final report;
- the nodes where the automatic and model labels disagree;
- two closed nodes.

That is usually 4-8 nodes, a few minutes per run. The label that counts is yours, then the model's, then the
automatic one.

How to label on the server (tree path: `<attempt>/workspace/OceanX Tasks/<task folder>/agents/coordinator/research_tree.sqlite3`):

```bash
python benchmarking/server/research_cli.py show --tree <tree path>          # tree, outcomes, current labels
python benchmarking/server/research_cli.py label --tree <tree path> --node B1.3 \
  --label decision-changing --labeler <your name> --note "changed the mechanism conclusion"
```

How labels are applied: **a label changes nothing by itself.** It is evidence for lessons.
- **Digests:** `consolidate` writes a digest per finished run. For each question it holds who proposed it, when
  it was created and run, every retry, its result and stated limits, its cost, its effective label, and which
  of its proposed follow-ups were adopted or dropped.
- **Mining:** the meta-agent reads the digests and the skills it may write into, and proposes lessons with
  one model call per role:
  - Coordinator: research-tree decisions, such as the order of questions, which follow-ups to adopt, how
    deep to go, retries and when to stop. These are written into `research-trajectory-planning`.
  - Analysis Experts: what to watch for in an analysis, such as definitions, limits of the data, method
    assumptions and checks. These are written into the analysis skills, for example
    `ocean-physical-consistency-review`.

  Each proposal names its skill and section. A lesson needs supporting runs from at least three different
  questions; two repeats of one question count once. Programming advice, findings about one region or
  process, and anything a skill already says are excluded by the instructions.
- **Approval:** you approve, edit or reject each proposal. An approved lesson is written into the named
  skill, at the end of the named section. Nothing is added to a prompt, and the packaged skill files are
  not changed: arms B and C run the same commit and differ only in the lessons written into those skills.
- **Was the skill read?** Every model call records the skills it opened (`skills_read` in the model-call
  records of the attempt's workspace database). Check this before reading a null result as "lessons do not
  help".
- **Checking the model judge:** `judge-agreement` tells you how often the model's labels match yours. When it agrees well,
  you can label fewer nodes in later rounds.

## Lessons: two rounds of learning (phases 1 and 2)

Both rounds use one evolution project, `$RUNS_ROOT/<experiment>/evolution`, so the second round sees the
first round's records and lessons.

### Round 1: set A yields L1

1. **Run** set A as arm E1 (`--policy v2-nested`, no lessons), two repeats.
2. **Model labels:** `research_cli.py judge-labels --tree <tree>` for every tree of the round.
3. **Your labels:** label the review set of each tree (above).
4. **Mine:** `research_cli.py consolidate --project $RUNS_ROOT/<experiment>/evolution --propose`. This creates
   `evolution/.oceanx/research/` with one digest per run and at most three lesson proposals per role. Run
   it again for more proposals; proposals awaiting review are shown to the meta-agent and duplicates are
   refused.
5. **Review:** `research_cli.py lessons --project ...` lists the proposals.
   - Approve one: `lesson-decide --project ... --proposal lp_... --approve --reviewer <you>`, optionally with
     `--text` and `--applies-when` edits.
   - Reject one: `--reject --reason "..."`.
   - Approve only general advice. Reject any lesson naming a test-suite region (South China Sea, Gulf of
     Mexico, East China Sea, Arabian Sea), paper or phenomenon.
6. **Freeze:** copy `evolution/.oceanx/research/lessons/lessons.json` to `$EVAL_ROOT/lessons/L1/`, write its
   SHA-256 and the list of approved proposals, and never edit L1 again.

### Round 2: set B, run with L1, yields L2

1. **Run** set B as arm E2 (`--policy v2-nested --lessons $EVAL_ROOT/lessons/L1`), two repeats. Decide no
   proposal while these runs are going, so the project's lessons stay equal to L1.
2. **Labels:** model labels and your labels, as in round 1.
3. **Mine** again with the same `consolidate --propose` command. The meta-agent now reads:
   - the records of both sets, each marked as run with or without lessons;
   - the skills with the L1 lessons written in, each with its id.

   It can propose new lessons, and it can propose retiring an L1 lesson that the set B runs contradict.
4. **Review** as in round 1. A new lesson still needs support from three different questions; these may come
   from either set.
5. **Freeze** the project's `lessons.json` as `$EVAL_ROOT/lessons/L2/`. L2 is L1 plus the lessons approved
   in round 2, minus those retired.

If round 2 changes nothing, L2 equals L1. Report that, and leave arm C2 out of the pre-registration.

The meta model is the `benchmark.yaml` model (through `research_cli.py`), the same as the runs.

## Why this design

- **Fair comparison:** all four arms share the same period, data, model, commit, time limit and judge, so
  the differences come from policy and lessons.
- **The lesson answers are about generalisation:** lessons come only from the evolution suite (two other
  regions, open problems only, no CMOMS data), and you approve them before seeing any test result.
- **Each round is measured on its own:** C1 against B shows what one round of learning gives, and C2
  against C1 shows what the second round adds. A single lesson arm could not separate the two.
- **Lessons are judged where they act:** they are written into skills and are about tree decisions, so the
  experiment checks that the skills were opened and compares the trees, not only the final answers.
- **Decisions cannot follow the results:** the pre-registration and the rubrics are frozen before the test
  runs, so the decision rules cannot be tuned after the scores are known.
