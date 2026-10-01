# Benchmark test plan for Codex

You are the benchmark tester and the single judge for the OceanX benchmark (catalogue `2026-10-01-v5`). This document lists every test
to execute, in order, with commands, pass criteria and what to report. Background:
- `DESIGN.md`: what the questions are;
- `DATA.md`: the data;
- `EVALUATION.md`: the process, labels and lessons;
- `evaluation/CODEX_JUDGE.md`: how to score.

## Rules

1. **Server only.** Work on the Linux server in the `oceanx-bench` conda environment, from the repository
   root. Never on macOS.
2. **Do not change OceanX** (`src/`) or any frozen file (frozen rubrics, the pre-registration, lesson
   snapshot L1). If a benchmarking script needs a fix, make it on a branch, explain it in your report, and
   wait for the owner before using it in phase 2.
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
export EXP=test-v5-2026-10                  # experiment name; must match the pre-registration
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
- `coverage.json` shows `numerical_inputs_complete: true` for all 42 tasks. Q14 and Q16 stay incomplete
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
python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite evolution \
  --output $RUNS_ROOT/$EXP/inputs/evolution-all.jsonl
```

The test command refuses to run while any test question lacks data. If Q14 and Q16 are still waiting for
their diagnostics and the owner agrees to start without them, list the other 28 questions with `--tasks`
and record the omission in the pre-registration.

Then make one shuffled copy per repeat (seed = repeat number) for each suite:

```bash
python - <<'EOF'
import json, os, random
root = os.path.expandvars("$RUNS_ROOT/$EXP/inputs")
for suite in ("test", "evolution"):
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
- 30 test cases (28 without Q14 and Q16) and 12 evolution cases, each pointing only at its own groups'
  folders;
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

Report:
- wall time, tokens and failed code runs per attempt. These calibrate the time budget.

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
- If the owner supplies the PDF, confirm each finding in the paper text and record the page.
- Confirm the transport section of Q03 and the typhoon's passage dates in Q06 from the papers before
  freezing those two rubrics.
- For Q05 and Q06, record whether the CMOMS forcing contains the typhoon. If it does not, the frozen
  expected verdicts are "not reproduced", and that is a valid reference.

**Owner step:** spot-check five frozen rubrics before phase 2: at least two paper questions, one checkable
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

## T7. Evolution phase

```bash
for r in 1 2; do
  python benchmarking/server/run_oceanx.py --queries $RUNS_ROOT/$EXP/inputs/evolution-r$r.jsonl \
    --output $RUNS_ROOT/$EXP/evolution/r$r/arm-E --arm E --policy v2-nested
done
for tree in $(find $RUNS_ROOT/$EXP/evolution -name research_tree.sqlite3); do
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
- 24 evolution attempts, or failures reported;
- labels done;
- L1 frozen with at least one approved lesson.

If no lesson is approved, report it: the RSI comparison has nothing to test.

## T8. Pre-registration

```bash
cp benchmarking/experiments/preregistration.example.yaml $EVAL_ROOT/$EXP/preregistration.yaml
```

Fill in:
- the commit from T0;
- the model;
- the judge model;
- the repeats from T5;
- the L1 path;
- the owner's name (**owner step:** the owner reviews the file).

Then freeze it:

```bash
python benchmarking/evaluation/evaluate.py freeze --prereg $EVAL_ROOT/$EXP/preregistration.yaml
```

Pass: the `.sha256` file exists. From now on no frozen file changes.

## T9. Test phase

For each repeat `r`, start the three arms in parallel on the same shuffled JSONL:

```bash
J=$RUNS_ROOT/$EXP/inputs/test-r$r.jsonl
python benchmarking/server/run_oceanx.py --queries $J --output $RUNS_ROOT/$EXP/test/r$r/arm-A --arm A --policy v0-coordinator-bfs &
python benchmarking/server/run_oceanx.py --queries $J --output $RUNS_ROOT/$EXP/test/r$r/arm-B --arm B --policy v2-nested &
python benchmarking/server/run_oceanx.py --queries $J --output $RUNS_ROOT/$EXP/test/r$r/arm-C --arm C --policy v2-nested --lessons $EVAL_ROOT/lessons/L1 &
wait
python benchmarking/evaluation/evaluate.py lessons-check --runs $RUNS_ROOT/$EXP/test
```

If memory is tight, run the arms one after another for each repeat. Watch the first repeat: if two or more
attempts in one arm fail for the same infrastructure reason, stop and report.

Pass:
- every attempt has a `result.json`;
- every `arm.json` has the same commit;
- `lessons-check` reports nothing changed.

## T10. Judging

```bash
python benchmarking/evaluation/evaluate.py blind --runs $RUNS_ROOT/$EXP/test/r*/arm-* \
  --out $EVAL_ROOT/$EXP/blind --map $EVAL_ROOT/$EXP/blind_map.json
```

Judge every blind folder by `evaluation/CODEX_JUDGE.md`, task by task. Then:

```bash
python benchmarking/evaluation/evaluate.py validate --scores $EVAL_ROOT/$EXP/scores
```

Pass:
- every completed attempt has a valid score file;
- `validate` reports no invalid files.

## T11. Analysis

```bash
python benchmarking/evaluation/evaluate.py summarize --prereg $EVAL_ROOT/$EXP/preregistration.yaml \
  --map $EVAL_ROOT/$EXP/blind_map.json --scores $EVAL_ROOT/$EXP/scores --out $EVAL_ROOT/$EXP/report
```

Send the owner:
- `report.md`;
- the differences by question type and by data access (private CMOMS, public);
- the five largest per-task differences in each direction, with one line on why;
- failures by arm;
- total cost.

Do not change any rule after seeing the results. Proposals for the next experiment go in a separate section.

## Time and cost (planning estimates; T3 and T5 refine them)

| Phase | Attempts | Estimate |
|---|---|---|
| T3-T5 smoke and pilot | 9 | half a day |
| T7 evolution | 24 | 1-2 days, plus the owner's labelling and approval |
| T9 test (3 arms x 30 x repeats) | 90 per repeat | 2-4 days per repeat with three parallel arms |
| T4 references | - | several days of evaluator work; can overlap T7 |
| T10 judging | 90 per repeat | 1-2 days per repeat |
