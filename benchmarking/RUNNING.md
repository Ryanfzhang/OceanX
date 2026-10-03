# Run OceanX, Claude Code and Finch from one .env

All commands run on the Linux server from `/home/mafzhang/code/OceanX`, with
`oceanx-bench` active. No Docker is used. Finish [INSTALL.md](INSTALL.md), install
Claude Code, and finish the separate [Finch setup](finch/README.md) first.
The three commands do not install dependencies, download data or start learning.

## 1. Configure once

```bash
cp -n benchmarking/.env.example benchmarking/.env
chmod 600 benchmarking/.env
```

Edit the ignored `.env`; do **not** source it. The key is never written to manifests.
The template includes every setting needed by the three commands. The main choices are:

```dotenv
DEEPSEEK_API_KEY=<your key>
BENCH_MODEL=deepseek-flash
BENCH_DATA_ROOT=/import/home3/share/mafzhang
BENCH_OUTPUT_ROOT=/home/mafzhang/oceanx-bench
BENCH_EXPERIMENT=methods-public-r1
BENCH_SUITE=test
BENCH_EVOLUTION_SET=
BENCH_TASKS=available
BENCH_TIMEOUT_SECONDS=10800
BENCH_RESUME=false
```

- `BENCH_TASKS=available`: select all numerically complete questions once; print exclusions.
- `BENCH_TASKS=all`: require every question in the selected suite/set to have complete data.
- `BENCH_TASKS=Q07,Q08,Q09`: require exactly these questions; commas or spaces are accepted.
- For an unscored smoke run: `BENCH_SUITE=evolution`, `BENCH_TASKS=E10` and a new experiment name.
- Evolution round A/B: `BENCH_SUITE=evolution`, `BENCH_EVOLUTION_SET=A` or `B`.
  All 24 evolution questions are selected when that field is empty and tasks are `all`/`available`.
- Optional OceanX library: `BENCH_OCEANX_LIBRARY=/absolute/path/to/frozen/L1` or L2.
  Other methods do not receive it. Learning/review remains an explicit offline step.
- `BENCH_TIMEOUT_SECONDS` is also OceanX's research budget: after 75% of it the Coordinator
  starts no new Expert assignment and finishes with the results it has (135 of 180 minutes).
- Before any model call, `run_oceanx.py` and `check_setup.py` start one sandboxed Python kernel
  and save to its output folder twice; the run stops if that fails.
- Claude executable and approved tools, and Finch checkout, worker/kernel interpreters, steps,
  temperature, execution timeout, memory and CPUs are also configured in this file.

Relative paths resolve from the OceanX checkout, not the shell's working directory.
The data root must already contain the downloaded/staged data **and** `_download_all/`.
Moving data does not migrate old JSONLs; a new experiment generates new absolute bindings.
`BENCH_OUTPUT_ROOT` must be separate from data and source repositories.

OceanX Coordinator/Experts, offline meta-agent/node labels, Claude (including subagents)
and Finch use one model/key. The independent scientific rubric judge is not reconfigured.
OceanX's dedicated benchmark Agent Server loads this file before importing its graphs;
the normal desktop model settings are neither used nor modified. Each attempt's
`model_protocol.json` is written by that server process and includes its PID and the
loaded model/provider/endpoint/token limit for Coordinator, Expert and meta roles, never keys.
This is a loaded-configuration record, not proof of provider billing or returned model identity;
check the per-call model ledger when comparing completed runs.

## 2. Run: three terminals, three commands

With `oceanx-bench` active and the checkout as working directory:

**Terminal 1**
```bash
python benchmarking/server/run_oceanx.py
```

**Terminal 2**
```bash
python benchmarking/server/run_claude.py
```

**Terminal 3**
```bash
python benchmarking/server/run_finch.py
```

Finch's controller starts in `oceanx-bench`; `BENCH_FINCH_PYTHON` points to its separate
Python 3.12 environment. Each method runs its selected questions sequentially.
No `--queries`, `--output`, model flags or exported path variables are needed.

The first command freezes the selection; the others reuse exactly the same JSONL.
An OS lock protects simultaneous starts. Later downloads do not expand that selection.
Changed settings or a damaged selection require a new `BENCH_EXPERIMENT`; the
runner stops instead of silently overwriting the experiment. API key rotation and
changing `BENCH_RESUME` do not change the selection.

```text
BENCH_OUTPUT_ROOT/BENCH_EXPERIMENT/
  inputs/queries.jsonl              shared immutable task input
  inputs/selection.json             task IDs, settings and input hash; no key
  runs/OceanX/                      OceanX attempts
  runs/Claude/                      Claude attempts
  runs/Finch/                       Finch attempts
```

The last folder names follow `BENCH_OCEANX_ARM`, `BENCH_CLAUDE_ARM`, `BENCH_FINCH_ARM`.
Choose distinct names. Each method retains its original output-writer lock and resume checks.

An existing method output is not overwritten. For a new repeat, change the experiment name,
e.g. `methods-public-r2`. For an interrupted batch, set `BENCH_RESUME=true` and rerun the
same command. It skips completed cases and creates new attempts for unfinished ones;
methods without an output folder start fresh. It does not resume an in-flight conversation.
Prespecify retries; do not selectively
retry scored failures. Run under `tmux` to survive SSH disconnection.

