# October 8, 2026 — second bilingual provisional-review refresh

Open `review-en.html` or `review-zh.html`. Per-query comparisons, criterion-level
reasons, strengths/weaknesses, original output figures, answer text and provenance
are followed by a 17-query score table and matching three-method bar chart.

## Replacements

Five newly completed reruns replace the earlier empty deliveries: Claude Q25 and
Finch Q09/Q15/Q24/Q27. Each now has a final answer and executed notebook, not merely
a `completed` flag. Scores are respectively 63.75, 45, 52.5, 40 and 52.5. All 46
other grades, levels, reasons and answer hashes are asserted unchanged against
`../2026-10-08-three-methods/scores.json`. All 51 currently selected deliveries
have executed scientific work. Selection is by latest available terminal attempt,
never best score; `selection.json` records changed paths and answer hashes.

Scientific execution is not correctness. For example, Finch Q24 omits longitude
spacing in cell area (approximately 12× area/volume inflation); Claude Q25's
variance-share normalization omits covariance and is not total-variance attribution.
These and other evidence-based limitations are reflected in grades and warnings.

## Limits

These remain **provisional, identity-known single-reviewer audit scores**, not
official frozen-reference benchmark grades. There is no frozen numerical oracle,
blind independent judge, independent scientific re-execution, complete paper
verification or confidence interval establishing method superiority. The historical
October 6 provisional scoring convention is retained for comparability, rather
than retrospectively applying a newer formal partial-artifact contract.

This is a selective replacement set, not a new matched experiment or causal test
of code improvements. Runtime/model versions may differ between selected attempts.
Time and token totals represent selected attempts only, not cumulative retry cost.

## Figures and portability

26 fresh figures are byte-for-byte copies checked with SHA-256. 471 reused figures
reference `../2026-10-06-three-methods/assets/` or
`../2026-10-08-three-methods/assets/`. **Keep all three report directories together.**
Figures are not scientifically corrected or edited: invalid diagnostics remain
visible with review warnings. No source run files, databases, raw NetCDF, large
arrays or conversations are changed or copied into the HTML package.

Both language editions share `scores.json`. `audit.json` contains evidence/report
hashes; `figure-manifest.json` identifies original image provenance; `qa.json`
records desktop/mobile checks, 497 image hashes and 51 table/chart score matches.
Report timestamps use Japan Standard Time (UTC+09:00).

Helper scripts reproduce this workstation's audit from private read-only evidence
snapshots and the preceding reviewer source. They are not benchmark runners and
do not execute the scientific analyses.
