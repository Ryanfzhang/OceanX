# OceanX benchmark (v2)

Catalogue `2026-10-01-scs-v2`:
- **Test suite (scored):** 30 questions on the South China Sea, 2011-2020. Each pairs private CMOMS model
  output with public observations or reanalysis.
- **Evolution suite (never scored):** 12 questions on the Gulf of Mexico and East China Sea. OceanX learns
  lessons from these runs.

Everything runs on the Linux server.

| Read | For |
|---|---|
| [DESIGN.md](DESIGN.md) | What is tested: allocation, the 30 + 12 questions, verified papers, design rules |
| [DATA.md](DATA.md) | Data groups, server layout, CMOMS staging, the extra CMOMS variables to request, download commands |
| [EVALUATION.md](EVALUATION.md) | How runs are made, stored and judged; how the policy is chosen; labels and lessons |
| [CODEX_TEST_PLAN.md](CODEX_TEST_PLAN.md) | The step-by-step tests Codex executes (T0-T11) |
| [evaluation/CODEX_JUDGE.md](evaluation/CODEX_JUDGE.md) | How Codex scores one answer, and the score-file format |
| [INSTALL.md](INSTALL.md) | One-time server setup |

## Layout

```text
tasks/Q01..Q30/task_info.json            agent-facing query, data groups, paper
tasks/Q01..Q30/evaluator/rubric.json     evaluator only: criteria, references, answer key, checks (draft)
evolution/E01..E12/task_info.json        evolution questions (no rubric)
download/                                data_manifest.json and download_all.py
server/                                  prepare_queries.py, run_oceanx.py (arms), research_cli.py, run_claude.py
evaluation/                              evaluate.py (blind, validate, freeze, summarize), CODEX_JUDGE.md
experiments/                             pre-registration template
tests/                                   python -m pytest benchmarking/tests
```

## The short version

```bash
python -u benchmarking/download/download_all.py public   --output "$DATA_ROOT" --execute
python -u benchmarking/download/download_all.py services --output "$DATA_ROOT" --execute
python benchmarking/download/download_all.py private --output "$DATA_ROOT"      # after staging CMOMS
python benchmarking/server/prepare_queries.py --data-root "$DATA_ROOT" --suite test --output <test.jsonl>
python benchmarking/server/run_oceanx.py --queries <test.jsonl> --output <arm folder> --arm B --policy v2-nested
```

Never mount the repository, `evaluator/` folders or `_evaluator_only/` data into an agent run, and never
commit CMOMS data or anything computed from it.
