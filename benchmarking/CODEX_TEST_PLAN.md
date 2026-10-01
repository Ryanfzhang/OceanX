# Benchmark test plan for Codex

You are the benchmark tester and the single judge for the OceanX benchmark (catalogue `2026-10-01-v6`). This document lists every test
to execute, in order, with commands, pass criteria and what to report. Background:
- `DESIGN.md`: what the questions are;
- `DATA.md`: the data;
- `EVALUATION.md`: the process, labels and lessons;
- `evaluation/CODEX_JUDGE.md`: how to score.

## Rules

1. **Server only.** Work on the Linux server in the `oceanx-bench` conda environment, from the repository
   root. Never on macOS.
2. **Do not change OceanX** (`src/`) or any frozen file (frozen rubrics, the pre-registration, lesson
   snapshots L1 and L2). If a benchmarking script needs a fix, make it on a branch, explain it in your report, and
   wait for the owner before using it in the test phase.
3. **Keep evaluator material away from agents.** Never put rubrics, references, answer-key data or score files
   in a folder bound to an agent. `prepare_queries.py` refuses them; do not work around it.
4. **Keep private data on the server.** CMOMS data and anything computed from them never leave it: no
   commits, no uploads, no pasting numbers into outside services.
5. **Stop and ask the owner** when a step's pass criterion fails, when data are missing or differ from
   `DATA.md` (for example CMOMS not daily), or when costs exceed the estimates by more than 50%.
6. **Report every test** in `$EVAL_ROOT/<experiment>/codex_reports/T<n>.md`. Give the commands run,
   key outputs, pass/fail per criterion, problems and decisions needed. Send the owner a short summary.

Variables used below (set them in your shell):

```bash
export DATA_ROOT=/import/home4/share/mafzhang
export RUNS_ROOT=$HOME/oceanx-bench/runs
export EVAL_ROOT=$HOME/oceanx-bench/eval
export EXP=test-v6-2026-10                  # experiment name; must match the pre-registration
```

## T0. Environment and repository

```bash
conda activate oceanx-bench
python -m pip install -r benchmarking/requirements.txt
python benchmarking/server/check_setup.py --agent oceanx
ocean doctor && ocean sandbox-self-check
python -m pytest benchmarking/tests -q
git rev-parse HEAD && git status --short
```

Pass:
- the setup check reports the model, endpoint, scientific Python and a working sandbox;
- the benchmark tests pass;
- the working tree is clean.

Report the commit. Every arm of the experiment must use this commit.

## T1. Data

1. Preview, then download the public and service groups (two terminals are fine):

   ```bash
   python benchmarking/download/download_all.py public --output "$DATA_ROOT"
   python -u benchmarking/download/download_all.py public   --output "$DATA_ROOT" --execute
   python -u benchmarking/download/download_all.py services --output "$DATA_ROOT" --execute --workers 2
   ```

   The services phase includes both evolution sets. To fetch one part first, name its groups, for example
   the Tasman Sea groups of evolution set B:

   ```bash
   python -u benchmarking/download/download_all.py services --output "$DATA_ROOT" --execute --workers 2 \
     --groups P_TAS_PHY P_TAS_SURF P_TAS_BGC
   ```
2. **Owner step:** stage CMOMS as `DATA.md` "Staging CMOMS" describes, including `CMOMS/grid/README.md`.
   When granted, also stage:
   - the heat budget under `_evaluator_only/CMOMS_DIA/`;
   - the production and carbon diagnostics for Q14 and Q16 under `CMOMS_DIA/`.
3. Check the staging and re-verify the downloads:

   ```bash
   python benchmarking/download/download_all.py private --output "$DATA_ROOT"
   python benchmarking/download/download_all.py verify  --output "$DATA_ROOT"
   ```
4. Open one CMOMS file per variable and record the time sampling, units and depth layout. Then compare them
   with `CMOMS/grid/README.md` and the queries' word "daily". Confirm that June 2017 and July 2018 are
   present, because the paper questions Q06 and Q05 depend on them.

Pass:
- `coverage.json` shows `numerical_inputs_complete: true` for all 54 tasks. Q14 and Q16 stay incomplete
  until their requested diagnostics are staged; report this, and run the other tasks only if the owner
  agrees;
- evaluator inputs are complete for Q11 and Q12 (Q05 and Q13 may lack the optional X_OXY);
- `verify` passes;
- CMOMS sampling is daily, or the owner has been told.

