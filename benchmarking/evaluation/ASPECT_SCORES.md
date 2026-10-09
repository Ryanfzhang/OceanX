# Six indicators per task type

**Status: v1.2, fixed with the Owner on 2026-10-09.** v1.0 (2026-10-06) left two settings open until they
had been tried: the mix of the parts inside an indicator, and whether repeated failures belong in
robustness. Two provisional reviews settled them: the mix stays and repeated failures leave the indicator.
v1.1 (2026-10-08) read delivery from each question's first attempt; v1.2 reads it from the attempt that is
judged (see "Delivery" for the reason). Nothing here changes once formal judging has begun.

The rubric total says how good an attempt is. The six indicators say in what, on six axes that can be
drawn as one chart per task type.

## What does not change

- The task rubrics `benchmarking/tasks/Q*/evaluator/rubric.json`: criteria, weights, anchors, answer keys,
  probes. Nothing in them is edited for the indicators.
- The rubric total, the score files, the run folders and `result.json`.
- The judging procedure in `CODEX_JUDGE.md`. The judge scores the rubric criteria and records the counts
  that procedure already asks for; no attempt is judged a second time.

The rubric total stays the main result. The judged parts of the six indicators use up exactly the rubric's
100 points, so the indicators are a division of that total, with counts and delivery added beside it.

## How an indicator is built

An indicator has up to three kinds of part, each a number from 0 to 100:

- **judged**: `100 * sum(weight * score / 4) / sum(weight)` over the rubric criteria of the indicator;
- **counted**: the share of listed items that the judge recorded as met;
- **run**: delivery (below).

`indicator = 0.50 * judged + 0.25 * counted + 0.25 * run`. A kind the indicator does not have gives its
share to the judged part. So an indicator with a judged part and one other part is `0.75 * judged + 0.25 *
that part`, one with only a judged part equals it, and robustness of paper verification, which has only a
run part, equals that.

Every part comes from each question's latest attempt, the one the evaluation reads. Every part is computed
per question and averaged over the questions of the type, per arm; with repeats, over the repeats of a
question first. An attempt without a score file (nothing was executed) counts 0 in every part.

## Open problems (Q11-Q30)

| Indicator | Judged (rubric points) | Counted | Run |
|---|---|---|---|
| Framing (问题拆解) | `F` (10) | none | none |
| Correctness (正确性) | `Q` (20) | answer-key items used by `Q`: pass 1, partial 0.5, otherwise 0; mean | none |
| Depth (深度) | `M` (20) | depth probes addressed out of those listed; on disagreement questions the mean of that share and of candidate causes tested out of those listed | none |
| Breadth (广度) | `B` (15) | breadth probes addressed out of those listed | none |
| Robustness (稳健性) | `R` (15) | none | delivery |
| Rigor (严谨性) | `A` + `I` (20) | none | none |

Rigor has no count of untraceable numbers: the rubric's gate already lowers the criterion such a number
supports, and one error is deducted once.

## Paper verification (Q01-Q10)

Each finding's level is divided in two. Up to level 2 it says whether the finding was tested with an
executed diagnostic (0 no executed analysis, 1 an analysis that cannot test it, 2 tested but with a
material flaw). Above level 2 it says whether the test was sound and the verdict right (3 sound and in
agreement with the reference, 4 also complete and compared quantitatively with the paper).

| Indicator | Judged (rubric points) | Counted | Run |
|---|---|---|---|
| Finding tests (命题检验) | `min(level, 2) / 2` of each `K`, by claim weight (35) | findings with a verdict (`agent_verdict` not `missing`) out of all | none |
| Right verdicts (判定正确) | `max(level - 2, 0) / 2` of each `K`, by claim weight (35) | findings with `matches_reference` true out of all | none |
| Method fidelity (方法忠实) | `M` (10) | none | none |
| Differences explained (差异归因) | `D` (10) | none | none |
| Traceability (可追溯) | `R` (10) | findings with `evidence_ok` true out of all | none |
| Robustness (稳健性) | none | none | delivery |

