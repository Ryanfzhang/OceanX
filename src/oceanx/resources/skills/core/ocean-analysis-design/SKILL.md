---
name: ocean-analysis-design
description: Select statistical methods for weighting, baselines, autocorrelation and uncertainty in ocean comparisons, trends and anomaly analyses.
metadata:
  origin: oceanmind
  roles:
    - statistical_inference_expert
---

# Ocean Statistical Methods

## when_to_use
Use when answering a statistical subquestion. Choose the methods it needs, not every method below.

## Weighting and aggregation

Weights express the estimand: cell area for a spatial mean, wet volume for a volume mean,
duration for a time-integrated mean, or sampling weights for a sampling design. Equal-month
and duration-weighted averages answer different questions; retain a user-specified convention.
Do not assume latitude-cosine weights fit an irregular or curvilinear grid when cell areas exist.

Use monthly means as the usual starting point for seasonal to interannual background evolution.
Use daily means for short-lived events, their onset and recovery; retain finer resolution when the
question concerns variation within a day. Use annual means for whole-year comparisons, or annual
totals for cumulative budgets, when within-year timing is not the target. In a paper reproduction,
follow the paper's plotted time resolution. Average only when the input sampling supports that scale;
do not average to a coarser scale merely to simplify a plot or reduce computation.

## Baselines and anomalies

Define the reference population/period, aggregation order, calendar, seasonal treatment and
missing-data convention. Spatial contrasts, deviations from one year's mean and anomalies
relative to a multi-year climatology are different quantities. A single year cannot supply an
independent multi-year climatology. Separate the baseline and target windows explicitly.

Removing a trend or fitting a seasonal cycle changes the question; use it when warranted rather
than automatically. A fitted component is not proof of a physical mechanism. For prediction or
held-out validation, estimate preprocessing from the training data rather than leaking test data.

## Smoothing for a short record

Choose a smoothing window in time units for the process of interest, considering sampling gaps and
the valid span left at the endpoints. For descriptive display without a prescribed physical cutoff,
start with a window no longer than roughly 20-25% of the record duration. This is a display heuristic,
not a universal scientific threshold; save the unsmoothed series and state the chosen window.
Do not choose a window to obtain a desired sign, correlation or resemblance to a published figure.
Apply consistent temporal treatment to series being compared, or explain why their treatments differ.
Compute and save the smoothed series in the analysis step, before plotting. A shorter window describes
a different timescale; it cannot recover long-period variability unsupported by the available record.

## Autocorrelation and dependence

Timestamps or neighboring grid cells are not automatically independent replicates. Examine
dependence at the scale used for inference; distinguish seasonal/trend structure from residual
autocorrelation. An observation-index lag is not a fixed time lag with irregular sampling.
The [statsmodels ACF documentation](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.acf.html)
describes its missing-data options and confidence-interval assumptions; choose rather than
silently inheriting them.

For uncertainty under dependence, use a model or resampling scheme appropriate to the actual
sampling: for example temporal/spatial blocks or dependence-robust regression uncertainty.
Explain the block/lag scale and relevant assumptions. A longer series with dependent samples
does not justify treating its raw length as the independent sample size.

A running mean shares values between neighbouring points. Record duration divided by window duration
is a warning about limited temporal support, not an effective sample size or a significance test.
For trends and correlations, state whether the estimate uses the original or smoothed series and
account for its dependence; a smoother-looking curve does not add independent evidence.

## Uncertainty and comparison

Report the effect estimate with units and uncertainty appropriate to that estimand. Separate
natural variability (such as daily standard deviation), uncertainty in a mean/trend and
uncertainty due to model or baseline choices. Mean divided by daily standard deviation is not
a significance test. For paired data preserve pairing; for dependent data preserve the
dependence in resampling. Do not infer confidence bounds from variability alone.

If many comparisons or a data-selected peak support the claim, account for selection/multiplicity
or label the result exploratory. Apply sensitivity checks to choices that could change the answer,
not as an automatic additional study. Report insufficient precision or unresolved assumptions
when the data cannot support the proposed inference.

## research_objective
Translate a scientific question into inspectable selections, transformations, comparisons, and falsifiable checks that an agent may later implement in editable code.

## questions_to_resolve
- What spatial, temporal, vertical, and variable selection is scientifically intended?
- Which baseline, aggregation, area or volume weighting, mask, and seasonality treatment are defensible?
- Which dependence, uncertainty, or alternative choices could change the requested answer?

## Numerical validation
Select assumptions and checks relevant to the scientific conclusion. For a formal hypothesis test,
identify the discriminating observations before examining the outcome; label chance findings as
exploratory. Baselines, weights and uncertainty methods depend on the data and question.

Before scaling up a consequential transformation, test its non-obvious assumptions on a small,
hand-checkable example. Select checks for the operations actually used, not an exhaustive audit:

- For column indexing, masks, flattening or broadcasting, the
  [array-operations Skill](/skills/xarray-array-ops/SKILL.md) provides executable checks
  and examples. Read it when those operations are involved.
- For vertical or spatial integrals, verify weights against the actual wet integration interval or
  area, including partial boundary cells. Integrating a constant should recover that constant times
  the intended thickness or area; averaging it should recover the constant.
- Put compared budget terms in common units and use the same selections, masks, and conventions.
  Derive figures and reported summaries from those checked series, not separately converted copies.
- In weighted means, restrict both numerator and denominator to the same finite values and valid
  weights; an all-missing selection is missing, not zero. Derivatives and vertical integration can
  remove cells that were valid in the source, so derive validity from the resulting diagnostic.
  Compare terms on common support or quantify the coverage difference. For area fractions, state
  whether the denominator is wet ocean, valid observations, or the full geographic box; do not
  silently include land or unsampled cells as negative observations.

Preserve the relevant check outputs with the calculation. If a check fails, repair the affected
computation and its dependent figures or claims; formatting an old result does not repair it.

## Interpretation
Explain whether a result describes an observation, supports an association, or distinguishes
competing explanations. Keep weighting, baseline and selection choices inspectable.
If reasonable methods disagree, quantify or report the material difference. Preserve unresolved
limitations that could change the answer rather than describing an unperformed check as passed.

<!-- oceanx:lessons max=6 for="expert" about="baseline, weighting, dependence or uncertainty choices that changed or invalidated a statistical result, and checks that caught such an error" -->
<!-- /oceanx:lessons -->

## relevant_references
Read `references/methods/anomaly.md` for anomaly definitions, `references/methods/trend.md` for
trend estimation, or `references/coding/large-array-practices.md` for large-array execution only
when the analysis involves that method.