Report:
- downloaded volume and duration per group;
- any provider gaps (MODIS 2018-2020 is the main unknown).

## T2. Query preparation and isolation

```bash
python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite test \
  --output $RUNS_ROOT/$EXP/inputs/test-all.jsonl
for s in A B; do
  python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite evolution --set $s \
    --output $RUNS_ROOT/$EXP/inputs/evolution-$s-all.jsonl
done
```

Every case gets the default three-hour time limit. T3 and T5 check that it is long enough; if it is not,
prepare the inputs again with a longer `--timeout` and use the same value for every arm.

The test command refuses to run while any test question lacks data. If Q14 and Q16 are still waiting for
their diagnostics and the owner agrees to start without them, list the other 28 questions with `--tasks`
and record the omission in the pre-registration.

Then make one shuffled copy per repeat (seed = repeat number) for the test suite and each evolution set:

```bash
python - <<'EOF'
import json, os, random
root = os.path.expandvars("$RUNS_ROOT/$EXP/inputs")
for suite in ("test", "evolution-A", "evolution-B"):
    cases = [json.loads(l) for l in open(f"{root}/{suite}-all.jsonl")]
    for r in (1, 2, 3):
        random.Random(r).shuffle(cases)
        with open(f"{root}/{suite}-r{r}.jsonl", "x") as out:
            out.writelines(json.dumps(c, ensure_ascii=False) + "\n" for c in cases)
EOF
```

Negative checks. Each must fail with an error:
- a `--bindings` file that binds `$DATA_ROOT/_evaluator_only/CMOMS_DIA/temp_rate`;
- one that binds `benchmarking/tasks/Q11/evaluator`;
- writing the output inside `$DATA_ROOT`.

Pass:
- 30 test cases (28 without Q14 and Q16) and 12 cases in each evolution set, each pointing only at its own
  groups' folders;
- all three negative checks refused.

## T3. Smoke runs

Run one paper question on CMOMS and one open problem on public data, and one evolution question, each in
its own arm folder:

```bash
python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite test --tasks Q05 Q27 \
  --output $RUNS_ROOT/smoke/inputs/test.jsonl
python benchmarking/server/run_oceanx.py --queries $RUNS_ROOT/smoke/inputs/test.jsonl \
  --output $RUNS_ROOT/smoke/arm-B --arm B --policy v2-nested
```

Also check the lesson injection on one short evolution question, with a throwaway snapshot:

```bash
mkdir -p $RUNS_ROOT/smoke/L0 && cp benchmarking/tests/fixtures/lessons.json $RUNS_ROOT/smoke/L0/
python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite evolution --tasks E10 \
  --output $RUNS_ROOT/smoke/inputs/evolution.jsonl
python benchmarking/server/run_oceanx.py --queries $RUNS_ROOT/smoke/inputs/evolution.jsonl \
  --output $RUNS_ROOT/smoke/arm-C --arm C-smoke --policy v2-nested --lessons $RUNS_ROOT/smoke/L0
```

Pass:
- both attempts complete;
- `arm.json` shows the commit, policy and parallel-Expert limit;
- the C-smoke attempt has `arm_lessons.json` with `unchanged: true`, and its state folder holds
  `research/lessons/skills/research-trajectory-planning/SKILL.md` with the fixture lesson written in;
- the answers cite only supplied data.

Then check that the process measures can be read from these runs:

```bash
python benchmarking/evaluation/evaluate.py process --runs $RUNS_ROOT/smoke/arm-B $RUNS_ROOT/smoke/arm-C \
  --out $RUNS_ROOT/smoke/report
```

Report:
- wall time, tokens and failed code runs per attempt. These calibrate the time budget: the time limit must
  be at least 1.5 times the longest run;
- from `process.md`: whether the Coordinator opened its planning skill in each run, and how many questions'
  Experts opened an analysis skill.

## T4. References and frozen rubrics (evaluator work)

For every test task, follow `EVALUATION.md` "References and frozen rubrics":
1. Write `$EVAL_ROOT/$EXP/references/<task>/compute.py`:
   - paper questions: one calculation per finding, following its `how_to_test`;
   - open problems: one calculation per answer-key item, following its `procedure`.

   Use the same inputs as the agents, plus evaluator-only data where the rubric names it.
