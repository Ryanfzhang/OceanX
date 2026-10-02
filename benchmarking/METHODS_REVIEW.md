# Three-method E10 smoke review

Date: 2026-10-02. This is a diagnostic, post-hoc review, not a registered experiment result.

## Most important finding: the runs are not model-matched

The OceanX attempt's `model_protocol.json` requests `deepseek-flash`, but all 196 completed
model-call ledger entries report `deepseek-v4-pro`. `CallMeter` takes this field from the
returned message's `response_metadata.model_name`. The Claude attempt reports only
`deepseek-flash`, and all 76 Finch ledger entries also report `deepseek-flash`.

The code provides a likely explanation: `benchmark_models.install_oceanx_models()` applies
in-memory overrides in the benchmark gateway process, while `research/launcher.py` launches
a separate `python -m oceanx.research.server` process. The child starts with fresh Python
modules and does not install the benchmark overrides. Environment inheritance does not
propagate monkeypatched functions. The production settings can therefore be used despite
the gateway's Flash configuration record. It was **not changed** by the delivery-only patch.

The subsequent benchmark-only fix starts the production Agent Server through
`benchmark_agent_server.py`, which installs the `.env` model configuration before graph
loading. The production desktop entrypoint is unchanged. `model_protocol.json` is now written
by the actual server and records its PID and loaded role profiles, without credentials.
Regression tests cross the real gateway/server subprocess boundary with stored Pro settings
and benchmark Flash settings; only the final HTTP-serving entrypoint is stubbed, so no paid
model requests run. Both supported wire protocols are covered. The historical runs below
are unchanged; **no corrected OceanX research run has yet been evaluated**. Returned-model
ledger entries must still be checked after that repeat before comparing it to the baselines.

Configuration metadata alone is not proof of the model that executed a run. The saved
returned-model records are stronger evidence, although they are not an independent provider
billing audit. The output-quality observations below remain observations about artifacts;
they do not identify an architecture advantage.

## Runs and descriptive measurements

All three attempts answered E10: compare GLORYS12 product mixed-layer thickness with MLD
derived from monthly temperature/salinity profiles, California/Oregon, 2011–2020. E10 is an
unscored evolution question, not one of the frozen scored test questions.

| Item | OceanX | Claude Code | Finch-local |
|---|---|---|---|
| Experiment | methods-public-r1 | methods-public-r1 | methods-smoke-r2 |
| Attempt suffix | 1790946542667609241-6db883f5 | 1790947807230182876-96fc2d83 | 1790949404902135917-8fb06f82 |
| Runtime outcome | completed | completed | completed |
| Wall time | 47.0 min | 34.3 min | 14.6 min |
| Reported returned model | V4 Pro, despite Flash configuration | Flash | Flash |
| Input tokens, including cached input | 9,719,989 | 17,232,238 | 2,151,921 |
| Cached input, a subset of input | 9,405,056 | 17,050,112 | 1,256,320 |
| Output tokens | 281,112 | 179,435 | 44,158 |
| Call-count evidence | 196 ledger entries | no independently recorded whole-call count | 76 ledger entries, 38 agent steps |
| Saved final figures | 6 registered views/previews | 7 PNGs | 5 PNGs |
| Notebook delivery | hidden per-execution notebooks; collector now exports an execution record | authored analysis.ipynb | native notebook.ipynb, 26 code cells |
| Temporary artifact score | 70.00 | 63.75 | 57.50 |

Token sources differ: OceanX's per-call SQLite ledger, Claude's whole-call `modelUsage`
including subagents, and Finch's router ledger. Cached input is not added a second time.
Claude assistant-message counts are not substituted for model calls. No dollar ranking is
inferred from these totals: models, cache fractions and accounting differ, and CLI-reported
dollar costs are not a provider invoice.

Scores use the same exploratory seven criteria, weights 10/10/20/20/15/15/10, and levels 0–4:

| Criterion | OceanX | Claude Code | Finch-local |
|---|---:|---:|---:|
| Framing | 3 | 3 | 3 |
| Data fitness/handling | 3 | 3 | 2 |
| Quantitative comparison | 3 | 3 | 3 |
| Explanation/causal identification | 2 | 2 | 2 |
| Robustness/uncertainty | 3 | 2 | 2 |
| Relevant breadth/synthesis | 3 | 3 | 2 |
| Insight/limits | 3 | 2 | 2 |

This rubric was written after method identities were known. Core fields have not been
independently recomputed, judge reliability is unmeasured, and the runs use different
models/experiments. These scores are **not evidence that OceanX outperforms the baselines**.
They neither change the official rubric nor turn E10 into a scored test. Notebook/figure
counts, tree size and wall time do not earn scientific points.

## What each method actually demonstrated

### OceanX

The answer contains useful targeted follow-ups on thermal/haline interpretation and
depth/threshold sensitivity. It distinguishes local haline-dominant behavior from a
domain-average thermal result, and includes year-block uncertainty analysis. These are
positive features of this answer, not proof that the tree or multi-agent design caused them.

