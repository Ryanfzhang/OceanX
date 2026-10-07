# Six indicators per task type

**Status: v1.0, agreed with the Owner on 2026-10-06.** The indicators, what each is made of and how each
part is computed are fixed. Two settings stay provisional until they have been tried on the 51 attempts of
the review of 2026-10-06: the mix of the parts inside an indicator, and whether the repeated-failure measure
stays. After that trial the file is frozen, before any formal judging.

The rubric total says how good an attempt is. The six indicators say in what, on six axes that can be
drawn as one chart per task type. Earlier drafts (seven aspects, four aspects, only the differing aspects)
were rejected by the Owner the same day and are not kept.

## What does not change

- The task rubrics `benchmarking/tasks/Q*/evaluator/rubric.json`: criteria, weights, anchors, answer keys,
  probes. Nothing in them is edited for the indicators.
- The rubric total, the score files, the run folders and `result.json`.
- The judging procedure in `CODEX_JUDGE.md`. The judge scores the rubric criteria and records the counts
  that procedure already asks for; no attempt is judged a second time.

The rubric total stays the main result. The judged parts of the six indicators use up exactly the rubric's
100 points, so the indicators are a division of that total, with counts and run measures added beside it.

## How an indicator is built

An indicator has up to three kinds of part, each a number from 0 to 100:

- **judged**: `100 * sum(weight * score / 4) / sum(weight)` over the rubric criteria of the indicator;
- **counted**: the share of listed items that the judge recorded as met;
- **run**: a measure taken from the attempt's run records.

`indicator = 0.50 * judged + 0.25 * counted + 0.25 * run`. A kind the indicator does not have gives its
share to the judged part, so an indicator with only a judged part equals it. An indicator with only run
parts is their mean. (This mix is provisional, see Status.)

Every part is computed per attempt and averaged over the tasks of the type, per arm; with repeats, over the
repeats of a task first. An attempt without a score file (nothing was executed) counts 0 in every part.

## Open problems (Q11-Q30)

| Indicator | Judged (rubric points) | Counted | Run |
|---|---|---|---|
| Framing (问题拆解) | `F` (10) | none | none |
| Correctness (正确性) | `Q` (20) | answer-key items used by `Q`: pass 1, partial 0.5, otherwise 0; mean | none |
| Depth (深度) | `M` (20) | depth probes addressed out of those listed; on disagreement questions the mean of that share and of candidate causes tested out of those listed | none |
| Breadth (广度) | `B` (15) | breadth probes addressed out of those listed | none |
| Robustness (稳健性) | `R` (15) | none | delivery, repeated failures |
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
| Robustness (稳健性) | none | none | delivery, repeated failures |

The mean of the two `K` halves is the rubric's score for the findings. A finding the rubric marks as not
testable follows its own anchors; stating plainly that it cannot be tested is both the sound handling and
the right verdict. Method fidelity and differences have no count because the rubrics give their focus as
one sentence, not as a list (Owner's decision: judged only, rubrics unchanged).

## Run measures

- **Delivery**: 100 when the attempt's status is `completed` and `answer.md` is not empty, otherwise 0.
  Averaged over tasks it is the share of tasks delivered.
- **Repeated failures**: an execution that fails with the same error as the failed execution just before
  it, by the same agent. `score = 100 * (1 - repeated failures / executions)`; an attempt with no
  execution scores 0. The error is compared by its last non-empty line with whitespace collapsed.
  - OceanX: `state/workspace.sqlite3`, table `code_executions`, per agent thread.
  - Finch: `code_runs.jsonl`. A notebook is replayed whole on every edit, so an error left in an earlier
    cell repeats; whether that is a retry is to be settled in the trial.
  - Claude Code: `events.jsonl`, the results of its command and code tools that are marked as errors.
- **Robustness run part** = mean of the two.
- Not scored, shown next to the chart: elapsed time, tokens and model calls from `result.json`.

## What the judge must record

The counts come from fields the score file already has (`CODEX_JUDGE.md`, "Score file"). They are needed
for every attempt that gets a score file:

- open problems: `answer_key[].result`, `probes.depth_addressed`, `probes.breadth_addressed`, and on
  disagreement questions `causes[].tested`;
- paper verification: `findings[].agent_verdict`, `findings[].matches_reference`, `findings[].evidence_ok`.

Without frozen references (a provisional review) `answer_key[].result` and `matches_reference` cannot be
recorded. Those two counted parts are then left out and their share returns to the judged part.

## What is reported

Per arm and task type: the six indicators, each with its parts, the number of attempts, and next to them
the unscored cost. One table and one six-axis chart for open problems, the same for paper verification.
The two task types are never averaged into one chart: their axes are different things.

## Rules that keep the comparison sound

1. The rubric total stays the main result; the indicators explain it.
2. The indicators are fixed before formal judging. They were chosen after the review of 2026-10-06, so that
   review can describe differences between methods and cannot confirm them.
3. All six axes are always shown, also where methods tie or one is behind.

## Trial on the review of 2026-10-06

`benchmarking/reviews/2026-10-06-three-methods/`: 51 attempts, draft rubrics, no frozen references.

1. Compute the judged parts from the criterion scores already in that review. Nothing is rejudged.
2. From the same evidence record the counts that need no reference: probes addressed, causes tested,
   findings with a verdict, `evidence_ok`.
3. Compute delivery and repeated failures from the run folders, read-only.
4. Give the Owner one table per task type with every part of every indicator for the three methods, and
   say for Finch how its replayed errors were counted. The Owner then settles the mix and the
   repeated-failure measure, and this file is frozen.
