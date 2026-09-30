# Native-v5: remove Expert pre-reading, test an unscripted research question

## Scope and status

Question, unchanged from the user's Campeche case:

> What mechanisms drive the formation and persistence of seasonal warm anomalies in the Bay of Campeche, using the provided one-year GLORYS12 dataset?

Read-only source: `/Users/ryanzhang/Code/CMEMS_oceanmind`. Coordinator calls report
`deepseek-v4-pro`; Expert calls report `deepseek-flash` (configured `deepseek-v4-flash`).
This was not an all-Pro test; the original description was incorrect.
explicit user authorization covers this source's summaries/results/paths and API usage.
Separate native task state; no edits to test10, user model settings or the source data.
No roles, execution order or required number of Experts added to the query.

| Item | Status | Evidence / boundary |
| --- | --- | --- |
| Reviewed correction replaces the same public report | Already implemented | Report save and review regression tests; not claimed exercised if no completed review in this run |
| Shared result index removed | Already implemented | Results directories and report paths, not a model index |
| Literature preference checklist removed | Already implemented | Acquisition permission retained |
| Original user question attached | Already implemented | Expert initial-message captures |
| `dataset_context_root` passed | Already implemented | Coordinator cache access retained; v5 ordinary Expert receives source paths instead of another context table |
| Per-Expert review starts on completion | Already implemented | Existing review regression; incomplete executions do not become approvals |
| Incomplete reason in report.md | Already implemented | Live partial reports retain budget failure |
| Absolute no-recompute continuation wording removed | Already implemented | Regression for same-session file reuse; no new science gate |
| Literature presentation template reduced | Already implemented | Paper-selection input fields retained |
| ASCII result suffix | Already implemented | Backend hash of work ID, six hex characters; role readable, question is in report, no model slug field |
| Manifest pre-read in assignment wrapper | Changed this round | Removed from `_participant_spec` |
| Manifest pre-read in public Expert system | Changed this round after observed omission | Initial live capture exposed the second instruction; it was then removed from runtime.py |
| Preloaded plotting API | Changed this round | On-demand scientific-figure-api.md; real model-boundary assertion rejects accidental preloading in test harness |
| Model-side storage/execution-history document | Changed this round | Private manifest reduced to input provenance; no checkpoint/runtime payload injection into ordinary Expert |
| Code tool output / replay | Changed this round | Short streams plus file paths; immutable executed scripts no longer replayed inline |
| Connection retry | Already implemented, not duplicated | Existing 5/15/30/60-second backoff |
| Coordinator prompt / role roster | Not changed this round | Judge actual natural-query dispatch first; no new checklist filter |

## Verification

The first regression run exposed assertions requiring the removed manifest/template
and full code replay. Tests were updated to check real file-based execution, plotting,
same-session recovery and diagnostic preservation instead. No failing tests were skipped.
After the final common-system deletion: **543 tests passed, 4 warnings, 55.34 seconds**
(`tests/test_oceanx`, log `/tmp/oceanx-v5-clean-tests.log`). Ruff F checks and
`git diff --check` also passed. These are regression checks, not a successful live-research verdict.

The first natural-query attempt (`output/campeche-native-v5-20260912`) was stopped:
its real system capture proved that the common Expert prompt still told participants
to read a manifest and included the plotting contract. Only the assignment wrapper had
been cleaned. This was an implementation omission, not evidence of model preference.
Its logs and usage are retained and excluded from a claim that manifest removal worked.

The corrected attempt is `output/campeche-native-v5-clean-20260912`. The harness now
asserts at the captured Expert system boundary that those two injections are absent.
This is a test assertion, not a production rule on scientific behaviour.

## Final diagnostic outcome: not passed

The corrected run was deliberately interrupted after six Expert rounds all returned
`incomplete / budget_exhausted`; the Coordinator was processing their results. No final
research answer or successful completed-review chain was obtained. The test process
exited 130 and its dedicated backend was confirmed stopped. All partial evidence remains.
No new production rules were added in response to these observations.

Observed event window: **13:51:06–14:05:11 UTC, 14 minutes 5 seconds**. The intervals
below overlap for parallel Experts and must not be summed as task wall time.

| Expert round | Model calls | Python calls | Python elapsed (s) | Round wall (s) | Input tokens | Output tokens | Outcome |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Data | 16 | 8 | 4.34 | 94.07 | 303,725 | 11,423 | Budget incomplete |
| Literature, first instance | 19 | 0 | 0 | 177.09 | 316,053 | 13,060 | Budget incomplete |
| Literature, new instance | 11 | 0 | 0 | 132.89 | 291,919 | 10,109 | Budget incomplete |
| Physics, round 1 | 14 | 8 | 2.49 | 101.02 | 308,280 | 13,060 | Budget incomplete |
| Physics, round 2 | 10 | 5 | 10.39 | 143.67 | 312,121 | 23,872 | Budget incomplete |
| Physics, round 3 | 13 | 8 | 14.32 | 146.51 | 332,363 | 24,959 | Budget incomplete |

