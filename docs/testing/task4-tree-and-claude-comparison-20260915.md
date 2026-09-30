# Task 4: research-tree use, costs, and historical Claude comparison

Read-only inspection of the completed run; no agents resumed and no research outputs modified.

## Sources and comparison limits

- Task: `task_bae91c1e75c44753a9ee89204c4ddfa1`, request `req_desktop_session_submit_0b43a24da9dc42b8b014ce42f71f11c6`.
- Store: `/Users/ryanzhang/Code/test/.oceanx/workspace.sqlite3`, opened read-only. Tables inspected: task_transcript_items, team_work_records, model_call_observations, code_executions.
- Task root: `/Users/ryanzhang/Code/test/OceanX Tasks/4--bae91c1e75c4`.
- Final answer: `analysis/coordinator/0e8ec58f-5089-5c5b-a699-61b1fc70ae8e/10b384c5-cca3-58eb-9f19-73a0150d100d/report.md` under that root.
- Current tree: `analysis/research_tree.json`.
- Historical comparator is **Claude Code with DeepSeek v4 Pro**, not an Anthropic Claude model. Previously verified values are preserved in `output/campeche-file-handoff-20260914-1259/monitoring.md` and earlier audits. Its original `/private/tmp/oceanx-three-arm-pro-20260910-final/results_claude/CAMPECHE/attempt-1789024350691578000-d146a0f0` directory is no longer at that location. It was not possible to re-read that original answer/figures in this inspection. Therefore the historical quantitative comparison is usable, but a fresh head-to-head scientific-quality ranking is not established.
- Task 4 uses Pro for Coordinator/checks and Flash for authors. Historical packaging, wording and literature policy also differ. This is not a controlled tree ablation or cost-normalized model comparison.

## Costs and delivery

Task 4 submission: 2026-09-15 01:46:27 Hong Kong; final report delivered: 02:31:09. Elapsed 2,682.436 s, **44m42s**. Claude historical elapsed 3,596.227 s, **59m56s**: Task 4 is 25.4% shorter.

| Task 4 role | Recorded calls, including summaries | Input | Output | Total |
|---|---:|---:|---:|---:|
| Coordinator | 63 | 1,879,648 | 65,129 | 1,944,777 |
| Physics authors, across initial and follow-up runs | 225 | 8,840,919 | 351,101 | 9,192,020 |
| Literature | 32 | 996,015 | 54,186 | 1,050,201 |
| Thin checks | 40 | 671,459 | 54,876 | 726,335 |
| Visualization | 51 | 1,704,628 | 56,201 | 1,760,829 |
| Total | 411 | 14,092,669 | 581,493 | **14,674,162** |

410 calls completed; one failed Coordinator call has no recorded usage. Of completed calls, 19 were summaries (920,466 input + 60,874 output). Cache reads are **12,269,440**, already included in input. These are recorded token counts, not a dollar bill or a claim of zero unreported provider consumption.

Historical Claude whole-call total: **14,036,436** (uncached input 221,719 + separately reported cache reads 13,604,480 + output 210,237). Task 4 uses **4.54% more tokens**, not fewer.

177 registered code executions: 139 succeeded, 38 failed. Their summed elapsed time is 418.78 s, about 7 minutes, not seven minutes of whole-run wall time. Model durations sum to about 61.4 minutes across concurrent roles; they include network/service/generation and cannot be added to infer serial wall time.

Final published artifacts: one report, **two interactive scientific views**, one supplementary notebook. Q1 cycle/anomaly and Q2 advection figures remain referenced as filenames rather than published result links in the final report. The requested new composite was not rendered. No visual inspection of all panels was performed in this audit, so this is an artifact-presence assessment, not a claim that their rendering is correct.

## Where the tree was genuinely used

Hong Kong timeline, grounded in actual messages and work orders:

1. **01:47:** Q1 (phenomenon characterization) and Q4 (literature) launched independently. Q2/Q3 were explicitly held for Q1's event definitions.
2. **01:54–01:58:** Q4 supplied candidate mechanisms; Q1 returned a thin June anomaly contrasted with deeper Sep/Jan events. Coordinator read the artifacts and rewrote Q2/Q3 with actual dates, structure and amplitude. Both later work orders include Q1's report, array paths and common region definition.
3. **01:58:** Two physics subagents launched for formation and persistence, rather than starting a statistics task solely because that role existed.
4. Q3 tested the literature-inspired freshwater-cap and lateral-retention ideas; the final answers did not simply confirm those hypotheses. The June fresh-cap claim was rejected in the reports; Sep and Jan were differentiated rather than assigned one common persistence story.
5. **02:20:** Coordinator declined a new deep-trend statistical task, giving the single-year identifiability limitation as its reason. It stopped exploring and moved to synthesis/visualization.

