# Server scripts

| Script | Purpose |
|---|---|
| `prepare_queries.py` | Write a suite's runner input (JSONL) from the data root. Folders come from `download/data_manifest.json`. `--set A` or `--set B` selects one evolution set. It refuses incomplete downloads and any evaluator material. |
| `run_oceanx.py` | Run a JSONL as one arm: `--arm`, `--policy`, optional `--lessons <frozen snapshot>`. Writes `arm.json`; each attempt starts from empty OceanX state. |
| `research_cli.py` | `ocean research ...` (show, label, judge-labels, judge-agreement, consolidate, lessons, lesson-decide) with the `benchmark.yaml` model. |
| `collect_oceanx.py` | Collect finished attempts into `collected/` for reading (run automatically at the end of a run). |
| `run_claude.py` | Optional: the same JSONL with Claude Code, for a cross-system comparison (not part of the main experiment). |
| `check_setup.py`, `benchmark_config.py`, `benchmark_models.py` | Model configuration from `benchmark.yaml` and setup checks. |

## Prepare inputs

```bash
python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite test --output <file.jsonl>
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
python benchmarking/server/run_oceanx.py --queries <file.jsonl> --output <arm folder> --arm A --policy v0-coordinator-bfs
python benchmarking/server/run_oceanx.py --queries <file.jsonl> --output <arm folder> --arm C1 --policy v2-nested --lessons <snapshot>
```

Output per case: `<arm folder>/<task>/attempt-*/` containing:
- `query.json`, `submitted_prompt.txt`, `result.json` (status, time, tokens) and `answer.md`;
- `model_protocol.json`;
- `workspace/` (the task's Agent folders, reports and outputs) and `state/` (that attempt's own OceanX state);
- `arm_lessons.json`, for lesson arms only.

`<arm folder>/arm.json` records arm, policy, lesson version, git commit and OceanX version. `--resume`
continues unfinished cases and refuses an output folder that belongs to a different arm.

Paper-selection prompts are answered automatically by selecting all offered papers. Other permissions are
never auto-approved.
