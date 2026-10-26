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
Take every quantity from the methods, not from the abstract or the captions: its formula, integration
domain and boundary, vertical limits, whether it is integrated or averaged (divided by an area, volume or
thickness), units, sign convention, grid placement, masking, smoothing or filtering, and the periods
compared. The extracted text of a PDF garbles equations, symbols and subscripts; read the page image of
the methods for them. Check each definition by its units against the paper's stated values and figure
axes: a circulation integrated along a boundary over a layer is in m3 s-1, so a figure in m s-1 shows it
divided by an area.

## Deriving what the data do not store
Model and reanalysis archives rarely store every term of a budget. Derive a term from the stored
variables before calling it missing; /skills/ocean-physical-consistency-review/SKILL.md describes how
for vorticity budgets and streamfunctions. A term is missing only when neither the archive nor the
attached sources hold what it needs. Name that variable, for example the surface wind stress, and the
conclusions it leaves untested. Do not substitute another dataset unless the researcher allows it.

## Matching the paper before interpreting
For the overlapping period, or the same dataset, compare means, magnitudes, signs and trends with the
paper's values, read from its text, tables and figure axes. A difference of more than about a factor of
two, or of sign, comes from a definition, normalisation, unit, domain, mask or sign convention until
shown otherwise: find it before drawing any conclusion.

## Adapting the method to the record
A method built for a long record can fail on a short one: keep a smoothing window well below the record
length and judge each trend and correlation by the independent values behind it
(/skills/ocean-analysis-design/SKILL.md, under dependence). Name each departure from the paper's method
and why.

## Figures
Reproduce each of the paper's figures as one figure with the same panels, from the reproduced quantities:
the same variables, symbols, units, scales, colour encoding, overlays, reference lines, annotations and
layout, drawn as /references/coding/matplotlib.md describes for publication figures. When you can read
images, look at the original figure first, and after saving compare yours with it once and fix what
differs. Deliver every panel you computed, with any doubt written on it rather than withholding it. Leave
out only a panel whose data are missing, say why, and never fill it with another quantity.

## Reporting
For each of the paper's conclusions give the paper's value, the reproduced value, whether they agree and
the reason for a difference. Keep what was reproduced, what differs and what the data cannot test apart.