The cost is more orchestration and a longer run, with 95 saved code executions, 21 failed.
Failures can be ordinary debugging, and their denominator is not comparable to a Finch
notebook cell count. Extra branches should be justified by changed conclusions, corrected
errors or reduced consequential uncertainty, not by the number of checks performed.

The delivery defect was in the benchmark collector: it looked for older receipts rather
than `outputs.json.task_results`. Six valid previews/data files existed even when the
collection reported zero. Fixing this packaging does not improve the science score.

### Claude Code

Claude produced a substantial, flexible single-agent analysis with reusable scripts,
tables, figures and an authored notebook. It tested reference-depth, interpolation and
coarse-graining choices. Its larger cumulative input ledger is predominantly cached and
must not be equated with proportionally higher cost.

The answer nevertheless contains scientific interpretation problems: a universally
one-sided averaging inequality is not established, a temperature/density layer-depth
statement contradicts the sign in a saved table, and archive depth truncation was treated
as evidence of MLD censoring without measuring failed threshold crossings. Many executed
tests do not guarantee correct synthesis.

### Finch-local

Finch provided a compact first-pass analysis quickly, with directly inspectable notebook
cells and five figures. This is the analysis component, not the full Robin workflow, and
it has no literature-search/network tool. Its explicit upstream two-call ReAct reasoning
remains, while provider-native DeepSeek thinking is disabled for mandatory-tool-call
compatibility. This is not identical to the other methods' execution arrangement.

There is a confirmed processing mismatch: the scalar helper interpolates the 10 m
reference, but the vectorized helper used for all 120 months selects the next depth level,
11.405 m. The report nevertheless claims a 10 m reference. Another reported `S(10 m)`
diagnostic actually uses the shallowest model level, 0.494 m. Threshold comparisons and
never-crossed-column checks deserve credit, but reference-depth/interpolation sensitivity
and stronger ocean-state separation are absent.

The notebook retains an early missing-file error; it is an execution history, not evidence
that a clean top-to-bottom restart succeeds. None of the three analyses was clean-replayed
in this audit. No penalty is applied merely because Finch lacked a search tool or did not
use every supplied variable.

## Shared scientific weakness

All three examine threshold differences, but none uniquely identifies the submonthly
averaging contribution from monthly fields. Agreement with a fixed 0.01 density threshold
does not by itself establish the production diagnostic. An algebraic decomposition closes
regardless of whether a residual's causal label is correct.

For Finch, the density-versus-temperature difference is additionally not an independent
third additive contribution to the product-versus-density discrepancy. Its quoted coastal
temperature decrease and salinity increase do not, by themselves, demonstrate T/S
compensation. More computation is not a substitute for a discriminating scientific check.

## Implications for a fair comparison and for OceanX

1. **Verify the actual executing model first.** Test across the real Agent Server subprocess
   boundary and compare requested versus returned model names. Do not continue formal
   same-model comparisons while this mismatch is unresolved.
2. **Separate native-system and controlled comparisons.** Same question/model alone does
   not make literature access, provider thinking, budgets, CPU limits or tools equal. A
   native-system comparison can preserve these differences if declared; an architecture
   claim needs a controlled comparison or suitable ablations. Record actual versions and
   settings and use multiple paired questions/repeats.
3. **Separate science, delivery and cost.** Judge preserved scientific evidence, report file
   completeness separately, and compare reliable accounting under the applicable prices.
   A notebook's presence is not the same as verified reproducibility.
4. **Test the marginal value of follow-ups.** Within OceanX, compare the initial supported
   answer with the final answer under the same model/inputs. Independently verify claimed
   corrections and account for extra time/tokens. A subsequent controlled stopping-policy
   ablation is stronger than simply counting deeper nodes.
5. **Do not claim recursive improvement yet.** This smoke task cannot establish benefits
   from lessons/tools or cross-task evolution. Those require frozen library snapshots,
   untouched held-out tasks and the registered comparison.

The defensible current conclusion is: Finch delivered a useful short first pass; Claude
delivered broader deterministic analysis; OceanX's answer contained deeper targeted
follow-ups. The observed quality/time differences cannot yet be attributed to the methods
themselves. Fix configuration fidelity and evaluate independently checked improvements
before turning these observations into a paper claim.

## Delivery patch verification

Only benchmarking files were changed. The collector copies registered results, authored
reports/code and saved execution cells; it invokes no models or analysis code. It preserves
the original answer byte-for-byte, reports collection gaps separately from runtime status,
and marks the aggregate notebook as an execution record rather than a clean analysis.

Sixteen collector tests passed. A local narrow copy of the saved OceanX E10 attempt yielded
six collected previews and six declared data files, zero collection errors, and an execution
record assembled from 95 saved notebooks. The production desktop, research runtime,
scientific answers, official scoring rules and server checkout were not modified.
