# Six indicators per task type

**Status: v2.0, the Owner's rule of 2026-10-10.** A task type has six indicators. They count the same,
each is one number from 0 to 100, and an attempt's score is their mean. v1.x (2026-10-06 to 2026-10-09)
mixed a judged part, a counted part and delivery into every indicator, beside a rubric total with weights
of its own. The Owner found that too complicated; what changed is listed at the end, and the old text is
in git history.

## The rule

1. **One indicator, one number.** An indicator is the judge's level (0 to 4, in steps of a half) of the
   criteria it names, as a share of the top level: `100 * level / 4`. One indicator is a count instead:
   right verdicts.
2. **The six count the same.** An attempt's score is the mean of its six indicators, so each is one sixth
   of the score.
3. **Averages.** Per arm and task type, an indicator is averaged over the questions, over the repeats of
   a question first. The six means make up the arm's mean score in the same way.
4. **Nothing executed.** An attempt without a score file counts 0 in every indicator.

Nothing else enters a score: no count of answer-key items or probes, no delivery, and no weight of a
rubric criterion except the weights of the findings among themselves. `evaluate.py` computes the scores
from the levels. The judge adds nothing up.

## Open problems (Q11-Q30)

| Indicator | The question it answers | 一句话 | From the rubric |
|---|---|---|---|
| Framing (问题拆解) | Is the question turned into testable hypotheses? | 问题拆成可检验的假设了吗 | `F` |
| Correctness (正确性) | Do the key results agree with the reference? | 关键结果与参考答案一致吗 | `Q` |
| Depth (深度) | Is the mechanism tested in the data? | 机制用数据检验了吗 | `M` |
| Breadth (广度) | Are related processes and published work connected? | 联系了相关过程和已有研究吗 | `B` |
| Robustness (稳健性) | Does the conclusion hold under other choices? | 换一种设定结论还成立吗 | `R` |
| Rigor (严谨性) | Are the data handled right and the limits stated? | 数据用得对、边界说得清吗 | the mean of `A` and `I` |

## Paper verification (Q01-Q10)

| Indicator | The question it answers | 一句话 | From |
|---|---|---|---|
| Finding tests (命题检验) | Is each finding tested properly? | 每个命题都认真检验了吗 | the findings `K1`...`K5`, each by its weight in the rubric |
| Right verdicts (判定正确) | Do the verdicts agree with the reference? | 判定与参考答案一致吗 | the share of findings with `matches_reference` true |
| Method fidelity (方法忠实) | Are the paper's definitions and methods followed? | 按论文的定义和方法做了吗 | `M` |
| Differences explained (差异归因) | Are the differences from the paper explained? | 与论文的差别解释了吗 | `D` |
| Robustness (稳健性) | Do the verdicts hold under other choices? | 换一种设定判定还成立吗 | `S`, judged beside the rubric |
| Rigor (严谨性) | Are the data handled right and fit for the findings? | 数据用得对、适合检验吗 | `A`, judged beside the rubric |

No paper rubric holds a criterion for the last two. The judge scores them beside the rubric, with the
level descriptions of the open problems' criteria `R` and `A` (`CODEX_JUDGE.md`, "Added criteria of paper
verification"), in a file of their own. Until they are judged, the two indicators and the score of the
attempt stay empty. Nothing is filled in for them.

The report criterion `R` of the paper rubrics (report and traceability) enters no indicator (Owner's
decision of 2026-10-10). The frozen rubrics hold it, so the judge still scores it. A number that cannot
be traced still earns nothing: that is a gate of the rubric and a rule of the judging.

## Delivery

Delivery is reported beside the scores and is part of none.

**Delivered** means: the attempt that is judged ended with a final answer that rests on analysis executed
in that attempt. A plan, a note that the work could not be done, or a message that work is still running
is not a delivery, whatever the status says.

- **Who records it.** The judge, for the attempt it judges, as `delivered` in the score file
  (`CODEX_JUDGE.md`, "Delivery"). An attempt whose report is whole and rests on executed analysis is
  delivered although its recorded status is not `completed`.
- **Void attempts** (Owner's decision of 2026-10-09). An attempt that failed for a reason outside the
  method (a fault of the runner, the sandbox, the data mount or the model provider) is void. The question
  is run again, and the void attempt enters nothing. The owner decides, and the reason is recorded.
- **Attempts that were replaced are listed beside the results**, void or not, each with its reason and
  without a score: a reader has to see that a question was run more than once.

Also beside the scores: what the judge records with the levels (answer-key results, probes, candidate
causes), which is the evidence for the levels and is read when a level is disputed; and repeated failures,
whose counts cannot be compared between methods (trial of 2026-10-06). Time and tokens are not reported
with the results (Owner's decision of 2026-10-10).

## What is reported

```bash
python benchmarking/evaluation/evaluate.py indicators --map <blind map> --scores <score files> \
  --added <added files> --out <folder>
```

It writes `indicators.md` (per task type: the six indicators and the score of every arm, and the numbers
beside them), `indicators.json`, and the chart `six-indicators.png` and `.svg`: one six-axis chart per
task type, every axis with the indicator's name and the question it answers, each arm's score under the
title. The chart shows three arms at most (`--arms` names them and their order).

An indicator that is not judged yet is named, stays empty in the table and leaves a gap in the chart, and
the command ends with status 1 until none is left. `evaluate.py summarize` compares arms on the same
scores and refuses an attempt whose score is not complete.

The two task types are never averaged into one chart: their indicators are different things. The list of
replaced attempts is written by hand into the report of the batch.

## Changes after the first formal judging

The 51 answers of the three-method comparison of 2026-10-10 were judged under v1.2. The Owner then changed
how the levels are added up, having seen the results. The levels the judge gave are unchanged. A report of
that comparison under v2.0 says so and names what changed:

- **Weights.** Before, the weights of the rubric made the total: for open problems answer and mechanism
  20 each, robustness and breadth 15, framing, data and insight 10; for paper verification the findings
  70, and method, differences and report 10 each. Now the six indicators count the same.
- **Parts.** The counts (answer-key items, probes, causes tested, verdicts given, evidence flags),
  delivery and the two halves of a finding's level left the indicators.
- **Traceability removed.** In that comparison it was 93.8, 100 and 100 for OceanX, Claude Code and
  Finch: all twelve paper answers had level 3.5 or 4, and OceanX lost half a level on two questions for
  figures left from abandoned analyses. The Owner took it out because it looks at the form of the report
  and the methods hardly differ on it.
- **Robustness and rigor added to paper verification,** judged for the twelve paper answers after the
  other results were known, in the blind folders. On the open problems OceanX led on both.

Earlier trials: `benchmarking/reviews/2026-10-06-three-methods/aspect-trial/` (v1.0) and
`benchmarking/reviews/2026-10-08-three-methods-r2/six-indicators/` (v1.1).
