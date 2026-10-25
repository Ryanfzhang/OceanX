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
Model and reanalysis archives rarely store every term of a budget. Before calling a term missing, derive
it from what is stored:
- pressure from temperature, salinity and sea surface height through the equation of state and the
  hydrostatic relation, `p(z) = rho0 * g * eta + integral(rho * g, z..0)`; from it a layer's
  pressure-gradient torque and the bottom pressure torque;
- the transport and planetary vorticity flux of each layer through a strait from the velocity normal to
  the strait section and the Coriolis parameter;
- advection, tilting and the vorticity tendency from the velocity fields at the archive's time step;
- one remaining term as the budget residual, labelled as a residual, once every other term is computed.
A term is missing only when neither the archive nor the attached sources hold what it needs. Name that
variable, for example the surface wind stress, and the conclusions it leaves untested. Do not substitute
another dataset unless the researcher allows it.

## Matching the paper before interpreting
For the overlapping period, or the same dataset, compare means, magnitudes, signs and trends with the
paper's values, read from its text, tables and figure axes. A difference of more than about a factor of
two, or of sign, comes from a definition, normalisation, unit, domain, mask or sign convention until
shown otherwise: find it before drawing any conclusion.

## Adapting the method to the record
A method built for a long record can fail on a short one. Keep a smoothing window well below the record
length: a 7-year running mean leaves almost nothing of a 12-year record, so use annual means or a shorter
filter. State how many independent values lie behind each trend and correlation, and do not report one
that so few values cannot support; `references/methods/trend.md` covers trend uncertainty. Name each
departure from the paper's method and why.

## Figures
Redraw the paper's figures panel by panel from the reproduced quantities, as you see fit, for example with
matplotlib: the same variables, symbols, units, scales, colour encoding, overlays, reference lines,
annotations and layout. When you can read images, look at the original figure first and compare yours with
it once. Leave out a panel whose data are missing and say why; never fill it with another quantity.

## Reporting
For each of the paper's conclusions give the paper's value, the reproduced value, whether they agree and
the reason for a difference. Keep what was reproduced, what differs and what the data cannot test apart.