2. Run it and keep its outputs.
3. Write the frozen rubric `$EVAL_ROOT/$EXP/rubrics/<task>.json`: `expected` and the final `tolerance` for
   every finding and answer-key item, the expected verdict of each candidate cause, `status: "frozen"`,
   and `references_sha256`.

Order:
- first Q11 and Q12 (heat-budget answer keys);
- then the ten paper questions;
- then the rest.

For the heat-budget answer keys, confirm the budget closes: rate equals the sum of the terms, within 5% over
the region and period used.

Paper questions:
- Q01, Q03, Q06, Q08 and Q09 were checked from the abstract only. With the PDF from the owner, confirm each
  finding, the region, the window and the paper's definitions in the text, and record the page. Open copies
  exist for Q01, Q08 and Q09 (see `DESIGN.md`, "Papers").
- Confirm the transport section of Q03 and the typhoon's passage dates in Q06 from the papers before
  freezing those two rubrics.
- For Q05 and Q06, record whether the CMOMS forcing contains the typhoon. If it does not, the frozen
  expected verdicts are "not reproduced", and that is a valid reference.

**Owner step:** spot-check five frozen rubrics before the test phase: at least two paper questions, one checkable
open problem and one disagreement question.

Pass:
- 30 frozen rubrics (28 while Q14 and Q16 wait for their diagnostics), each with references and a closed
  budget where one is used;
- the owner's spot-check accepted.

## T5. Noise pilot

Arm B, three tasks (one paper question, one checkable open problem, one disagreement question), two
repeats each:

```bash
python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite test --tasks Q05 Q12 Q27 \
  --output $RUNS_ROOT/pilot/inputs/pilot.jsonl
python benchmarking/server/run_oceanx.py --queries $RUNS_ROOT/pilot/inputs/pilot.jsonl --output $RUNS_ROOT/pilot/r1/arm-B --arm B --policy v2-nested
python benchmarking/server/run_oceanx.py --queries $RUNS_ROOT/pilot/inputs/pilot.jsonl --output $RUNS_ROOT/pilot/r2/arm-B --arm B --policy v2-nested
```

Blind both repeats, judge them (T6 calibration happens here too), and report the score difference between
the two repeats of each task.

Decision for the pre-registration:
- **1 repeat** if the median absolute difference is at most 5 points;
- **2 repeats** if it is at most 10;
- **3 repeats** otherwise, or ask the owner to cut tasks.

## T6. Judge calibration

From the pilot, judge three attempts twice in separate sessions, without reading the first scores.

Pass:
- no criterion differs by more than one level;
- the owner accepts the three score pairs.

Otherwise, tighten your reading of the anchors, write down how, and repeat.

## T7. Lesson pilot (gate before the evolution rounds)

Three questions of set A, one run each, without lessons. They use three different data groups and are
three different questions, the least the meta-agent needs to propose a lesson.

```bash
python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite evolution --tasks E01 E05 E08 \
  --output $RUNS_ROOT/lesson-pilot/inputs/pilot.jsonl
python benchmarking/server/run_oceanx.py --queries $RUNS_ROOT/lesson-pilot/inputs/pilot.jsonl \
  --output $RUNS_ROOT/lesson-pilot/runs/arm-E1 --arm E1 --policy v2-nested
for tree in $(find $RUNS_ROOT/lesson-pilot/runs -name research_tree.sqlite3); do
  python benchmarking/server/research_cli.py judge-labels --tree "$tree"
done
python benchmarking/server/research_cli.py consolidate --project $RUNS_ROOT/lesson-pilot/runs --propose
python benchmarking/server/research_cli.py lessons --project $RUNS_ROOT/lesson-pilot/runs
python benchmarking/evaluation/evaluate.py process --runs $RUNS_ROOT/lesson-pilot/runs/arm-E1 \
  --out $RUNS_ROOT/lesson-pilot/report
```

Send the owner the proposals in full (text, condition, skill, section and rationale) and `process.md`.

**Owner step:** judge the proposals. This is a check of the meta-agent, not a source of lessons: the pilot
folder is separate from the experiment and nothing from it is frozen.

Pass:
- the three runs finish inside the time limit;
- the Coordinator opened its planning skill in at least two of the three runs;
- at least one Coordinator proposal is a research-tree decision that holds for all three questions and is
  not already in the skill, in the owner's judgement.

If the gate fails, stop and report. The two evolution rounds and the two lesson arms would test nothing.

## T8. Evolution round 1: set A yields L1

