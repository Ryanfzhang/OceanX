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

Agents must not read it. Its normal state is `chmod 700 "$EVAL"`: open to the owner, who is also the user
that makes the references and judges, and closed to everyone else on the server. OceanX and Finch run in
sandboxes that see only their question's data, so their runs need nothing more. Claude Code has host Bash
under the same user: while it runs, the folder is closed (`chmod 000 "$EVAL"`) and no reference or
judging work goes on; afterwards it is opened again (`chmod 700 "$EVAL"`). This keeps an agent from
reading it by accident. It is not a barrier against the same user, so afterwards check that no attempt
touched it: `grep -lE 'eval/(rubrics|references)' <runs>/Claude/*/attempt-*/events.jsonl` should list
nothing.

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
   written. Propose another only when the reference work itself shows that it cannot be applied as
   written, for example a relative tolerance ("+/-30%") on a reference value that does not differ from
   zero. Write the reason in `open-points.md` and wait for the owner. A tolerance is never set from what
   any method answered.

   Two additions need no new decision. The report lists every place where either sentence was added.

   *A value near zero* (Owner, 2026-10-08). Where a tolerance asks for a sign or a relative size and the
   reference value does not differ from zero, the frozen tolerance keeps its wording and gains this
   sentence: "a value that does not differ from zero in the reference agrees when the agent's value lies
   within the reference's 95% interval or is reported as not different from zero". `expected` then gives
   that interval.

   *A tie* (Owner, 2026-10-09). Where a tolerance asks for a ranking, a first place or one of several
   categories ("ranking exact", "top relation exact", "main pathway exact") and the reference cannot tell
   two entries apart, the frozen tolerance keeps its wording and gains this sentence: "entries that the
   reference names as tied may come in any order, and any of them may be named first". Two entries are
   tied when the 95% interval of the difference between their deciding numbers includes zero. Take the
   difference inside the same resampling that gives each number its own interval: between the absolute
   values of two correlations, between two seasons year by year. `expected` then names the tied entries.

   Which pairs are tested follows from what the tolerance asks: for a first place, the first entry
   against every other; for the rank of one entry, that entry against every other; for a whole ranking,
   every pair. A tie holds between the two entries tested and does not pass along a chain: A tied with B
   and B tied with C does not make A tied with C. Where no tie touches what the tolerance asks (a peak
   season that is told apart from every other season), the sentence is not added, and `expected` names
   only the ties that bear on the tolerance.
5. **Do not guess.** When a procedure is ambiguous, when the supplied data cannot give the quantity, or
   when the paper says something else than the rubric, do not choose silently. Record it in
   `open-points.md` with the options and what each would change, leave that place unfilled, and go on with
   the rest. A change to a rubric's wording is the owner's. It is made in the repository before freezing,
   with a new `rubric_version`.
6. **A reference says what the supplied data give.** For a paper task this can be "not reproduced" or
   "not testable with the supplied data"; an agent that reports the same earns full marks. Do not bend a
   reference towards the paper.

## Which label a result gets

The pilot (Q08, Q25, Q27) showed that a label needs rules of its own. These hold for every task.

**A paper finding.** Compare what the supplied data give with what the paper states, using the item's own
tolerance, the same one the judge later uses between an agent and the reference.

| Label | When |
|---|---|
| `reproduced` | Every part of the claim holds: the pattern is there, and each number the claim states agrees within the tolerance. |
| `partly reproduced` | The pattern is there but a stated number is outside the tolerance, or one part of a claim with several parts holds and another does not. |
| `not reproduced` | The pattern is absent or opposite. |
| `not testable with the supplied data` | The data cannot decide. |

A finding the rubric marks `partly testable` gets the label of its testable part, and its `expected` names
what cannot be tested. `not testable with the supplied data` is for a finding of which no part can be
decided. Where the data follow a feature for a part of the paper's period only (an eddy that is lost
half-way), the label is given on that part, `partly reproduced` at most, and `expected` says where the
record ends.

The numbers that decide a label are the ones the claim and its tolerance name: "up to 9.7 C" is the
largest value in the paper's period, compared once. Other numbers in `paper_evidence` are shown beside the
result and decide nothing.

Where a claim says two things and the paper has a diagnostic for each (where a layer lies; how uniform it
is), and the supplied data meet one and not the other, the claim holds in part: `partly reproduced`, with
both results in `expected`. Two ways of measuring one quantity (a mixed-layer depth from temperature or
from density) are not that: they are definitions, and the next paragraph applies.