This is positive evidence of **evidence-dependent sequencing, shared event definitions and scoped follow-ups**. The tree was not merely drawn after an unchanged batch dispatch. It does not establish that the dictionary itself caused better science than an otherwise identical run without a tree.

The tree still ends as R with Q1–Q4; it mainly refined existing questions rather than growing new branches. That is not a failure: node count or depth is not research value. Conversely, executed flags alone cannot establish that the scientific conclusions are sound.

## Do not count all follow-ups as research gains

- Q2's first follow-up fixed a divergence magnitude error and completed an omitted event-window budget; its second fixed the sign in prose. These are correctness/completion costs, not new research directions.
- Q3's follow-up resolved an inconsistent salinity profile and completed missing decay tests, with one additional winter-barrier-layer question. This mixes repair with inquiry.
- Those three author follow-ups together consumed **4,527,173 tokens (30.9% of the run)**, excluding associated checks.
- Five thin checks all reached eight recorded model calls; two finished with `Handoff failed: Final model response was not a complete text handoff`. Author reports survived and the Coordinator read them. A final report exists despite these failures; the checks did not all deliver normally.
- Visualization was launched only at **02:20:30**, after mechanism results. It was not overlapped with a next scientific question. Its 51 calls consumed 1.76M tokens, and it delivered a numerical synthesis/panel specification rather than the new figure. Visualization plus final recovery/publishing/synthesis occupied the last **10m40s**. The initial programming change enabled native parallelism; it did not make this model choose early visualization.

## Material scientific issues found in this inspection

### 1. A cross-Expert method conflict survived synthesis

Q2's final report explicitly disqualifies the flux-divergence form `-div(u*T)` because interpolated velocities are not discretely balanced; only `-u·grad(T)` is used in Q2's conclusions. Q3's report nevertheless calls its lateral term `-div(u*T)`, and actual executed code confirms it:

`analysis/expert-sessions/01a0a111-ca33-7502-af65-33a6aab92311--4a1a830339b1/executions/codeexec_b068dda43d0841cbb876fdad2511239c/code/analysis.py` computes `Fx=U*T`, `Fy=V*T`, their gradients, then their negative sum. It also substitutes zero flux at NaNs.

The final Coordinator answer accepts Q2's caution but carries Q3's September/January lateral-cooling/warming interpretations forward without reconciling this conflict. Those interpretations require reassessment; no corrected budget was calculated in this audit. This is specifically a **synthesis/coordination failure**, not evidence that the tree needs more fields.

### 2. The reported haline contribution fraction is dimensionally wrong

In Q3 `outputs/q3_series2.py:81–96`, `gsw.beta` feeds `S_contrib = mean(beta * delta_S)` and `f_S = S_contrib / delta_sigma`. GSW beta is `(1/rho) * d(rho)/d(SA)`, so `beta * delta_S` is a fractional density change, not a density change in kg/m³. Comparing it with `delta_sigma` without the density factor understates the scale by approximately 1,000.

Official definition: [TEOS-10 notes on beta](https://www.teos-10.org/pubs/gsw/pdf/beta.pdf).

Read-only checks on saved `q3_series2.npz`, 30 m index:

| Month | Saved mean f_S | Multiply by 1,025 for scale illustration only |
|---|---:|---:|
| June | 0.00003605 | 0.03695 |
| September | 0.00033912 | 0.34760 |
| January | 0.00087082 | 0.89259 |

These are not a recomputed physical decomposition: spatial averaging, density choice and nonlinear effects still need correct treatment. They show why “f_S is almost zero all year” is not supported by the code. The more specific June salinity-profile observation may still support absence of a fresh cap; it should not be conflated with the invalid all-year quantitative fraction.

### 3. Four-event rank significance is overstated

The final report prints Spearman rho=-1 with p=0.000 for four events. Direct enumeration of the 4!=24 rank permutations gives two equally extreme cases, so the exact two-sided p-value is **2/24=0.08333**, not zero (under the exchangeable, no-ties null). That still does not address seasonal confounding or fit uncertainty. SciPy itself recommends permutation tests for small samples: [spearmanr documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.spearmanr.html).

The monotonic ordering is a description. It is not sufficient to assert that barrier layers do not confer persistence as a general mechanism.

## Overall assessment

Task 4 is a genuine completed research interaction, unlike prior runs that ended after dispatch. It shows meaningful question refinement and better reuse of a shared event definition. Historical elapsed time improved, but total tokens did not. Repair, late visualization, failed checks and unresolved cross-Expert scientific inconsistencies remain costly.

**Research-tree coordination is working in a limited, observable sense; scientific superiority over the historical Claude run is not established.** The next priority suggested by this run is correct numerical evidence and reconciliation of conflicting methods in final synthesis, not more tree schema, more branches or another blanket rule about how many agents to launch.
