# October 8, 2026 — bilingual provisional artifact-review refresh

Open `review-en.html` or `review-zh.html`. Each query has a three-method score
comparison, criterion-level reasons, strengths/weaknesses, original figures,
submitted answers, provenance and recorded duration/token cost. The last section
contains all 17 query scores and a matching bar chart.

This is **not an official frozen-reference benchmark grade**: no frozen numerical
oracle, no blinded independent judge, no independent scientific re-execution.
It retains the October 6 provisional scoring convention for comparability, not
a retrospective application of a newer formal partial-artifact scoring contract.

## Refresh scope

The latest available terminal attempt is selected by directory timestamp, never
by score. Six replacements are newly reviewed: OceanX Q25/Q27, Claude Q15, Finch
Q08/Q20/Q23. The other 45 scores, levels, explanations and answer hashes are
asserted unchanged against the original review. These are selective reruns, not
a new matched A/B experiment. Time totals cover only the selected attempts, not
all historical retry cost. The old OceanX Q25 directory is no longer listed in
the current run root; its prior assessment remains in the historical report.

`selection.json` records selected/superseded paths and answer hashes.
`scores.json` stores identical bilingual scores and criterion reasons.
`audit.json` stores report hashes and checks; `qa.json` records layout validation.

## Figures and portability

46 new output figures are byte-for-byte copies checked with SHA-256. 425 unchanged
figures are reused from `../2026-10-06-three-methods/assets/`. **Keep both report
directories together** when moving or serving this report. Saved invalid or
superseded panels remain accessible with visible warnings; they are not redrawn.
Large arrays, raw NetCDF, checkpoints and full conversations are not copied into
the HTML package. Source run files and databases are not modified.

Report timestamps use Japan Standard Time (UTC+09:00).

## Generation notes

The helper scripts are an audit reproduction for this workstation, not a new
benchmark runner. They use the historical reviewer source and a private read-only
evidence snapshot outside the repository. `refresh_review.py` collects changed
evidence; `fetch_assets.py` copies new figures; `reviewed_cases.py` records the six
manual assessments; `render_review.py` renders both editions; `qa.js` verifies
layout and score/figure consistency. They do not execute scientific analyses.
