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
  -e /home/mafzhang/code/finch-baseline pyyaml
```

Docker must already be installed and available to this server account. If it is
not, ask the administrator to provide Docker or an equivalent reviewed execution
setup; this runner has **no unsandboxed fallback**. Docker access itself is a
trusted-host privilege; only the trusted runner/Finch controller can access it.
The model-controlled calculation container cannot access the socket.

Build the calculation image from the OceanX checkout:

```bash
cd /home/mafzhang/code/OceanX
docker build -f benchmarking/finch/Dockerfile -t oceanx-finch-kernel:1 .
```

The image contains only a Python notebook kernel and scientific packages, not
OceanX, its skills, the Finch controller or credentials. The runner resolves the
image tag to an image ID, records it and executes that ID. It never pulls an image
automatically. Record an image digest when publishing a reproducible experiment.

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

Run the supervisor in oceanx-bench; `--python` selects the separate Finch worker:

```bash
/home/mafzhang/miniconda3/envs/oceanx-bench/bin/python \
  /home/mafzhang/code/OceanX/benchmarking/server/run_finch.py \
  --queries /home/mafzhang/benchmark-inputs/test.jsonl \
  --output /import/home4/share/mafzhang/benchmark-runs/finch/F-repeat1 \
  --config /home/mafzhang/code/OceanX/benchmark.yaml \
  --finch-root /home/mafzhang/code/finch-baseline \
  --python /home/mafzhang/miniconda3/envs/finch-bench/bin/python \
  --image oceanx-finch-kernel:1 --arm F --max-steps 60
```

All model requests use the model, provider and endpoint in benchmark.yaml;
credentials are not written to manifests or supplied to the calculation kernel.
No Edison/FutureHouse account is required and no files are uploaded to its platform.
**Notebook content, plots and tool observations are still sent to the configured
LLM provider.** Local execution is not a guarantee that private derived data never
leave the server. Use an endpoint approved for CMOMS confidentiality.

Default limits are a 3-hour attempt, 60 agent steps, 300 seconds per notebook
execution, 8 GiB memory and 2 CPUs. A case's `timeout_seconds` overrides the default
attempt limit. ReAct may make multiple model calls per step; steps are not token or
call counts. These are adapter defaults, **not** the Nature paper's settings.
The nbconvert cell timeout is explicitly set to the same execution budget instead
of its implicit 30-second default; the outer deadline still bounds the entire notebook.
Freeze the chosen settings before scored runs; budget changes require a new arm.

Datasets appear at `/inputs/<index>/<name>` as read-only mounts, without copies.
The notebook writes under `/workspace`; published figures/tables go in `outputs/`,
temporary calculations in `scratch/`. The container has no network, extra Linux
capabilities or writable root filesystem. Each attempt owns one named container.
The supervisor removes it after success, failure, timeout or cancellation, and
stops the batch if cleanup fails. SIGKILL/host failure cannot run cleanup: an
administrator must inspect orphan `oceanx-finch-*` containers before restarting.

Add `--resume` to the exact same command. Completed tasks are skipped; other tasks
receive new attempt folders. A running writer owns an OS lock. Changes to the
queries, model, limits, source commit, dependency versions, image ID or adapter
hash are rejected on resume. Run repeats into distinct output directories and
interleave arm order using the same experimental plan as OceanX.

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
are not a complete billing audit. A container/notebook finishing is not evidence
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
container; it makes no model requests and executes no model-written code on the host.
A real server smoke test with Docker and
an approved model endpoint is required before a scored benchmark.