Advanced CLI flags still override individual launch defaults. Explicit `--queries`
or `--query` requires explicit `--output` and bypasses automatic selection; do not
mix that workflow with the three-command comparison.

### Repeat OceanX after the model-configuration fix

Earlier OceanX attempts can say Flash in `model_protocol.json` while their returned-model
ledger says Pro: that record used to be written by the gateway, whose in-memory override
did not reach the actual server child. Those attempts cannot serve as Flash results.

After updating the server checkout, keep the same data, suite, task IDs and other scientific
settings, but use a **new** `BENCH_EXPERIMENT` (for example `methods-oceanx-flash-r1`) and
`BENCH_RESUME=false`, then run only:

```bash
python benchmarking/server/run_oceanx.py
```

For the E10 smoke comparison, keep `BENCH_SUITE=evolution`, `BENCH_EVOLUTION_SET=` and
`BENCH_TASKS=E10`, with `BENCH_MODEL=deepseek-flash`. Do not delete or overwrite the earlier
OceanX, Claude or Finch attempts. Changing runner source files invalidates the old automatic
experiment selection, so a new arm name alone is not sufficient. The new query bindings
must match the old query text and datasets before using the earlier baselines as comparators.
This smoke repeat diagnoses the corrected model routing; it is not a new formal A/B claim.

## OceanX review delivery

If a follow-up attempt leaves its question's nonempty `report.md` unchanged, OceanX
delivers that report and its original Summary; a short closing reply is added only to
the Coordinator receipt. The closing reply becomes the report only when no nonempty
report exists, for the Discussion Partner, or when it contains a nonempty `## Summary`.
Without closing prose, the receipt explicitly says so and gives the model-call stop reason.

The OceanX runner automatically creates a new `runs/OceanX/collected/collection-*`
folder after the batch. Open its `index.md`, then each attempt's `review.md` for the
answer, figure gallery, registered result data and links to saved reports/code.
The collector reads `outputs.json.task_results`; it does not discover results by
scanning ordinary NetCDF files, run models, rerun analysis, or modify the original answer.

`summary.json` and each `collection_manifest.json` distinguish runtime status from
collection status. `collection_status=complete` means the available answer and
registered files were collected without errors, **not** scientific correctness or
verified reproducibility. Missing previews, files, checksum mismatches and invalid
indexes are reported explicitly. Notebook availability is a separate field.

When saved per-execution notebooks exist, `execution_record.ipynb` groups their
original cells and outputs by agent. It can include failed attempts and original
server paths; it is **not** a clean, end-to-end `analysis.ipynb`. No missing cells
are invented or repaired. Collection is for review, not an additional scientific
completion step or an automatic increase in benchmark scores.

Existing attempts can be recollected without rerunning them:

```bash
python benchmarking/server/collect_oceanx.py --run /import/home3/share/oceanx-bench/methods-public-r1/runs/OceanX
```

Replace `--run` with the saved OceanX method folder to review. Every collection uses
a new directory and preserves previous attempts and collections. Historical receipt
formats remain readable only when no current task-result index is present.

## 3. Before formal scoring

- Pass the server environment/sandbox checks and the native Finch tests.
- Run the three methods on an **evolution** smoke question, in a separate experiment;
  check reports, figures, token/time records and conversations. Smoke records do not
  enter the evolution project's lesson review.
- Record and freeze the commit, selection SHA-256, actual task IDs, model, dependency
  versions, budgets, repeats and retry rule. Use [methods.example.yaml](experiments/methods.example.yaml)
  for the external-method comparison, not the B/C1/C2 library experiment template.
- Compute independent references and freeze rubrics before scored runs. Repository
  rubrics are drafts; data completeness is not scientific-reference readiness.
- Do not update code/config while any method is running. Three concurrent methods
  contend for capacity; rotate/interleave scored repeats for meaningful timing comparisons.

Claude tools in the template include **host Bash, not a filesystem sandbox**.
Start with public data. Finch has a network-disabled calculation sandbox but no
literature-search agent; it is Finch-local, not full Robin. LLM observations can
leave the server in every method; use an approved endpoint for confidential CMOMS.

## 4. Collect and score (separate evaluator step)

For the example paths above, inventory and blind all three method folders together:

```bash
python benchmarking/evaluation/evaluate.py inventory \
  --runs /home/mafzhang/oceanx-bench/methods-public-r1/runs/{OceanX,Claude,Finch} \
  --out /home/mafzhang/oceanx-bench/methods-public-r1/eval/inventory
python benchmarking/evaluation/evaluate.py blind \
  --runs /home/mafzhang/oceanx-bench/methods-public-r1/runs/{OceanX,Claude,Finch} \
  --out /home/mafzhang/oceanx-bench/methods-public-r1/eval/blind \
  --map /home/mafzhang/oceanx-bench/methods-public-r1/eval/blind_map.json
```

Keep rubrics/references outside any bound dataset. Give only blinded evidence and
frozen rubrics to the judge; keep the ID map, raw transcripts, costs and method metadata
away. Follow [CODEX_JUDGE.md](evaluation/CODEX_JUDGE.md), then validate and summarize
with the frozen preregistration. Scoring is not part of the three launch commands.
OceanX-only tree/checkpoint metrics are not applicable to the baselines, not zeros.
