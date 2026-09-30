---
name: ocean-dataset-diagnosis
description: Establish what supplied Ocean data contain and resolve coordinate, unit, grid or coverage uncertainties relevant to a research question.
metadata:
  origin: oceanmind
  roles:
    - ocean_process_expert
    - statistical_inference_expert
---

# Ocean Dataset Diagnosis

## when_to_use
Use for data familiarization or when an analysis depends on unresolved metadata in a supplied dataset.

## research_objective
Establish what the data can represent and which coordinate or metadata ambiguities could invalidate an analysis.

## questions_to_resolve
- Are longitude convention, latitude order, depth sign, calendar, frequency, units, fill values, and masks explicit?
- Is the grid rectilinear, curvilinear, staggered, or otherwise unsuitable for a direct map overlay?
- What are resolution, chunks, missing ratio, and plausible land or boundary contamination risks?

## evidence_requirements
Link the relevant metadata findings to the supplied files and state what remains unknown.

## process_checkpoints
Distinguish metadata facts from derived quantities. Flag uncertainty rather than guessing a CF convention.

Establish product identity from file attributes, source-variable and source-file records, and
available processing provenance, not the directory name or a label in the query. Distinguish
reanalysis, analysis/forecast, and observations; distinguish native resolution from the delivered
grid after interpolation, regridding, or temporal averaging. If metadata conflicts with the query,
report the discrepancy and its implications for the planned diagnostic. If lineage is incomplete,
keep identity unresolved rather than assigning a familiar product name.

## quality_gates
Never assume a positive-down depth, Gregorian calendar, regular grid, or Celsius/Kelvin conversion without evidence.

## stop_or_escalation_conditions
Explain which conclusions are limited if material coordinate semantics, units, grid metrics or calendar remain unresolved.

## relevant_references
`references/data/cf-conventions.md`, `references/data/calendars.md`, `references/data/grids-and-coordinates.md`, `references/data/common-variables-and-units.md`.
