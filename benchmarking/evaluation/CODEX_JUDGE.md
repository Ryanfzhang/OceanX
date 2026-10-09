# Judging procedure (Codex, single judge)

Codex is the only judge. This file is the whole judging contract; `evaluate.py validate` enforces the
score-file format below.

## Preconditions

1. The task's rubric is **frozen** in the evaluator area:
   `$EVAL_ROOT/<experiment>/rubrics/<task>.json`. It is a copy of
   `benchmarking/tasks/<task>/evaluator/rubric.json` with the evaluator's results filled in,
   `status: "frozen"`, and `frozen.references_sha256` set. Repository rubrics are drafts and are never used
   to judge. See `EVALUATION.md`, "References and frozen rubrics".
2. You judge from the blind folder `$EVAL_ROOT/<experiment>/blind/<blind_id>/` only.
   Do **not** open `blind_map.json`, run folders, `arm.json` or run logs until every score file is written.
3. You never run the agent's code. You may read its code, open its NetCDF outputs to read numbers, and run
   your own reference scripts.

## The two rubric types

| Type | Criteria | What the rubric holds |
|---|---|---|
| Paper verification (`paper_reproduction`, Q01-Q10) | One per finding (`K1`...`K5`, 70 points), plus method `M`, differences `D` and report `R` (10 each) | For each finding: the paper's evidence, its testability, how to test it, the frozen expected result and tolerance. Also `period_match`: the paper's study period and the supplied data. |
| Open problem (`open_problem`, Q11-Q30) | Framing `F` 10, data `A` 10, answer `Q` 20, mechanism `M` 20, robustness `R` 15, breadth `B` 15, insight `I` 10 | Answer-key items with frozen values and tolerances; depth probes; breadth probes; for disagreement questions, candidate causes with the test for each; sometimes literature context. |

