# Run OceanX, Claude Code and Finch on the same available questions

This is the operational entry point. The library-transfer experiment (B/C1/C2) is
separate; see EVALUATION.md for it. All commands below run on the Linux server,
from `/home/mafzhang/code/OceanX`. No Docker is used.

## 1. Prepare once

Use the same repository commit throughout a comparison. Do not update it while any
runner is active. Finish [INSTALL.md](INSTALL.md) and the separate
[Finch setup](finch/README.md) before starting the three terminals.

The server audit on 2026-10-02 found no configured benchmark credentials, no Claude executable
at the usual install locations, and no `finch-bench` environment or pinned Finch
checkout. Those steps still need to be completed; scripts alone are not a ready baseline.

For Claude Code, follow the [official installation instructions](https://code.claude.com/docs/en/setup).
The official Linux native installer is:

```bash
curl -fsSL https://claude.ai/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"
claude --version
```

Disable CLI auto-updates during a frozen experiment (`DISABLE_AUTOUPDATER=1` below).
Record the installed version. The runner uses API credentials from `benchmarking/.env`,
not an inherited login or cloud-provider setting.

Copy `benchmarking/.env.example` to ignored `benchmarking/.env` on the server and fill
`DEEPSEEK_API_KEY`. `BENCH_MODEL=deepseek-flash` applies to **all three methods and the
offline meta-agent/node labels**. Both official DeepSeek API formats share that one key;
Claude Code uses the Anthropic-compatible URL and the other roles default to OpenAI
format. There is no separate `meta_model`. Do not source the file: runners load it
explicitly. The scientific rubric judge remains independent. See INSTALL.md.

Set these variables in **each** terminal (terminal environments are not shared):

```bash
cd /home/mafzhang/code/OceanX
export PATH=/home/mafzhang/miniconda3/envs/oceanx-bench/bin:$HOME/.local/bin:$PATH
export DATA_ROOT=/import/home4/share/mafzhang
export EXP=methods-public-r1
export RUNS_ROOT=/home/mafzhang/oceanx-bench/runs
export EVAL_ROOT=/home/mafzhang/oceanx-bench/eval
export QUERY_FILE=/home/mafzhang/oceanx-bench/inputs/methods-public-r1.jsonl
export DISABLE_AUTOUPDATER=1
```

Check OceanX and Claude without model calls:

```bash
python benchmarking/server/check_setup.py --agent both
```

Finch performs its own real sandbox/dependency preflight before a model request.
First run the fixed-code native tests in its installed environment:

```bash
/home/mafzhang/miniconda3/envs/finch-bench/bin/python -m pip install pytest
/home/mafzhang/miniconda3/envs/finch-bench/bin/python -m pytest \
  benchmarking/tests/test_finch_sandbox.py benchmarking/tests/test_finch_upstream.py -q
```

Then smoke-test the runners on an evolution question (e.g. E01), using a separate
input/output set, before freezing and running scored test questions. Do not tune
adapters or prompts on Q01-Q30. Preflight does not test model credentials live.

## 2. Freeze a partial-data input set, once

You do **not** need all 54 questions' data. Create one immutable JSONL from completed
groups and pass this exact file to every method:

```bash
python benchmarking/server/prepare_queries.py \
  --data-root "$DATA_ROOT" --suite test --available \
  --timeout 10800 --output "$QUERY_FILE"
```

`--available` prints every excluded question and its missing groups. It still checks
manifest versions, completed group reports and actual input paths; it does not
accept an incomplete group, silently ignore a stale report, or change a query.
The output cannot replace an existing file. Do not regenerate it after starting
one method, even if downloads finish later.

To select fewer ready questions, add `--tasks Q07 Q08 Q09` together with `--available`.
For an unscored smoke run, instead use `--suite evolution --tasks E01 --available`
and a different `--output` path. The test/evolution sets are never mixed.

At the latest 2026-10-02 audit, the completion reports allowed these **17 scored questions**:

```text
Q07 Q08 Q09 Q10 Q15 Q18 Q19 Q20 Q21 Q23 Q24 Q25 Q26 Q27 Q28 Q29 Q30
```

All E01-E24 had complete numerical inputs; together this is 41/54. The remaining
13 test exclusions require staged CMOMS (Q14/Q16 also need requested diagnostics).
This list is a dated snapshot, not a hard-coded selector. Readiness is not scientific
reference validation: freeze the chosen tasks' rubrics/references before a formal run.

Record the commit, CLI/dependency versions, JSONL SHA-256, exact task IDs, BENCH_MODEL,
timeout, Finch limits and repeat count in a pre-registration **before** scored runs.
Start from [the external-method template](experiments/methods.example.yaml), not the
B/C1/C2 library template. A partial public-data result is not a full-suite result
and says nothing about performance on private CMOMS questions.

Fill the copy in, then lock it. `evaluate.py summarize` in step 4 refuses a
pre-registration that was not frozen or was changed afterwards:

```bash
mkdir -p "$EVAL_ROOT/$EXP"
cp -n benchmarking/experiments/methods.example.yaml "$EVAL_ROOT/$EXP/preregistration.yaml"
# edit the copy, then:
python benchmarking/evaluation/evaluate.py freeze --prereg "$EVAL_ROOT/$EXP/preregistration.yaml"
```

## 3. Three terminals, three independent output folders

Use the variables from step 1 in all three terminals. Each runner processes its
selected questions sequentially; the three runners operate concurrently. Output
folders must be new, outside the code checkout and input data folders.

**Terminal 1 — OceanX**, default v2-nested, no learned library:

```bash
python -u benchmarking/server/run_oceanx.py \
  --queries "$QUERY_FILE" --output "$RUNS_ROOT/$EXP/OceanX" --arm OceanX
```

**Terminal 2 — Claude Code**:

```bash
python -u benchmarking/server/run_claude.py \
  --queries "$QUERY_FILE" --output "$RUNS_ROOT/$EXP/Claude" --arm Claude \
  --allow-tools Read Glob Grep Bash Write Edit NotebookEdit WebSearch WebFetch
```

This is an explicit approval of those tools for these tasks, **not** a filesystem
sandbox. Claude's Bash can access the host account. Start with the public subset;
do not expose private CMOMS to it or an unapproved model endpoint on the assumption
that a read-only instruction provides security. Evaluator isolation is enforced by
input binding and instructions here, not a hostile-code boundary. Permission denials
are recorded as `needs_interaction`; the runner never bypasses permissions globally.

**Terminal 3 — Finch-local**:

```bash
python -u benchmarking/server/run_finch.py \
  --queries "$QUERY_FILE" --output "$RUNS_ROOT/$EXP/Finch" --arm Finch \
  --finch-root /home/mafzhang/code/finch-baseline \
  --python /home/mafzhang/miniconda3/envs/finch-bench/bin/python \
  --max-steps 60 --execution-timeout 300 --memory-mb 8192 --cpus 2
```

Finch uses Linux Bubblewrap, mounts declared data read-only and has no literature
search agent. This is its local analysis component, not full Robin. OceanX and
Claude may use literature search; report this capability difference. The same
model/query/data does not make tool capabilities or resource budgets identical.

For SSH sessions, run each command inside its own `tmux` session if available;
closing an ordinary SSH terminal can terminate its foreground runner. `--resume`
continues a stopped batch; it does not resume an in-flight agent conversation.
Add it to the **unchanged** original command to skip completed cases and create new
attempts for unfinished cases. Resume records are retained, but the default blind
export uses the latest attempt; do not selectively retry scored failures. Prespecify
a retry rule and disclose retries. Planned repeats use a new `EXP`, not `--resume`.

Three simultaneous methods compete for server/network/model capacity. This is a
useful smoke/comparison workflow, not a controlled latency experiment. Before
paper-quality timing comparisons, finish downloads, verify selected groups, measure
contention, and rotate/interleave method order across repeats. Never verify/move
active input files while a downloader is running.

## 4. Collect, blind and score together

After all three batches end:

```bash
python benchmarking/evaluation/evaluate.py inventory \
  --runs "$RUNS_ROOT/$EXP/OceanX" "$RUNS_ROOT/$EXP/Claude" "$RUNS_ROOT/$EXP/Finch" \
  --out "$EVAL_ROOT/$EXP/inventory"
python benchmarking/evaluation/evaluate.py blind \
  --runs "$RUNS_ROOT/$EXP/OceanX" "$RUNS_ROOT/$EXP/Claude" "$RUNS_ROOT/$EXP/Finch" \
  --out "$EVAL_ROOT/$EXP/blind" --map "$EVAL_ROOT/$EXP/blind_map.json"
```

Give only the blind folder and frozen scientific rubrics to the independent judge;
follow [CODEX_JUDGE.md](evaluation/CODEX_JUDGE.md). Keep the ID map, time/tokens,
raw transcripts and method metadata away from the judge. Formats can still suggest
the system; blinding is not guaranteed unidentifiability. Scoring is not automatic:
the judge writes the per-attempt score files, then validate and summarize:

```bash
python benchmarking/evaluation/evaluate.py validate --scores "$EVAL_ROOT/$EXP/scores"
python benchmarking/evaluation/evaluate.py summarize \
  --prereg "$EVAL_ROOT/$EXP/preregistration.yaml" \
  --map "$EVAL_ROOT/$EXP/blind_map.json" --scores "$EVAL_ROOT/$EXP/scores" \
  --out "$EVAL_ROOT/$EXP/report"
```

All methods retain answer/evidence, time and available usage. Claude's whole-call
token totals include cache reads/writes once; missing usage is unknown, not zero.
Its CLI does not provide an independent per-call/code-execution ledger. Finch's
notebook/transcript are inventoried separately. OceanX-only tree metrics are not
applicable to either baseline, and must not be counted as zeros or scientific penalties.
