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
forms of Stokes' theorem giving the same circulation. From then on use only that computation: rename or
remove the outputs of the versions it replaced, and compute every series you compare or correlate from
the same samples.

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
A method built for a long record can fail on a short one. Scale a smoothing window with the record: keep
the share of the record it spans as in the paper, and smooth values at the time resolution the paper
plots, monthly ones rather than annual means. A paper that smooths 28 years with a 7-year window uses a
quarter of its record, so on 12 years use about 3 years; the paper's own window would leave a few points.
Before reporting a trend or correlation of a smoothed series, read /skills/ocean-analysis-design/SKILL.md,
under Autocorrelation and dependence, and judge each trend and correlation by the independent values behind
it. Name each departure from the paper's method and why.

## Figures
The original is the specification. Before drawing the first figure, read /references/coding/matplotlib.md.
Reproduce each of the paper's figures as one figure with the same panels: open the original, list its
panels and what each one draws, and draw every element your data cover from your own values, the
paper's value at most beside yours and a trend too short to hold marked not significant. Keep the
original's axis and colour ranges where your main series fits them. Leave out an element your data do
not cover, such as a period before the record begins, and name it in the answer, never replacing it
with another period or quantity; deliver every panel you computed. Name each file after the paper's
figure, as fig2_layer_vorticity.pdf for Fig. 2: after the run, OceanX puts the original and yours side
by side in one image for you to compare.

## Reporting
For each of the paper's conclusions give the paper's value, the reproduced value, whether they agree and
the reason for a difference. Keep what was reproduced, what differs and what the data cannot test apart.
