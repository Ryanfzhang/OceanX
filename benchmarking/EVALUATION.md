# Evaluation: how runs are made, stored and judged

One experiment answers two questions with one set of test runs:

1. **Policy:** should the default research policy be `v0-coordinator-bfs` or `v2-nested`?
2. **RSI:** do lessons learned on the evolution suite improve answers on the test suite?

## The process

| Phase | What happens | Who |
|---|---|---|
| 0. Prepare | Data downloaded and staged; references computed and rubrics frozen; pre-registration frozen | Codex; owner signs off |
| 1. Evolve | Evolution suite (E01-E12) runs; tree nodes labelled; lessons mined, reviewed, frozen as snapshot L1 | Codex runs; **owner labels and approves** |
| 2. Test | Test suite (Q01-Q30) runs in three arms, nothing evolving | Codex |
| 3. Judge | Outputs blinded; Codex scores every attempt against the frozen rubric | Codex |
| 4. Decide | Paired comparisons and pre-registered rules applied; report written | Codex; owner decides |

Arms (fixed in the pre-registration):

| Arm | Policy | Lessons | Used for |
|---|---|---|---|
| A | v0-coordinator-bfs | none | control for the policy comparison |
| B | v2-nested | none | treatment for policy; control for RSI |
| C | v2-nested | frozen snapshot L1 | treatment for RSI |

## Storage

```text
$RUNS_ROOT/<experiment>/
  evolution/r<k>/arm-E/<E01..E12>/attempt-*/   run_oceanx.py output (arm.json at arm level)
  evolution/.oceanx/research/                  digests, lesson proposals and decisions (created by consolidate)
  test/r<k>/arm-A|arm-B|arm-C/<Q01..Q30>/attempt-*/
$EVAL_ROOT/<experiment>/
  preregistration.yaml (+ .sha256)             frozen before phase 2
  rubrics/<task>.json                          frozen rubrics (template + reference values + answer key)
  references/<task>/                           evaluator scripts and outputs (private-data derived)
  blind/<blind_id>/                            what the judge reads
  blind_map.json                               blind ID -> arm, run; the judge opens it only after scoring
  scores/<blind_id>.json                       Codex score files
  report/                                      summary.json and report.md
$EVAL_ROOT/lessons/L1/lessons.json (+ SHA256, approvals.json)   frozen lesson snapshot
```

Every attempt folder holds `query.json`, `result.json` (status, time, tokens), `answer.md`,
`model_protocol.json` and the task workspace. `arm.json` records arm, policy, lesson version and SHA-256,
git commit (and whether the tree was dirty), OceanX version and the parallel-Expert limit.

## Running arms

```bash
python benchmarking/server/run_oceanx.py --queries <suite.jsonl> --output <arm folder> \
  --arm A --policy v0-coordinator-bfs                      # arm A
  --arm B --policy v2-nested                               # arm B
  --arm C --policy v2-nested --lessons $EVAL_ROOT/lessons/L1   # arm C
```

- One JSONL per repeat with the task order shuffled (`seed = repeat number`). Run the three arm processes
  in parallel on the same JSONL, so time-dependent effects (provider load, web search results) hit all arms
  equally. With limited memory, run them one after another per repeat and keep the order.
- Use the same commit, `benchmark.yaml` model and literature mode (`search_only`) for every arm. No merges
  or setting changes until phase 2 ends.
- A failed, timed-out or empty attempt scores 0 and is reported separately. Do not re-run a failed
  attempt for a better score. `--resume` only completes attempts that never finished.

### Nothing evolves during benchmarking

- Each attempt starts with empty OceanX state (its own state folder), so no memory, digest or lesson
  carries over between attempts.
- Arm C copies the frozen snapshot into each attempt. The attempt records the lesson file's SHA-256 before
  and after; `evaluate.py lessons-check --runs <test folder>` must report nothing changed.
- During phase 2, do not run `consolidate`, `lesson-decide` or anything else that edits lessons.

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
3. Paper tasks: confirm each finding against the paper text, if the owner provides the PDF. Otherwise the
   abstract wording in the rubric stands. Record where in the paper it was confirmed. Two rubrics name a
   detail to confirm first: the transport section of Q03 and the typhoon's passage dates in Q06.
4. Set `status: "frozen"`, `frozen.references_sha256` (SHA-256 of the reference outputs), date and name.
   From then on the frozen rubric is read-only.

Reference outputs contain numbers derived from CMOMS: they stay in `$EVAL_ROOT` and are never committed.

## Judging (phase 3)

```bash
python benchmarking/evaluation/evaluate.py blind --runs <every arm folder of the test phase> \
  --out $EVAL_ROOT/<experiment>/blind --map $EVAL_ROOT/<experiment>/blind_map.json
```

Codex then follows `evaluation/CODEX_JUDGE.md` for every blind folder and writes `scores/<blind_id>.json`.
Afterwards:

```bash
python benchmarking/evaluation/evaluate.py validate --scores $EVAL_ROOT/<experiment>/scores
```

## Analysis (phase 4)

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

## Lessons: from evolution runs to the frozen snapshot (phase 1)

1. **Run** the evolution suite as arm E (`--policy v2-nested`, no lessons), two repeats.
2. **Model labels:** `research_cli.py judge-labels --tree <tree>` for every evolution tree.
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
6. **Freeze:** copy `evolution/.oceanx/research/lessons/lessons.json` to `$EVAL_ROOT/lessons/L1/`, write its SHA-256
   and the list of approved proposals, and never edit L1 again.
7. **Use:** arm C runs with `--lessons $EVAL_ROOT/lessons/L1`.

The meta model is the `benchmark.yaml` model (through `research_cli.py`), the same as the runs.

## Why this design

- **Fair comparison:** all three arms share the same period, data, model, commit and judge, so the
  differences come from policy and lessons.
- **The RSI answer is about generalisation:** lessons come only from the evolution suite (another region, open
  problems only, no CMOMS data), and you approve them before seeing any test result.
- **Decisions cannot follow the results:** the pre-registration and the rubrics are frozen before the test
  runs, so the decision rules cannot be tuned after the scores are known.
