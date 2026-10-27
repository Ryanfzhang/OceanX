---
name: paper-reproduction
description: Reproduce or test a published analysis with the supplied data; take each quantity's definition from the paper's methods, derive what the data do not store, match the paper's values before interpreting, adapt the method to the record and redraw the paper's figures.
metadata:
  origin: oceanmind
  roles:
    - coordinator
    - ocean_process_expert
    - statistical_inference_expert
    - literature_reproduction_expert
    - scientific_discussion_partner
---

# Reproducing a paper's analysis

## when_to_use
Use when a request asks to reproduce, test or extend the analysis of a paper the researcher attached or
named. A reproduction computes the paper's quantities as the paper defines them and compares them with
the paper's own values; a similar-looking analysis of the same data is not a reproduction.

## Definitions before code
Before computing anything, read the page image of each page whose equations define the quantities you
will compute: the extracted text names that image above the page and garbles its equations, symbols and
subscripts. Take every quantity from the methods, not from the abstract or the captions: its formula,
integration domain and boundary, vertical limits, whether it is integrated or averaged (divided by an
area, volume or thickness), units, sign convention, grid placement, masking, smoothing or filtering, and
the periods compared. Check each definition by its units against the paper's stated values and figure
axes: a circulation integrated along a boundary over a layer is in m3 s-1, so a figure in m s-1 shows it
divided by an area.

## One computation per quantity
Fix one computation of each quantity before drawing any figure, and check it: its units, the paper's
magnitudes for the overlapping period, and any identity it must satisfy, such as the area and boundary
forms of Stokes' theorem giving the same circulation. Use that checked computation across figures and
compute every series you compare or correlate from aligned samples. When correcting it, check the
replacement before adopting it, regenerate affected saved results and figures, and verify that the
delivered figures read those results rather than an older file or variable. A corrected scratch result
alone does not correct the deliverable. Keep superseded results separate from the selected results;
retain deliberately compared alternatives with their methods labelled.

Sampling, averaging, smoothing and normalisation are part of a quantity's definition.
For direct reproduction, match the paper where the supplied data support it; otherwise state the
adapted treatment and its limits on comparison. A shortcut that changes any of them, taken for time or
memory, is a change of method: compare it with the paper's treatment on a common part of the data and report the difference
before using it.

## Deriving what the data do not store
Before writing code for a vorticity budget or a streamfunction, read
/skills/ocean-physical-consistency-review/SKILL.md, under Vorticity budgets and streamfunctions. Derive a
term from the stored variables before calling it missing. A term is missing only when neither the archive
nor the attached sources hold what it needs. Name that variable, for example the surface wind stress, and
the conclusions it leaves untested. When several terms cannot be told apart, give their sum as the residual
of the terms you computed, labelled with the terms it may hold and the reconstruction errors that can
also contribute. Closure by subtraction does not validate those terms independently. A term found small
in the paper is an assumption to test in this dataset before attributing the residual to another term.
Do not substitute another dataset unless the researcher allows it.

## Matching the paper before interpreting
For the overlapping period, or the same dataset, compare means, magnitudes, signs and trends with the
paper's values, read from its text, tables and figure axes. A difference of more than about a factor of
two, or of sign, comes from a definition, normalisation, unit, domain, mask or sign convention until
shown otherwise: find it before drawing any conclusion.

## Adapting the method to the record
A method built for a long record can fail on a short one. Evaluate the paper's smoothing window
against the available duration, sampling and valid endpoint coverage. When it consumes much of the
record, use /skills/ocean-analysis-design/SKILL.md, under Smoothing for a short record, to select an
adapted display window. Smooth at a time resolution appropriate to the question and supported by the
data. Use the paper's analysis resolution when compatible; otherwise explain the adaptation. Do not
coarsen the series merely for plotting. Save the unsmoothed series and, where supported, the paper-window
result as data; the reproduced figure draws only the selected treatment, in the original's style, and a comparison of windows goes in
a separate supplementary figure. State both windows and the changed timescale.
A physically defined filter is part of the scientific question: shortening it
does not establish the paper's long-period conclusion, and insufficient support must be reported.
Before reporting a trend or correlation of a smoothed series, read /skills/ocean-analysis-design/SKILL.md,
under Autocorrelation and dependence, and judge each trend and correlation by the independent values behind
it. Name each departure from the paper's method and why. Draw a period's trend when it can be
estimated, and label significance only from a valid statistical test. If the record cannot support an
estimate or test, state that limitation rather than calling it not significant. Draw smoothed curves
and fills only where the stated smoothing method produces valid values; do not pad or extrapolate
endpoints to match the original's appearance.

## Figures
Before drawing the first figure, read /skills/scientific-figure-design/SKILL.md, under Reproducing a
paper's figure.

## Reporting
For each of the paper's conclusions give the paper's value, the reproduced value, whether they agree and
the reason for a difference. Keep what was reproduced, what differs and what the data cannot test apart.
