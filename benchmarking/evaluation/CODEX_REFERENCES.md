# Reference answers and frozen rubrics: instructions for Codex

You compute the reference answers of the test questions and freeze their rubrics (phase 0 of
`EVALUATION.md`). The judge later compares every agent's result with what is frozen here, so a wrong
reference is worse than a missing one.

**Scope now:** the 17 questions that have data and runs: Q07-Q10, Q15, Q18-Q21 and Q23-Q30. All use public
data. Their rubrics wait in 121 places: the expected value and the tolerance of each finding (paper tasks)
and of each answer-key item (open problems), and the expected verdict of each candidate cause (Q20, Q23,
Q27, Q29). The other 13 questions wait for CMOMS.

**Not part of this work:** scoring or rescoring any attempt, running any agent, and changing criteria,
weights, anchors, probes or gates.

## Where the work lives

On the server, `EVAL=/import/home3/share/oceanx-bench/eval` (the owner's choice of 2026-10-08). It stands
for `$EVAL_ROOT/<experiment>` in `EVALUATION.md`. Nothing under it is committed, and `eval` is never used as
a `BENCH_EXPERIMENT` name.

```text
$EVAL/references/<task>/spec.md          the definitions, written before anything is computed
$EVAL/references/<task>/compute.py       one function per finding or answer-key item
$EVAL/references/<task>/outputs/         values.json, small tables, a few figures (what the hash covers)
$EVAL/references/<task>/checks.md        the self-checks and what they showed
$EVAL/references/<task>/open-points.md   only when something could not be settled
$EVAL/rubrics/<task>.json                the frozen copy of the repository's rubric
$EVAL/reports/                           your reports
```

Agents must not read it. OceanX and Finch run in sandboxes that see only their question's data, but Claude
Code has host Bash under the same user. While any method is running the folder is closed
(`chmod 000 "$EVAL"`), and opened again afterwards (`chmod 700 "$EVAL"`).

## Rules

1. **Method before numbers.** For every finding and every answer-key item, write the definition in
   `spec.md` before computing it. A definition chosen after seeing the number is not a reference.
2. **Independent of every agent.** You have reviewed the three methods' answers to these questions. A
   reference must not come from them. `compute.py` reads the bound input data and nothing else. While you
   work on references, do not open run folders, blind folders, `benchmarking/reviews/` or your earlier
   review notes, and reuse no agent's code, number or definition. Start from a new session. If you
   remember an agent's number, do not use it to choose a definition or to decide that a result looks right.
3. **The same inputs as the agents.** Only the data folders the task binds (`data_groups` in its
   `task_info.json`, resolved through `download/data_manifest.json`). No other product and no download.
4. **Tolerances are fixed before any score is known.** The rubric's suggested tolerance is frozen as it is
   written. Propose another only when the reference work itself gives the reason, for example two
   legitimate definitions that differ by more than the suggested tolerance. Write the reason in
   `open-points.md` and wait for the owner. A tolerance is never set from what any method answered.
5. **Do not guess.** When a procedure is ambiguous, when the supplied data cannot give the quantity, or
   when the paper says something else than the rubric, do not choose silently. Record it in
   `open-points.md` with the options and what each would change, leave that place unfilled, and go on with
   the rest. A change to a rubric's wording is the owner's. It is made in the repository before freezing,
   with a new `rubric_version`.
6. **A reference says what the supplied data give.** For a paper task this can be "not reproduced" or
   "not testable with the supplied data"; an agent that reports the same earns full marks. Do not bend a
   reference towards the paper.

## For each task

1. **Read** the question (`tasks/<task>/task_info.json`) and the rubric
   (`tasks/<task>/evaluator/rubric.json`): each finding's `how_to_test`, each answer-key item's `procedure`,
   each candidate cause's `test`. For a paper task read the paper for every finding and note the section
   or page that states it.
2. **Write `spec.md`**, one entry per finding, answer-key item and candidate cause:

   ```markdown
   ## Q08-K1
   Claim or quantity: (quoted from the rubric)
   - Decides it: the number or pattern that settles it, with units.
   - Data: folders and variables, of those the task binds.
   - Where and when: region with coordinates, depth range, period, sampling.
   - Definition: the formula or procedure with every threshold, and where each part comes from (the
     question, the rubric, or the paper with section or page).
   - Other legitimate definitions: any other choice a careful analyst could make. Each is computed too.
   - Reading the result: which results mean reproduced, partly reproduced, not reproduced or not testable
     (paper tasks); how the reference value is read off (answer-key items); which result means supported,
     partly supported or not supported (candidate causes).
   ```
3. **Write and run `compute.py`.** One function per entry of `spec.md`, named after its id. It writes
   `outputs/values.json` and whatever small tables or figures help a reader check it:

   ```json
   {"task": "Q08", "catalogue": "2026-10-02-v7", "commit": "<git commit>", "computed_at": "<time>",
    "inputs": ["<bound folder>", "..."],
    "items": [
      {"id": "Q08-K1", "definition": "one line",
       "value": {"layer_top_m": 60, "layer_bottom_m": 240},
       "alternatives": [{"definition": "one line", "value": {"layer_top_m": 55, "layer_bottom_m": 260}}],
       "verdict": "partly reproduced", "why": "one or two sentences"}
    ]}
   ```

   An answer-key item has no `verdict`. A candidate cause has `verdict` (supported, partly supported or
   not supported) and `why`.
4. **Check yourself** and write what each check showed in `checks.md`:
   - units and order of magnitude, against a published or textbook value;
   - the main number again by a second, independent code path (another reduction order, an explicit loop
     on a sub-sample, another library call);
   - closure or conservation where the quantity has one;
   - every other legitimate definition of `spec.md`, and whether the reading of the result changes;
   - the share of missing or masked data in what was averaged;
   - paper tasks: the paper's own numbers beside yours. They need not agree; say which do and which do not.
5. **Fill the frozen copy.** Copy the repository's rubric to `$EVAL/rubrics/<task>.json` and change only:
   - a finding's `expected`: the verdict label first, then the reference numbers with units, for example
     `"partly reproduced: low-stratification layer 60-240 m in the reanalysis eddy core (paper: 50-250 m)"`;
   - an answer-key item's `expected`: the value with units, and its range across the legitimate definitions;
   - every `tolerance`: the suggested text made final, without "to freeze before judging (suggested: ...)";
   - a candidate cause's `expected`: exactly `supported`, `partly supported` or `not supported`;
   - `status: "frozen"`, and in `frozen`: `references_sha256`, `tolerances_frozen_at` (the date) and
     `frozen_by`.

   A finding whose `expected` is already `n/a` (not testable) stays as it is.
6. **Check the result** and make the rubric read-only:

   ```bash
   python benchmarking/evaluation/evaluate.py rubric-check \
     --rubrics "$EVAL/rubrics" --references "$EVAL/references" --tasks Q08 Q25 Q27
   chmod a-w "$EVAL/rubrics/Q08.json"
   ```

   The command prints the hash of each task's `outputs/` (that is the value of `frozen.references_sha256`)
   and lists what is still wrong. A rubric is frozen when it is listed under `ready`. After that, neither
   the rubric nor its `outputs/` changes.

**Q09.** Its rubric was checked against the full paper on 2026-10-08 (rubric 3.3; Sosa-Gutierrez et al.
2020, doi:10.1029/2019JC015397; the owner has the PDF). Two things to carry into its `spec.md`: the paper's
eddy core is the 30 km around the centre, and findings 3 to 5 are results of the paper's regional model
for simulated eddies of 1993-2012, which the question asks to test on the observed eddy of 2016-2017.

## Order of work

1. **Pilot: Q08 (paper), Q25 (open problem), Q27 (disagreement question).** Do all six steps for the
   three, then stop and report. Claude reviews; the owner looks. The formats above change if the pilot
   shows they should.
2. **The other 14: every `spec.md` first, nothing computed.** Report; Claude reviews the definitions.
3. **Compute, check, freeze** the 14. Report.
4. **Review.** Claude checks every task. The owner spot-checks five frozen rubrics: at least two paper
   tasks, one open problem with an answer key and one disagreement question.

## Reports

`$EVAL/reports/references-<step>.md`, and a short summary to the owner. Per task: its `spec.md`, its
`values.json`, its `checks.md`, the open points, and the time it took. These 17 questions use public data,
so their numbers may be shown to the reviewer. This will not hold for the CMOMS questions: their references
never leave the server.