The mean of the two `K` halves is the rubric's score for the findings. A finding the rubric marks as not
testable follows its own anchors; stating plainly that it cannot be tested is both the sound handling and
the right verdict. Method fidelity and differences have no count because the rubrics give their focus as
one sentence, not as a list (Owner's decision: judged only, rubrics unchanged).

## Delivery

**Delivered** means: the attempt that is judged ended with a final answer that rests on analysis executed
in that attempt. A plan, a note that the work could not be done, or a message that work is still running
is not a delivery, whatever the status says. Delivery is 100 or 0 per attempt; averaged over questions it
is the share of questions an arm delivers.

- **Who records it.** The judge, for the attempt it judges, as `delivered` in the score file
  (`CODEX_JUDGE.md`, "Delivery"). An attempt whose report is whole and rests on executed analysis is
  delivered although its recorded status is not `completed` (an early Claude Code runner wrote
  `needs_interaction` whenever a tool call had been refused).
- **Void attempts.** An attempt that failed for a reason outside the method (a fault of the runner, the
  sandbox, the data mount or the model provider) is void. The question is run again, and the void attempt
  enters no indicator. The owner decides, and the reason is recorded.
- **Why not the first attempt** (Owner's decision of 2026-10-09). v1.1 read delivery from each question's
  first attempt, so that the axis would not be 100 for every method once failed questions had been run
  again. But the first attempts of the first batch failed mostly for faults of the runners, which were
  then corrected: a step limit without a warning, a prompt that did not say that a run is one turn, a
  notebook replayed whole within the time limit. Counting them would have charged the methods with the
  harness's faults.
- **Attempts that were replaced are listed beside the results**, void or not, each with its reason and
  without a score: a reader has to see that a question was run more than once.
- **What follows.** In a batch where every failed question has been run again, delivery is 100 for every
  method. Robustness of paper verification then does not separate the methods, and robustness of open
  problems separates them through its judged part alone. Delivery separates methods in a comparison that
  allows no rerun except of void attempts.

**Repeated failures are not part of an indicator.** A repeated failure is an execution that fails with the
same error as the failed execution just before it, by the same agent. The trial of 2026-10-06 showed that
its denominators cannot be compared between methods: a sandbox that counts every shell command, a log of
tool calls, and a notebook replayed whole on every edit. It is reported beside the chart as a diagnostic,
with elapsed time, tokens and model calls.

## What the judge must record

The counts come from fields the score file already has (`CODEX_JUDGE.md`, "Score file"). They are needed
for every attempt that gets a score file:

- open problems: `answer_key[].result`, `probes.depth_addressed`, `probes.breadth_addressed`, and on
  disagreement questions `causes[].tested`;
- paper verification: `findings[].agent_verdict`, `findings[].matches_reference`, `findings[].evidence_ok`;
- for every attempt: whether it delivered (`delivered`).

Without frozen references (a provisional review) `answer_key[].result` and `matches_reference` cannot be
recorded. Those two counted parts are then left out and their share returns to the judged part.

## What is reported

Per arm and task type: the six indicators, each with its parts, the number of attempts, and next to them
the unscored diagnostics. One table and one six-axis chart for open problems, the same for paper
verification. The two task types are never averaged into one chart: their axes are different things.

`evaluate.py indicators --map <blind map> --scores <score files> --out <folder>` computes them and writes
`indicators.md` (the table, each indicator with its parts, and the numbers beside them), `indicators.json`
and the chart `six-indicators.png` and `.svg`. An entry that a score file leaves out counts as not met;
the command names every such entry and ends with status 1 until none is left. The chart shows three arms
at most (`--arms` names them and their order) and carries no numbers: they are in the table. The list of
replaced attempts is written by hand into the report of the batch: the run folders do not always hold
them. The two provisional charts were made by the scripts in their review folders (below).

## Rules that keep the comparison sound

1. The rubric total stays the main result; the indicators explain it.
2. The indicators were fixed after two provisional reviews had been seen. Those reviews can describe
   differences between methods and cannot confirm them.
3. All six axes are always shown, also where methods tie or one is behind.

## Where they have been computed so far

- `benchmarking/reviews/2026-10-06-three-methods/aspect-trial/`: the trial by v1.0 on 51 attempts, with
  all three kinds of part. It is why repeated failures left the indicator.
- `benchmarking/reviews/2026-10-08-three-methods-r2/six-indicators/`: the judged parts and robustness by
  v1.1 on the later review. The counted parts are missing there for the 11 attempts that had been run again.