**More than one legitimate definition.** The primary definition is the paper's own diagnostic, or the
closest the supplied data allow (paper tasks), and the reading the rubric's `procedure` names first (open
problems). Where neither names a value for a threshold, the value the literature documents is primary (the
17 cm sea-surface-height contour for the Loop Current) before a round number. `expected` gives the primary
value and label first, then the range of the value over the other definitions, naming those that change
the label. Each definition's own value stays in `values.json`. A spread between definitions wider than
the tolerance is not an open point: the judge compares an agent with the reference computed under the
definition the agent states (`CODEX_JUDGE.md`). It is an open point only when no definition can be called
primary.

**The region is a definition too.** An agent is told the region by its name in the question and sees the
supplied box. It is not told the benchmark's analysis box (`masks` in the data manifest). Where the
supplied box reaches into water the question does not ask about, or the quantity grows with the region (an
area, a total), give every item for the region the question names (primary), for the analysis box and for
the whole supplied box, and give an area also as a share of the region's ocean. In a paper task the
primary region is the paper's. A region drawn by coordinates is checked against the native mask: no water
of the neighbouring basin inside it.

**A reference is a value, not a bound.** Where a definition leaves a case open, take the reading the
definition implies, say so, and give the other reading as an alternative. A column warmer than 26 C down
to the seabed has its heat content above 26 C integrated to the seabed; it is not unknown.

**A candidate cause** (disagreement questions) is one of two kinds (the second kind is the Owner's decision
of 2026-10-08, the wording for counts, dates and rates that of 2026-10-09). Each entry of `spec.md` says
which result gives which label before anything is computed.

*A choice of method* (a definition, a baseline, a threshold, a record length, a product). Judge it by what
the choice does to the question's main answer, on a common footing: a longer season has more days, so
compare rates, not totals.

| Label | When |
|---|---|
| `supported` | The choice changes the conclusion: the sign of the result, or whether it differs from zero under statistics that allow for autocorrelation. For an answer that is a count, a date or a rate: the choice moves it by more than twice the tolerance, so that no value agrees with both answers. |
| `partly supported` | The conclusion stands, but the size changes by more than the tolerance of the answer-key item it bears on. |
| `not supported` | The test shows no such change, or the supplied data cannot show the cause at work. The `why` says which. |

Changing a definition on one record is a paired comparison, so the sampling uncertainty of the answer is
not the yardstick, and a date has none. Where the cause is the length of the record itself, the two ends
of the answer's 95% interval stand for the two choices.

*A physical mechanism* (a wind, a wave, an intrusion). Judge it by the relation the rubric's `test`
predicts.

| Label | When |
|---|---|
| `supported` | The relation is there, differs from zero under statistics that allow for autocorrelation and the length of the record, and holds under the listed definitions. |
| `partly supported` | The relation has the predicted sign but does not differ from zero, or it holds in some years or under some definitions only. |
| `not supported` | The relation is absent or opposite, or the supplied data cannot show the mechanism at work. The `why` says which. |

Where the main answer has several quantities (days, frequency, intensity), the cause takes the strongest
label any of them gives.

**A label at the edge of its tolerance.** A label lies at the edge when the listed definitions, or the
several quantities of one cause, fall on both sides of the tolerance. The reference then says so and names
the neighbouring label: in a finding's `expected`, and for a candidate cause in its `why` (its `expected`
stays one label). The judge accepts either label from an agent whose numbers agree with the reference
(`CODEX_JUDGE.md`, Owner's decision of 2026-10-08).

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

   Write it so that the owner can read it: whole words and plain sentences, one definition at a time,
   every threshold with where it comes from. What all entries share is said once at the top.
3. **Write and run `compute.py`.** One function per entry of `spec.md`, named after its id. It writes
   `outputs/values.json` and whatever small tables or figures help a reader check it:

   ```json
   {"task": "Q08", "catalogue": "2026-10-02-v7", "commit": "<git commit>", "computed_at": "<time>",
    "inputs": ["<bound folder>", "..."],
    "items": [
      {"id": "Q08-K1", "definition": "one line",
       "value": {"layer_top_m": 60, "layer_bottom_m": 240},
       "alternatives": [{"definition": "one line", "value": {"layer_top_m": 55, "layer_bottom_m": 260},
                         "verdict": "reproduced"}],
       "verdict": "partly reproduced", "why": "one or two sentences"}
    ]}
   ```

   An answer-key item has no `verdict`. A candidate cause has `verdict` (supported, partly supported or
   not supported) and `why`. An alternative carries its own `verdict` where that differs.

   `items` hold only the numbers that decide a value or a label. Each has a name that carries its unit, and
   each item a `definition` of its own. An answer-key item gives one value for the question's whole period
   first, then the values by year. Alternatives change one choice at a time from the primary; a grid of
   combinations, like daily series and sensitivity tables, goes into CSV files beside `values.json`.
4. **Check yourself** and write what each check showed in `checks.md`:
   - units and order of magnitude, against a published or textbook value;
   - the task's own deciding numbers again by a second, independent code path (another reduction order, an
     explicit loop on a sub-sample, another library call); a check that several tasks share does not count;
   - closure or conservation where the quantity has one;
   - every other legitimate definition of `spec.md`, and whether the reading of the result changes;
   - the share of missing or masked data in what was averaged;
   - a feature that is followed through time (an eddy, a front, a plume): its position twice a month, the
     largest step from one day to the next, and the paper's positions beside them;
   - paper tasks: the paper's own numbers beside yours. They need not agree; say which do and which do not.
