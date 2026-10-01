# Judging procedure (Codex, single judge)

Codex is the only judge. This file is the whole judging contract; `evaluate.py validate` enforces the
score-file format below.

## Preconditions

1. The task's rubric is **frozen** in the evaluator area:
   `$EVAL_ROOT/<experiment>/rubrics/<task>.json` (a copy of `benchmarking/tasks/<task>/evaluator/rubric.json`
   with the evaluator's results filled in, `status: "frozen"`, and `frozen.references_sha256` set).
   Repository rubrics are drafts and are never used to judge. See `EVALUATION.md`, step "References".
2. You judge from the blind folder `$EVAL_ROOT/<experiment>/blind/<blind_id>/` only.
   Do **not** open `blind_map.json`, run folders, `arm.json` or run logs until every score file is written.
3. You never run the agent's code. You may read its code, open its NetCDF outputs to read numbers, and run
   your own reference scripts.

## Order of work for one attempt

1. Read `task.json` (query and status) and the frozen rubric.
2. **Checks first.** For every rubric check (`<task>-X<n>`), find the agent's value in `answer.md`, the reports
   or the published outputs, compare it with the frozen reference within the frozen tolerance, and record
   `pass`, `partial`, `fail` or `not_applicable`. If the agent used a different but stated definition and the
   rubric says to recompute with the agent's definition, recompute and compare against that.
3. **Claims** (paper validation only): record the agent's verdict for each claim and whether its evidence
   was executed and adequate.
4. **Criteria.** Score each criterion 0-4 with the rubric anchors (0, 2 and 4 are written out; 1 and 3 lie
   between). Cite the evidence for each score as paths inside the blind folder (and a figure or section name).
   Use the check results for the "agreement with references" / "quantitative" criteria and the answer key for
   the mechanism criterion.
5. Compute `total = sum(weight * score / 4)` over the criteria (0-100).

## Rules

- Score executed evidence, not plans, length or confident wording. A number that cannot be traced to code,
  a table or a figure counts as unsupported.
- A justified negative or "partly supported" verdict can earn full marks.
- Do not deduct the same root error under several criteria; score its distinct consequences only.
- Paper-validation tasks: the paper's numbers are claims to test, not answers to copy. A different period
  or dataset can legitimately give a different result; reward explaining it.
- Open problems: the mechanism criterion is judged against the frozen answer key (for example the CMOMS
  heat-budget ranking). Partly correct means the dominant term is right but the second is wrong, or the
  ranking is right but untested.
- Disagreement tasks: reward targeted tests that could have shown a cause wrong; a list of plausible causes
  without tests caps the diagnosis criterion at 1.
- Failed, timed-out or empty attempts: write no score file; the summary scores them 0 and counts them.
- Judge all attempts of one task in one sitting, in blind-ID order, to keep the standard steady.

## Score file

One file per attempt: `$EVAL_ROOT/<experiment>/scores/<blind_id>.json`.

```json
{
  "blind_id": "b1a2b3c4d5e6",
  "task_id": "Q17",
  "status": "completed",
  "rubric_version": "2.0",
  "rubric_status": "frozen",
  "references_sha256": "<frozen.references_sha256 of the rubric used>",
  "judge": {"name": "codex", "model": "<model>", "judged_utc": "2026-10-20T08:00:00Z"},
  "checks": [
    {"id": "Q17-X1", "result": "pass", "agent_value": "2020 Jul 25 - Aug 31", "reference_value": "2020 Jul 24 - Aug 30", "note": ""}
  ],
  "claims": [],
  "criteria": [
    {"id": "Q17-C1", "score": 3, "evidence": "evidence/answer.md 'Data'; reports/B1.1/report.md"},
    {"id": "Q17-C2", "score": 4, "evidence": "..."},
    {"id": "Q17-C3", "score": 2, "evidence": "..."},
    {"id": "Q17-C4", "score": 3, "evidence": "..."},
    {"id": "Q17-C5", "score": 4, "evidence": "..."}
  ],
  "total": 73.75,
  "flags": [],
  "notes": ""
}
```

`claims` entries (paper validation): `{"id": "Q07-K1", "agent_verdict": "supported|partly_supported|not_supported|missing", "evidence_ok": true, "note": ""}`.
`flags` records anything the owner should look at: possible leakage of evaluator material, unverifiable
numbers, a reference that looks wrong.

## Calibration before the main judging

Judge three pilot attempts (different task types) twice, in separate sessions, without looking at the first
scores. Report every criterion whose two scores differ by more than one level, and send the three score pairs
to the owner. Main judging starts after the owner accepts them.
