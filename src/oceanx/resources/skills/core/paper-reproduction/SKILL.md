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

## Writing down what the paper requires
Before computing anything, write repro_spec.md in your working directory. For each figure you will
reproduce, give the path of the image that shows it, named in the paper's extracted text, and what the
image and its caption show: panels, variables, units, axis ranges and their multipliers, colour encoding,
fills, overlays, reference lines, annotations and layout. For each quantity, give its definition as read
above and the paper's values you will compare with. Write only what the paper shows or states, mark what
you could not read, and correct the file from the paper, never to fit your results. Read it again whenever
earlier messages have been replaced by a summary.

## One computation per quantity
Fix one computation of each quantity before drawing any figure, and check it: its units, the paper's
magnitudes for the overlapping period, and any identity it must satisfy, such as the area and boundary
forms of Stokes' theorem giving the same circulation. From then on use only that computation: rename or
remove the outputs of the versions it replaced, and compute every series you compare or correlate from
the same samples.
For time derivatives, convert timestamp differences explicitly to the time unit of the reported quantity.
For detrending, evaluate and subtract the fitted trend on the same time coordinate and in the same units
used for fitting. If subsampling replaces a full-period average, compare both on a common subset before
using the approximation, and disclose the sampling.

## Deriving what the data do not store
Before writing code for a vorticity budget or a streamfunction, read
/skills/ocean-physical-consistency-review/SKILL.md, under Vorticity budgets and streamfunctions. Derive a
term from the stored variables before calling it missing. A term is missing only when neither the archive
nor the attached sources hold what it needs. Name that variable, for example the surface wind stress, and
the conclusions it leaves untested. When several terms cannot be told apart, give their sum as the residual
of the terms you computed, labelled with the terms it holds, rather than marking each one missing: where
the paper finds one of them small, the residual tests the others. Do not substitute another dataset unless
the researcher allows it.

## Matching the paper before interpreting
For the overlapping period, or the same dataset, compare means, magnitudes, signs and trends with the
paper's values, read from its text, tables and figure axes. A difference of more than about a factor of
two, or of sign, comes from a definition, normalisation, unit, domain, mask or sign convention until
shown otherwise: find it before drawing any conclusion.

## Adapting the method to the record
A method built for a long record can fail on a short one. Justify any change to smoothing or filtering
using the available record, the timescale being studied and the samples retained. Respect explicit user
requirements, preserve the quantity being estimated, and record the change from the paper's method.
Do not assume that scaling a window in proportion to record length is always appropriate.
Before reporting a trend or correlation of a smoothed series, read /skills/ocean-analysis-design/SKILL.md,
under Autocorrelation and dependence, and judge each trend and correlation by the independent values behind
it. Account for serial dependence when estimating uncertainty from averaged or smoothed series;
overlapping windows do not provide independent samples. Name each departure from the paper's method and why.

## Figures
Before drawing the first figure, read /references/coding/matplotlib.md, under Publication figures.
Reproduce each of the paper's figures as one figure with the same panels, from the reproduced quantities:
the same variables, symbols, units, scales, colour encoding, fills, overlays, reference lines, annotations
and layout. Draw every element the original has, the trend line of each period included; one the record
is too short to support is drawn and marked not significant, never left out. Smoothed curves and their
fills run through the whole record as the original's do, over the raw series drawn faintly behind them at
the paper's time resolution. Before drawing each figure, read repro_spec.md again and, when you can
read images, open the original again, since what you read at the start lies far back in the
conversation. After saving, open the original and yours together, compare them item by item (panel layout,
fills, line styles, axis ranges and their multipliers, panel letters, legends and annotations, text that
crosses a line, lines that run off the axes) and fix every difference the data allow. Deliver every panel you
computed, with any doubt written on it rather than withholding it. Leave out only a panel whose data are
missing, say why, and never fill it with another quantity.

## Reviewing the results
Before answering, read repro_spec.md again and review your results against it: each saved figure beside
the image of its original, item by item as under Figures, and each reproduced value beside the paper's.
Check that every figure and number you report comes from the saved output of the one computation of its
quantity. Fix what the data allow, and report what remains with its reason.

## Reporting
For each of the paper's conclusions give the paper's value, the reproduced value, whether they agree and
the reason for a difference. Keep what was reproduced, what differs and what the data cannot test apart.