5. **Fill the frozen copy.** Copy the repository's rubric to `$EVAL/rubrics/<task>.json` and change only:
   - a finding's `expected`: the verdict label first, then the reference numbers with units, for example
     `"partly reproduced: low-stratification layer 60-240 m in the reanalysis eddy core (paper: 50-250 m)"`;
   - an answer-key item's `expected`: one value for the question's whole period with units, then its range
     over the years and across the legitimate definitions;
   - every `tolerance`: the suggested text made final, without "to freeze before judging (suggested: ...)";
   - a candidate cause's `expected`: exactly `supported`, `partly supported` or `not supported`;
   - `status: "frozen"`, and in `frozen`: `references_sha256`, `tolerances_frozen_at` (the date) and
     `frozen_by`.

   A finding whose `expected` is already `n/a` (not testable) stays as it is.

   The judge and the owner read `expected`. Write it in a few plain sentences, without JSON: the primary
   result first, numbers rounded to what the tolerance can tell apart, then the range over the other
   definitions and which of them change the label, then the name of the `values.json` that holds every
   definition's full value.
6. **Check the result** and make the rubric read-only:

   ```bash
   python benchmarking/evaluation/evaluate.py rubric-check \
     --rubrics "$EVAL/rubrics" --references "$EVAL/references" --tasks Q08 Q25 Q27
   chmod a-w "$EVAL/rubrics/Q08.json"
   ```

   The command prints the hash of each task's `outputs/` (that is the value of `frozen.references_sha256`)
   and lists what is still wrong. A rubric is frozen when it is listed under `ready`. After that, neither
   the rubric nor its `outputs/` changes.

**Q09.** Its rubric was checked against the full paper on 2026-10-08 (Sosa-Gutierrez et al. 2020,
doi:10.1029/2019JC015397; the owner has the PDF). Two things to carry into its `spec.md`: the paper's eddy
core is the 30 km around the centre, and findings 3 to 5 are results of the paper's regional model for
simulated eddies of 1993-2012, which the question asks to test on the observed eddy of 2016-2017. Since
rubric 3.4 finding 4 is read through the share of the August 2016 gradient that remains at the end. The
paper gives no number for "negligible", so the item's 0.2 is also what the label uses: reproduced when
no more than a fifth remains, partly reproduced when the gradient falls but more remains.

**Q10.** Its rubric was revised from the full text on 2026-10-08 (rubric 3.3; Oh et al. 2024, open
access). To carry into its `spec.md`: the paper's box is 25-34 N, 120-128 E; its heatwave definition joins
one-day gaps; the budget is the paper's Eq. 1 with the entrainment term at the base of the mixed layer,
averaged over each phase from its onset to its peak; and "ocean dynamics" in the paper is mainly that
vertical term, with horizontal advection negative in the box mean.

## Order of work

1. **Pilot: Q08 (paper), Q25 (open problem), Q27 (disagreement question).** Do all six steps for the
   three, then stop and report. Claude reviews; the owner looks. The formats above change if the pilot
   shows they should. (Reviewed twice by 2026-10-08; the formats and label rules above are the result. The
   three are frozen after their corrections have been reviewed.)
2. **The other 14: every `spec.md` first, nothing computed.** Report, together with the pilot's
   corrections; Claude reviews the definitions.
3. **Compute, check, freeze** the 14. Report.
4. **Review.** Claude checks every task. The owner spot-checks five frozen rubrics: at least two paper
   tasks, one open problem with an answer key and one disagreement question.

## Reports

`$EVAL/reports/references-<step>.md`, and a short summary to the owner. Per task the report holds, in
full and not as a summary: its `spec.md`, the `items` of its `values.json`, every `expected` and
`tolerance` as written into the frozen copy, its `checks.md`, its `open-points.md`, and the time it took.
Tables under `outputs/` are named, not pasted, except a small one that a review asked to see (a track of
twenty rows). A report after a review holds what changed since the last one and says what did not. The
reviewer cannot read the server, so what is not in the report is not reviewed. These 17 questions use
public data, so their numbers may be shown to the reviewer. This will not hold for the CMOMS questions:
their references never leave the server.

An open point is settled by the reviewer when it is a matter of reading the rubric, and by the owner when
it needs the rubric's wording or a tolerance changed.