```bash
for r in 1 2; do
  python benchmarking/server/run_oceanx.py --queries $RUNS_ROOT/$EXP/inputs/evolution-A-r$r.jsonl \
    --output $RUNS_ROOT/$EXP/evolution/A/r$r/arm-E1 --arm E1 --policy v2-nested
done
for tree in $(find $RUNS_ROOT/$EXP/evolution/A -name research_tree.sqlite3); do
  python benchmarking/server/research_cli.py judge-labels --tree "$tree"
done
```

**Owner step:** label each run's review set (`EVALUATION.md`, "User labels"). Then:

```bash
python benchmarking/server/research_cli.py consolidate --project $RUNS_ROOT/$EXP/evolution --propose
python benchmarking/server/research_cli.py lessons --project $RUNS_ROOT/$EXP/evolution
python benchmarking/server/research_cli.py judge-agreement --runs $RUNS_ROOT/$EXP/evolution
```

Each run proposes at most three lessons per role (Coordinator: research-tree decisions; Experts: analysis),
each naming the skill and section it would be written into. Run `consolidate --propose` up to three times
if fewer than three proposals per role survive validation.

**Owner step:** approve or reject each proposal with `lesson-decide`.

Freeze the snapshot:

```bash
mkdir -p $EVAL_ROOT/lessons/L1
cp $RUNS_ROOT/$EXP/evolution/.oceanx/research/lessons/lessons.json $EVAL_ROOT/lessons/L1/
sha256sum $EVAL_ROOT/lessons/L1/lessons.json > $EVAL_ROOT/lessons/L1/SHA256
chmod -R a-w $EVAL_ROOT/lessons/L1
```

Pass:
- 24 attempts, or failures reported;
- labels done;
- L1 frozen with at least one approved lesson.

If no lesson is approved, report it: the lesson comparisons have nothing to test, and round 2 is skipped.

## T9. Evolution round 2: set B, run with L1, yields L2

Decide no proposal while these runs are going: the project's lessons must stay equal to L1.

```bash
for r in 1 2; do
  python benchmarking/server/run_oceanx.py --queries $RUNS_ROOT/$EXP/inputs/evolution-B-r$r.jsonl \
    --output $RUNS_ROOT/$EXP/evolution/B/r$r/arm-E2 --arm E2 --policy v2-nested --lessons $EVAL_ROOT/lessons/L1
done
python benchmarking/evaluation/evaluate.py lessons-check --runs $RUNS_ROOT/$EXP/evolution/B
for tree in $(find $RUNS_ROOT/$EXP/evolution/B -name research_tree.sqlite3); do
  python benchmarking/server/research_cli.py judge-labels --tree "$tree"
done
python benchmarking/evaluation/evaluate.py process \
  --runs $RUNS_ROOT/$EXP/evolution/A/r*/arm-E1 $RUNS_ROOT/$EXP/evolution/B/r*/arm-E2 \
  --out $EVAL_ROOT/$EXP/report/evolution
```

The process report here compares different questions in different regions, so it is descriptive only. Read
one row in it: whether the skills holding L1 were opened in arm E2.

**Owner step:** label the review sets of the set B runs. Then mine and review as in T8, with the same
`consolidate --project $RUNS_ROOT/$EXP/evolution --propose` command. The meta-agent now reads both sets and
the skills with L1 written in, and may propose retiring an L1 lesson.

**Owner step:** approve or reject each proposal with `lesson-decide`.

Freeze the snapshot:

```bash
mkdir -p $EVAL_ROOT/lessons/L2
cp $RUNS_ROOT/$EXP/evolution/.oceanx/research/lessons/lessons.json $EVAL_ROOT/lessons/L2/
sha256sum $EVAL_ROOT/lessons/L2/lessons.json > $EVAL_ROOT/lessons/L2/SHA256
chmod -R a-w $EVAL_ROOT/lessons/L2
cmp $EVAL_ROOT/lessons/L1/lessons.json $EVAL_ROOT/lessons/L2/lessons.json && echo "L2 equals L1"
```

Pass:
- 24 attempts, or failures reported, and `lessons-check` reports nothing changed;
- labels done;
- L2 frozen.

If L2 equals L1, report it and leave arm C2 and the two L2 comparisons out of the pre-registration.

## T10. Pre-registration

```bash
cp benchmarking/experiments/preregistration.example.yaml $EVAL_ROOT/$EXP/preregistration.yaml
```

