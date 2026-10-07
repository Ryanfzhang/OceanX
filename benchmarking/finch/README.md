# Local Finch benchmark baseline

This is **Finch-local**, the analysis component used by Robin, not a reproduction of
the full Robin discovery workflow. It preserves Finch's LDP ReAct agent and
notebook tools. It does not add OceanX skills, lessons, a research tree, literature
agents, consensus selection or answer-specific prompting.

Upstream: https://github.com/Future-House/finch

Pinned checkout: `aea66fdf2dd2be827727de50a73cae60dff59972` (Apache-2.0).

## One-time server setup

Use a separate Python 3.12 environment. Do **not** install Finch into oceanx-bench:
its pinned NumPy and agent dependencies differ from OceanX's.

```bash
git clone https://github.com/Future-House/finch.git /home/mafzhang/code/finch-baseline
git -C /home/mafzhang/code/finch-baseline checkout aea66fdf2dd2be827727de50a73cae60dff59972
conda create -n finch-bench python=3.12 pip -y
/home/mafzhang/miniconda3/envs/finch-bench/bin/python -m pip install \
  -c /home/mafzhang/code/OceanX/benchmarking/finch/constraints.txt \
  -e /home/mafzhang/code/finch-baseline pyyaml 'python-dotenv>=1.0,<2' 'httpx[socks]>=0.27,<1'
/home/mafzhang/miniconda3/envs/finch-bench/bin/python -m pip install \
  -r /home/mafzhang/code/OceanX/benchmarking/finch/kernel-requirements.txt
```

No Docker daemon, image, administrator access or Edison account is required.
Linux must provide `bwrap` (Bubblewrap), `prlimit` and `taskset`, and permit user
namespaces. These are already available on macyang10 (checked 2026-10-02).
If namespaces are disabled elsewhere, the runner fails before making any model
request; it never falls back to unrestricted host execution.

Check the server tools:

```bash
command -v bwrap prlimit taskset
bwrap --version
```

By default the notebook uses the same separate Finch interpreter as the agent.
`--kernel-python` can select another dedicated scientific environment. Only its
runtime directories are mounted read-only; neither the Finch checkout nor the
OceanX checkout or user home is mounted. No model credentials are supplied to the
notebook. Both interpreters' package versions and the sandbox adapter hash are
recorded; preflight imports the runtime inside the actual sandbox before any run.

## Prepare the same task inputs

Use the existing benchmark preparation script in oceanx-bench. This step still
requires complete, verified data for the selected tasks:

```bash
cd /home/mafzhang/code/OceanX
export DATA_ROOT=/import/home4/share/mafzhang
/home/mafzhang/miniconda3/envs/oceanx-bench/bin/python \
  benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" \
  --suite test --output /home/mafzhang/benchmark-inputs/test.jsonl
```

For a pilot, prepare non-test questions with `--suite evolution --set A --tasks
E01 E02`. Do not tune the baseline on the scored test suite.

Dataset roots must contain only model-visible scientific inputs. The runner
rejects evaluator directories, nested symlinks and special files; it never mounts
the whole repository/data root in place of a narrower dataset reference.

## Run an external arm

Normal launch: set `BENCH_FINCH_ROOT`, `BENCH_FINCH_PYTHON`, dataset/task/output
settings and resource limits in `benchmarking/.env`, then run
`python benchmarking/server/run_finch.py` in `oceanx-bench`. It chooses its questions from
the same settings as OceanX and Claude; see [RUNNING.md](../RUNNING.md).
The command below is the optional explicit-CLI workflow.

Run the supervisor in oceanx-bench; `--python` selects the separate Finch worker:

```bash
/home/mafzhang/miniconda3/envs/oceanx-bench/bin/python \
  /home/mafzhang/code/OceanX/benchmarking/server/run_finch.py \
  --queries /home/mafzhang/benchmark-inputs/test.jsonl \
  --output /import/home4/share/mafzhang/benchmark-runs/finch/F-repeat1 \
  --config /home/mafzhang/code/OceanX/benchmarking/.env \
  --finch-root /home/mafzhang/code/finch-baseline \
  --python /home/mafzhang/miniconda3/envs/finch-bench/bin/python \
  --arm F --max-steps 60
```