Expert total: **83 completed model calls; 29 Python calls, 31.54 seconds**.
Coordinator: **14 completed calls plus 1 interrupted call**, 241.51 seconds of recorded
call duration, 377,078 input / 16,285 output tokens. Recorded model-call duration includes
network/provider processing; it is not a measurement of generation time alone.

Corrected run metered usage: **2,241,539 input + 112,768 output**. Of the input,
**1,682,432** was reported as cache-read (a subset, not an extra amount). This explains
why cumulative input is not equivalent to newly generated content or full-price billing.
No API-error calls were recorded; the interrupted call has no returned usage, so this is
observed usage, not an exact invoice.

The earlier stopped run with my missed shared-system instruction separately consumed
**1,945,788 input + 119,282 output** in recorded calls (1,370,752 cache-read input).
It also has one unmetered interrupted call. These costs are not hidden in a claimed
performance improvement. Across both diagnostic runs: 4,187,327 metered input and
232,050 output, plus any unreported interrupted usage.

## Runtime observations

- Corrected first dispatch selected Data and Literature without roles being specified
  in the question. First Data and Literature tools did not read OCEAN_INPUT_MANIFEST.
- Data tried ocean_read_file on the source directory, then the results directory,
  then used Python to list source files. The file reader is scoped to results/session
  evidence, so the source-directory read did not succeed. This observation does not
  establish a permission-free source reader or a zero-overhead start.
- Literature listed task results, listed Skills, then loaded paper-navigator; no initial
  Python manifest probe. Its external searching is distinct from code analysis.
- Data still returned budget_exhausted. Removing manifest pre-reading alone is not a
  demonstration that stopping, delivery or total token efficiency is fixed.
- The second dispatch did **not** contain the Data report path. The Coordinator had
  read saved evidence and instead copied variable/grid/date facts into the physical
  assignment. Its assignment still enumerated anomaly characterization, advection,
  stratification, vorticity and water-mass diagnostics. Thus file access exists but
  path-based handoff and question-led delegation are not reliably demonstrated.
- The second literature assignment used the profile ID, creating a new instance;
  it was not a same-instance continuation. The physical follow-up did use its existing
  instance. Both facts are visible in dispatch/roster records.
- All six completed rounds were `incomplete` with `budget_exhausted`, not API failures.
  The existing per-Expert budget is 320,000 input / 64,000 output tokens, with 85%
  wind-down and reservations for remaining context reads. A budget termination can
  occur below the nominal ceiling; it is not the former 600-second timeout.
- Observed errors included a nonexistent netCDF4 `diskless` attribute, recursively
  inspecting a source directory's `.venv` symlink, missing optional `psutil`, and
  listing a session execution directory outside that code invocation's mounts.
  These are recorded observations, not newly added agent rules or permission changes.
- The Coordinator's third assignment prescribed a six-step script. It also described
  a local anticyclonic feature as having positive `dv/dx - du/dy`; this wording needs
  scientific review rather than being treated as a validated finding. No mechanisms
  should be inferred from these unreviewed work orders.

## Reproduction and raw evidence

```sh
OCEAN_SANDBOX_PYTHON=/Users/ryanzhang/miniconda3/envs/oceanx/bin/python \
MPLBACKEND=Agg .venv/bin/python scripts/verify_file_handoff.py --research \
  output/campeche-native-v5-clean-20260912 /Users/ryanzhang/Code/CMEMS_oceanmind

.venv/bin/python scripts/verify_file_handoff.py --collect output/campeche-native-v5-clean-20260912
```

Use a new output directory for another run. Repeated runs preserve the same question
and source, not shared task history. Comparing to the prior 60-value synthetic test
(26 successful model calls / 22 Python calls / 17.5 seconds of execution) is descriptive,
not a controlled speed comparison: the problem and data differ.

- [First Coordinator context](/Users/ryanzhang/Code/OceanX-v2/output/campeche-native-v5-clean-20260912/handoff-excerpts/first_coordinator_context.json)
- [First dispatch, verbatim](/Users/ryanzhang/Code/OceanX-v2/output/campeche-native-v5-clean-20260912/handoff-excerpts/first_dispatch.json)
- [After first delivery](/Users/ryanzhang/Code/OceanX-v2/output/campeche-native-v5-clean-20260912/handoff-excerpts/after_first_delivery_context.json)
- [Second dispatch, verbatim](/Users/ryanzhang/Code/OceanX-v2/output/campeche-native-v5-clean-20260912/handoff-excerpts/second_dispatch.json)
- [Observed dispatches and file reads](/Users/ryanzhang/Code/OceanX-v2/output/campeche-native-v5-clean-20260912/handoff-excerpts/observations.json)
- [Experts' first three tools](/Users/ryanzhang/Code/OceanX-v2/output/campeche-native-v5-clean-20260912/handoff-excerpts/expert-first-tools.json)
- [Per-work-round model/code counts and times](/Users/ryanzhang/Code/OceanX-v2/output/campeche-native-v5-clean-20260912/handoff-excerpts/expert-metrics.json)
- [Actual model-call timing and usage records](/Users/ryanzhang/Code/OceanX-v2/output/campeche-native-v5-clean-20260912/handoff-excerpts/model-call-metrics.json)
