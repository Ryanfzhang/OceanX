# Server scripts

| Script | Purpose |
|---|---|
| `prepare_queries.py` | Write a suite's runner input (JSONL) from the data root. Folders come from `download/data_manifest.json`. `--set A` or `--set B` selects one evolution set. It refuses incomplete downloads and any evaluator material. |
| `run_oceanx.py` | Run a JSONL as one arm: `--arm`, optional `--library <frozen snapshot>` (lessons and tools). The policy is the default, `v2-nested`; `--policy` selects another for a paired run. Writes `arm.json`; each attempt starts from empty OceanX state and learns nothing. |
| `research_cli.py` | Offline tree labels/library review with the same DeepSeek Flash model/key in `benchmarking/.env` as the analysis methods. |
| `collect_oceanx.py` | Collect finished attempts into `collected/` for reading (run automatically at the end of a run). |
| `run_claude.py` | The same JSONL with Claude Code; exports arm identity, derived evidence and CLI token totals for unified blinding/inventory. Not part of the library experiment automatically. |
| `run_finch.py`, `finch_worker.py`, `finch_sandbox.py` | Optional local Finch analysis-component baseline using the same JSONL/config, a separate Python 3.12 environment and a read-only-data Linux Bubblewrap notebook kernel; no Docker. See [Finch setup](../finch/README.md). Not full Robin and not part of the three-arm experiment automatically. |
| `check_setup.py`, `benchmark_config.py`, `benchmark_models.py` | Unified model/key configuration from `benchmarking/.env` and setup checks. Only `.env.example` belongs in Git. |

## Prepare inputs

For partial data and three-terminal OceanX/Claude/Finch commands, start with
[RUNNING.md](../RUNNING.md). Do not wait for the entire catalogue to download.

```bash
python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite test --output <file.jsonl>
python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite test --available --output <partial.jsonl>
python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite test --tasks Q05 Q27 --output <file.jsonl>
python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite evolution --set A --output <file.jsonl>
python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite evolution --set B --output <file.jsonl>
```

- **Each case** holds the unchanged query, the bound data folders (read-only references, never copies),
  `workflow_mode: research`, `literature_mode: search_only` and a 3-hour default timeout (`--timeout`).
  Use the same timeout for every arm of an experiment: a timed-out attempt scores 0.
- **Overrides:** `--bindings <json>` overrides folders per task (`{"Q01": {"datasets": ["CMOMS/temp", ...]}}`),
  under the same checks.

## Run an arm

```bash
python benchmarking/server/run_oceanx.py --queries <file.jsonl> --output <arm folder> --arm B
python benchmarking/server/run_oceanx.py --queries <file.jsonl> --output <arm folder> --arm C1 --library <snapshot>
```

Output per case: `<arm folder>/<task>/attempt-*/` containing:
- `query.json`, `submitted_prompt.txt`, `result.json` (status and time) and `answer.md`;
- `model_protocol.json`;
- `workspace/` (the task's Agent folders, reports and outputs) and `state/` (that attempt's own OceanX
  state: the ledger of model calls, the code runs and the agents' conversations);
- `arm_library.json`, for arms that run with a library snapshot: the SHA-256 of its lessons and tools
  before and after the attempt.

`<arm folder>/arm.json` records arm, policy, the library version, git commit and OceanX version. `--resume`
continues unfinished cases and refuses an output folder that belongs to a different arm.

Paper-selection prompts are answered automatically by selecting all offered papers. Other permissions are
never auto-approved.