All model requests use BENCH_MODEL (DeepSeek Flash), the shared key and endpoints in benchmarking/.env;
credentials are not written to manifests or supplied to the calculation kernel.
Finch preserves upstream's two-call ReAct step (explicit reasoning, then required
tool selection). For DeepSeek's OpenAI-compatible endpoint the adapter explicitly
sends `thinking.type=disabled` on every request: provider thinking rejects
`tool_choice=required`, and the pinned interfaces do not replay `reasoning_content`.
This does **not** remove Finch's own reasoning step or replace required tool calls
with auto selection. It is not a retry/fallback. `arm.json` and every line of
`launches.jsonl` record `model_compatibility`; report this mode difference in comparisons with
OceanX/Claude, rather than claiming identical provider reasoning settings.
See [DeepSeek's API contract](https://api-docs.deepseek.com/api/create-chat-completion/).

If SOCKS support was installed in oceanx-bench only, install it in the actual
Finch worker environment too:

```bash
/home/mafzhang/miniconda3/envs/finch-bench/bin/python -m pip install 'httpx[socks]>=0.27,<1'
```

After updating the adapter or dependencies the same experiment can continue: old
attempt folders remain intact, and `launches.jsonl` in the method folder records the
code, runtime and limits of every launch. Do not edit a settings file while a runner
that uses it is still running. No live API smoke run is performed by the installation tests.
No Edison/FutureHouse account is required and no files are uploaded to its platform.
**Notebook content, plots and tool observations are still sent to the configured
LLM provider.** Local execution is not a guarantee that private derived data never
leave the server. Use an endpoint approved for CMOMS confidentiality.

Default limits are a 3-hour attempt, 60 agent steps, 1200 seconds per notebook
execution, 8 GiB address space per calculation process and affinity to 2 available
CPUs (fractional values round up). These are native process limits, not Docker
aggregate-memory limits or CPU quotas. A case's `timeout_seconds` overrides the default
attempt limit. ReAct may make multiple model calls per step; steps are not token or
call counts. These are adapter defaults, **not** the Nature paper's settings.
Calculation processes also inherit a 256-process user limit and disabled core dumps.
The nbconvert cell timeout is explicitly set to the same execution budget instead
of its implicit 30-second default; the outer deadline still bounds the entire notebook.
Freeze the chosen settings before scored runs; budget changes require a new arm.

A notebook execution deadline ends that attempt with `status=timed_out` and
`stop_reason=notebook_execution_timeout`, matching upstream's Docker-path termination
on timeout. It does not spend the remaining agent steps replaying the same blocking
cell. The batch proceeds to the next query. `result.json` includes `worker_error` and
`execution_log`; code-run records and the transcript retain the explicit timeout.
The execution log keeps available process output, not guaranteed cell-level progress.
Existing notebook code, previously saved outputs and workspace files remain intact;
outputs still buffered in a killed kernel are not guaranteed to survive. This neither
raises the execution budget nor changes Finch to incremental cell execution.

Datasets appear at `/inputs/<index>/<name>` as read-only mounts, without copies.
The notebook writes under `/workspace`; published figures/tables go in `outputs/`,
temporary calculations in `scratch/`. Bubblewrap creates a private filesystem,
PID namespace and network namespace, drops capabilities and clears the environment.
The sandbox has only local loopback for Jupyter; it cannot reach external hosts.
Only `/workspace` is host-writable; `/tmp` is disposable namespace-local storage.
Every complete notebook replay starts a fresh sandbox and kernel. Its PID namespace
and `--die-with-parent` tear down calculation descendants when the launcher or
controller dies, including descendants that created another process group.

Run the same command again to continue: completed tasks are skipped and the other
tasks receive new attempt folders (`--no-resume` runs every task again). A running
writer owns an OS lock. The queries, model, limits, commit, dependency versions and
runtime of each launch are recorded in `launches.jsonl`; nothing compares them, so
keep them the same within a comparison yourself. Run repeats into distinct output
directories and interleave arm order using the same experimental plan as OceanX.

## Saved per attempt

- `query.json`, `submitted_prompt.txt`, `worker.json`: input and execution settings.
- `answer.md`: the answer explicitly submitted by Finch; no synthetic success
  answer is manufactured at a step limit. Incomplete work remains in the notebook.
- `workspace/notebook.ipynb` and `notebook.md`, `workspace/outputs/`: executed code,
  notebook outputs, final figures and derived tables, including partial work.
- `transcript.jsonl`: model requests/responses, environment observations and actions.
- `model_calls.jsonl`, `token_usage.json`: returned raw router usage and timing.
- `code_runs.jsonl`: notebook execution starts/ends, durations and error states.
- `result.json`, `artifacts.json`, `evidence_manifest.json`, worker stdout/stderr.

Usage is counted once per router response, not once per choice/trajectory object.
Missing usage is `null`, never zero. Cache tokens are a subset of input tokens.
Requests killed in flight and retries internal to LiteLLM without returned usage
are not a complete billing audit. A sandbox/notebook finishing is not evidence
that the scientific answer is correct; notebook errors and final submission are
recorded independently.

Finch reruns its notebook when cells change. Preserve that behavior: do not
silently replace it with OceanX's incremental execution to improve baseline speed.

## Evaluation

Each batch writes `arm.json`. The existing `evaluate.py blind` accepts this arm
alongside OceanX arms. Its external evidence manifest includes the answer,
notebook and published outputs, not scratch arrays, raw transcripts, credentials
or mounted inputs. It uses the same frozen scientific rubric, not OceanX's UI or
ScientificFigure format. `inventory` understands Finch's notebook/JSONL records;
OceanX trees and checkpoints are not required.

```bash
python benchmarking/evaluation/evaluate.py blind \
  --runs /path/to/oceanx-arm /path/to/finch-arm \
  --out /path/to/evaluation/blind --map /path/to/evaluation/blind_map.json
python benchmarking/evaluation/evaluate.py inventory \
  --runs /path/to/finch-arm --out /path/to/evaluation/inventory
```

Add external score comparisons to a **new** pre-registration;
this integration does not change the existing three-arm experiment automatically.
Finch has no literature-search agent or cross-task learning. Report that capability
difference, and treat OceanX-only research-tree measures as not applicable rather
than zero. A Finch comparison cannot replace B/C1/C2 tests of lesson transfer.

## Verification

```bash
python -m pytest benchmarking/tests/test_run_finch.py benchmarking/tests/test_evaluate.py
/home/mafzhang/miniconda3/envs/finch-bench/bin/python -m pip install pytest
/home/mafzhang/miniconda3/envs/finch-bench/bin/python -m pytest benchmarking/tests/test_finch_upstream.py
```

The first tests use fake subprocesses/model responses and check recording, timeout,
resume, mounts and evaluation contracts. The separate Finch-environment test exercises
the real pinned ReAct, model-routing and notebook interfaces with a fake provider and
sandbox; it makes no model requests and executes no model-written code on the host.
`test_finch_sandbox.py` additionally exercises real Linux notebook execution and
isolation with fixed test code when Bubblewrap is available.
A real server smoke test with Bubblewrap and
an approved model endpoint is required before a scored benchmark.