Fill in:
- the commit from T0;
- the model;
- the judge model;
- the repeats from T5;
- the time limit used when the inputs were prepared;
- the L1 and L2 paths;
- the owner's name (**owner step:** the owner reviews the file).

Then freeze it:

```bash
python benchmarking/evaluation/evaluate.py freeze --prereg $EVAL_ROOT/$EXP/preregistration.yaml
```

Pass: the `.sha256` file exists. From now on no frozen file changes.

## T11. Test phase

For each repeat `r`, start the four arms in parallel on the same shuffled JSONL:

```bash
J=$RUNS_ROOT/$EXP/inputs/test-r$r.jsonl
python benchmarking/server/run_oceanx.py --queries $J --output $RUNS_ROOT/$EXP/test/r$r/arm-A --arm A --policy v0-coordinator-bfs &
python benchmarking/server/run_oceanx.py --queries $J --output $RUNS_ROOT/$EXP/test/r$r/arm-B --arm B --policy v2-nested &
python benchmarking/server/run_oceanx.py --queries $J --output $RUNS_ROOT/$EXP/test/r$r/arm-C1 --arm C1 --policy v2-nested --lessons $EVAL_ROOT/lessons/L1 &
python benchmarking/server/run_oceanx.py --queries $J --output $RUNS_ROOT/$EXP/test/r$r/arm-C2 --arm C2 --policy v2-nested --lessons $EVAL_ROOT/lessons/L2 &
wait
python benchmarking/evaluation/evaluate.py lessons-check --runs $RUNS_ROOT/$EXP/test
```

If memory is tight, run the arms one after another for each repeat. Watch the first repeat: if two or more
attempts in one arm fail for the same infrastructure reason, stop and report.

Pass:
- every attempt has a `result.json`;
- every `arm.json` has the same commit;
- `lessons-check` reports nothing changed.

## T12. Judging

```bash
python benchmarking/evaluation/evaluate.py blind --runs $RUNS_ROOT/$EXP/test/r*/arm-* \
  --out $EVAL_ROOT/$EXP/blind --map $EVAL_ROOT/$EXP/blind_map.json
```

Judge every blind folder by `evaluation/CODEX_JUDGE.md`, task by task. Then:

```bash
python benchmarking/evaluation/evaluate.py validate --scores $EVAL_ROOT/$EXP/scores
```

Label the test trees with the model judge. It reads each question, its result and the final answer, not
the arm:

```bash
for tree in $(find $RUNS_ROOT/$EXP/test -name research_tree.sqlite3); do
  python benchmarking/server/research_cli.py judge-labels --tree "$tree"
done
```

Pass:
- every completed attempt has a valid score file;
- `validate` reports no invalid files;
- every finished test tree has judge labels.

## T13. Analysis

```bash
python benchmarking/evaluation/evaluate.py summarize --prereg $EVAL_ROOT/$EXP/preregistration.yaml \
  --map $EVAL_ROOT/$EXP/blind_map.json --scores $EVAL_ROOT/$EXP/scores --out $EVAL_ROOT/$EXP/report
python benchmarking/evaluation/evaluate.py process --runs $RUNS_ROOT/$EXP/test/r*/arm-* \
  --prereg $EVAL_ROOT/$EXP/preregistration.yaml --out $EVAL_ROOT/$EXP/report
```

Send the owner:
- `report.md` and `process.md`;
- the differences by question type and by data access (private CMOMS, public);
- for each lesson comparison, the score result and the process result side by side, with the spread
  between control repeats;
- how often the skills holding lessons were opened in arms C1 and C2;
- the five largest per-task differences in each direction, with one line on why;
- failures by arm;
- total cost.

Do not change any rule after seeing the results. Proposals for the next experiment go in a separate section.

## Time and cost (planning estimates; T3 and T5 refine them)

| Phase | Attempts | Estimate |
|---|---|---|
| T3-T5 smoke and pilot | 9 | half a day |
| T7 lesson pilot | 3 | half a day, plus the owner's review |
| T8 evolution round 1 | 24 | 1-2 days, plus the owner's labelling and approval |
| T9 evolution round 2 | 24 | 1-2 days, plus the owner's labelling and approval |
| T11 test (4 arms x 30 x repeats) | 120 per repeat | 2-4 days per repeat with four parallel arms |
| T4 references | - | several days of evaluator work; can overlap T8 and T9 |
| T12 judging | 120 per repeat | 1-2 days per repeat, plus the judge labels |