Every criterion is scored from 0 to 4 with the anchors written in the rubric, in steps of half a level
(Owner's decision of 2026-10-09). A half level says that the answer meets the lower description and part
of the next one; the criterion's `evidence` names that part. Where a level is not written out, it lies
between its neighbours.

## Order of work for one attempt

1. Read `task.json` (query and status) and the frozen rubric.
2. **Paper verification.**
   1. For each finding, find the agent's verdict and its evidence in `answer.md`, the reports or the
      published outputs. Record them under `findings`.
   2. Compare the agent's result with the frozen `expected` value within the frozen `tolerance`. If the
      agent used a different but stated definition, recompute the reference with that definition and compare
      against it.
   3. Score the finding with its anchors. A finding marked `not testable` has its own anchors.
   4. Score `M` and `D` against their `focus` lists, and `R`.
3. **Open problem.**
   1. For each answer-key item, find the agent's value and compare it with the frozen value within
      tolerance. Record `pass`, `partial`, `fail` or `not_reported` under `answer_key`.
   2. Disagreement questions: for each candidate cause, record whether the agent tested it and whether its
      conclusion matches the frozen expectation, under `causes`.
   3. Note which depth probes and breadth probes the answer addresses.
   4. Score the seven criteria. Each criterion's `uses` field names what it draws on:
      - `Q`: its answer-key items;
      - `M`: its answer-key items, the candidate causes and the depth probes;
      - `R`: the depth probes;
      - `B`: the breadth probes and the literature context.
4. Apply the rubric's gates. They cap individual criteria, so the total stays the weighted sum.
5. Compute `total = sum(weight * score / 4)` over the criteria (0-100).
6. Record whether the attempt delivered (`delivered`, see "Delivery").

## Rules

- **Executed evidence only.** Score executed evidence, not plans, length or confident wording. A number
  that cannot be traced to code, a table or a figure counts as unsupported.
- **Paper verification rewards the right verdict, not agreement with the paper.** A justified "not
  reproduced" that matches the frozen reference earns full marks. A "reproduced" that the data do not
  support does not.
- **A label at the edge of a tolerance** (Owner's decision of 2026-10-08). Where a label of the reference
  lies at the edge of its tolerance, the reference says so and names the neighbouring label: in the
  finding's `expected`, or for a candidate cause in the `why` of its item in
  `$EVAL_ROOT/<experiment>/references/<task>/outputs/values.json`. There an agent's verdict with either
  label matches the reference, provided its numbers agree with the reference under the definition it
  states.
- **Tied entries** (Owner's decision of 2026-10-09). Where a tolerance asks for a ranking, a first place
  or one of several categories and the frozen `expected` names entries as tied, an agent's answer matches
  with those entries in any order and with any of them named first. Entries the reference does not name
  as tied keep their place. A tie holds between the two entries named and does not pass along a chain: A
  tied with B and B tied with C does not make A tied with C.
- **Delivery** (`ASPECT_SCORES.md`, "Delivery"). `delivered` is `true` when the attempt you judge ended
  with a final answer that rests on analysis executed in that attempt. A plan, a note that the work could
  not be done, or a message that work is still running is not a delivery, whatever the status says. An
  attempt without a final answer, judged on what it kept, did not deliver. Where the runner recorded
  another status than `completed` for an attempt whose report is whole, the report decides; say so in
  `notes`.
- **Numbers that cannot be traced** (Owner's decision of 2026-10-09; how the rubric's first gate is
  applied). A number or citation without a traceable source earns nothing and gets a flag. Score the
  criterion on what remains. The cap at 1 applies only where the criterion's credit rests on that number
  or citation alone. A check that lacks a source must not score lower than the same answer without the
  check.
- **A finding that is partly testable** (Owner's decision of 2026-10-09). The reference labels the
  testable part and names what cannot be tested; an agent was not told this convention. Its verdict agrees
  with the reference when its result on the testable part agrees within the tolerance and it says which
  part the supplied data cannot test, whether it calls the finding by the reference's label or "partly
  reproduced" for that reason.
- **How much a flaw costs** (Owner's decision of 2026-10-09). The levels say what an answer achieved. A
  flaw is material when it changes a verdict, moves a deciding number beyond its tolerance or leaves a
  deciding part of the question untested; for a finding, level 2 is for such a flaw. A flaw that is not
  material is noted and costs half a level at most. A flaw lowers the criteria whose results it changes
  and no other: a track that ends early lowers the findings that need the missing months, not every
  finding. Between two levels give the half level, not the lower one. Level 4 is for an answer that does
  what its description says, not only for a perfect one.
- **Findings that cannot be tested.** Full marks need a plain statement that the supplied data cannot test
  the finding, naming what is missing. Reporting such a finding as verified scores 0.
- **Open problems reward depth and breadth only when executed.** A literature review without analysis caps
  `B` at 2. A mechanism asserted without a test caps `M` at 1.
- **Disagreement questions.** Reward targeted tests that could have shown a cause wrong. A list of plausible
  causes without tests caps `M` at 1.
- **One error, one deduction.** Do not deduct the same root error under several criteria; score its distinct
  consequences only.
- **Attempts that end without a final answer** (Owner's decision of 2026-10-06). Whatever the attempt
  kept is what it delivered, however little. Judge the executed work in the blind folder with the rubric as
  it stands: Expert reports, an executed notebook, tables, figures, and, where there is no `answer.md`, the
  agent's own messages in `partial_answer.md`. A part of the question that the kept work does not answer
  scores as unanswered, and nothing is added for what a finished run might have found. Copy `status` from
  `task.json` into the score file. Write no score file only when nothing was executed; the summary then
  scores the attempt 0 and counts it. A plan, expected values, or numbers with no executed code behind them
  are not executed work.
- **Consistency.** Judge all attempts of one task in one sitting, in blind-ID order.

## Score file

One file per attempt: `$EVAL_ROOT/<experiment>/scores/<blind_id>.json`.

```json
{
  "blind_id": "b1a2b3c4d5e6",
  "task_id": "Q12",
  "status": "completed",
  "delivered": true,
  "rubric_version": "3.1",
  "rubric_status": "frozen",
  "references_sha256": "<frozen.references_sha256 of the rubric used>",
  "judge": {"name": "codex", "model": "<model>", "judged_utc": "2026-10-20T08:00:00Z"},
  "answer_key": [
    {"id": "Q12-A1", "result": "pass", "agent_value": "Spearman 0.82 with the reference index", "reference_value": "threshold 0.7", "note": ""}
  ],
  "causes": [],
  "findings": [],
  "probes": {"depth_addressed": [1, 3], "breadth_addressed": [2]},
  "criteria": [
    {"id": "Q12-F", "score": 3, "evidence": "evidence/answer.md 'Approach'"},
    {"id": "Q12-A", "score": 3, "evidence": "..."},
    {"id": "Q12-Q", "score": 4, "evidence": "..."},
    {"id": "Q12-M", "score": 2.5, "evidence": "..."},
    {"id": "Q12-R", "score": 3, "evidence": "..."},
    {"id": "Q12-B", "score": 2, "evidence": "..."},
    {"id": "Q12-I", "score": 3, "evidence": "..."}
  ],
  "total": 73.75,
  "flags": [],
  "notes": ""
}
```

- **`findings` entries (paper verification):**
  `{"id": "Q05-K1", "agent_verdict": "reproduced|partly_reproduced|not_reproduced|not_testable|missing", "matches_reference": true, "evidence_ok": true, "note": ""}`.
- **`causes` entries (disagreement questions):**
  `{"id": "Q23-H1", "tested": true, "agent_conclusion": "supported", "matches_reference": true}`.
- **`flags`:** anything the owner should look at, such as possible leakage of evaluator material, numbers
  that cannot be verified, or a reference that looks wrong.

`evaluate.py validate` checks the criterion IDs, the levels (0 to 4 in steps of 0.5), the evidence fields,
the total, the frozen status (for every score file, also one of an attempt without a final answer), the
blind ID, the judge and `delivered`. It does not check the other fields; fill them anyway, because the
owner reads them when a score is disputed, and because the six indicators per task type
(`ASPECT_SCORES.md`) are computed from `answer_key`, `causes`, `findings` and `probes`: an entry left out
counts as not met. `evaluate.py indicators` names every such entry and ends with status 1 until none is
left.

## Calibration before the main judging

Judge three pilot attempts twice, in separate sessions, without looking at the first scores: one paper
verification, one checkable open problem and one disagreement question. Write the second set of score
files into a folder of its own. Report every criterion whose two scores differ by more than one level, and
send the three score pairs to the reviewer (Claude), who checks them and tells the owner the result
(Owner's decision of 2026-10-09; before, the owner accepted the pairs). Main judging starts when no
criterion differs by more than one level. A larger difference goes to the owner first.
