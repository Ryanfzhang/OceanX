---
name: ocean-dataset-diagnosis
description: Read before computing when supplied data have unresolved coordinate, unit, grid, calendar, product-identity or coverage conventions.
metadata:
  origin: oceanmind
  roles:
    - ocean_process_expert
    - statistical_inference_expert
    - literature_reproduction_expert
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

Retain the provider/product version and relevant subset or processing history with the input identity.
Before time aggregation, confirm the calendar, time units, interval bounds and timestamp meaning;
do not silently convert a non-Gregorian calendar or treat incomplete periods as complete ones.
Before a map overlay, establish the source CRS, coordinate registration and cell bounds rather than
matching the images by eye. Use the references below for unresolved conventions.

## quality_gates
Never assume a positive-down depth, Gregorian calendar, regular grid, or Celsius/Kelvin conversion without evidence.

## stop_or_escalation_conditions
Explain which conclusions are limited if material coordinate semantics, units, grid metrics or calendar remain unresolved.

<!-- oceanx:lessons max=4 for="expert" about="properties of a supplied data product (resolution, coverage, processing, missing fields) that limited what an analysis could conclude" -->
<!-- /oceanx:lessons -->

## relevant_references
`/references/data/cf-conventions.md`, `/references/data/calendars.md`, `/references/data/grids-and-coordinates.md`, `/references/data/common-variables-and-units.md`, `/references/data/common-datasets.md`.
