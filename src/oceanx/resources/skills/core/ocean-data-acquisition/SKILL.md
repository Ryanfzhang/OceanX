---
name: ocean-data-acquisition
description: Handle explicitly requested ocean-data acquisition, including download instructions, user-run scripts or authorized downloads, with verified product provenance.
metadata:
  origin: oceanmind
  roles:
    - literature_reproduction_expert
---

# Ocean data acquisition

Use for an explicit user request for data, download instructions or a user-run script. Execute a
download only when requested, within the authorized destination and access permissions. Missing
inputs during a research analysis do not authorize acquiring replacements.

## Provider references

Read only the reference for the requested product; these are supporting files, not separate Skills:

- Copernicus Marine: [references/cmems.md](/skills/ocean-data-acquisition/references/cmems.md).
- MODIS: [references/modis.md](/skills/ocean-data-acquisition/references/modis.md).
- SeaWiFS: [references/seawifs.md](/skills/ocean-data-acquisition/references/seawifs.md).

## Product selection

Choose variables, spatial and temporal resolution, period, depth, region and processing level for
the requested data. Distinguish observed, simulated and reanalysed products. Find current provider
documentation and verify actual catalog identifiers rather than guessing file names or endpoints.
A bounding-box catalog search does not necessarily crop the downloadable granules.

## Download or user-run script

Prefer documented Python clients or streaming HTTP requests with timeouts, bounded retries and
an explicit destination supplied by the user. Estimate transfer volume and prefer server-side
subsets when available. Do not put credentials into scripts, logs, URLs or Skills.

Write incomplete transfers to temporary files, validate the transfer and available checksum, then
rename. Reuse verified files. HTTP success or a login page is not evidence of a usable dataset.
Check readable variables, coordinates, units, dates and missingness before claiming the download
matches the requested selection. Keep source version, selection and citation alongside it.

Generating a script does not mean it has run or that its outputs are registered Task Sources.
Describe missing authentication, dependencies or inaccessible products honestly.
