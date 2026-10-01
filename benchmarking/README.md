# OceanX benchmark (v5)

Catalogue `2026-10-01-v5`:
- **Test suite (scored):** 30 questions.
  - Ten paper verifications. Each paper's study period lies inside the supplied data.
  - Twenty open problems: 7 on CMOMS in the South China Sea, and 13 on public data in the Arabian Sea, the
    Gulf of Mexico and the East China Sea.
- **Evolution suite (never scored):** 12 open problems on the California Current System using public
  reanalyses. OceanX learns lessons from these runs.
- **Requested inputs:** small-region CMOMS primary-production/nitrate-uptake diagnostics (Q14) and
  surface air-sea CO2 flux/pCO2 diagnostics (Q16), both for 2011-2020.

Everything runs on the Linux server.

| Read | For |
|---|---|
| [summary.md](summary.md) | All 42 questions, required data (type, time, space, variables), and brief assessment criteria |
| [DESIGN.md](DESIGN.md) | What is tested: allocation, the 30 + 12 questions, verified papers, design rules |
| [DATA.md](DATA.md) | Data groups, server layout, CMOMS staging, the extra CMOMS variables to request, download commands |
| [EVALUATION.md](EVALUATION.md) | How runs are made, stored and judged; how the policy is chosen; labels and lessons |
| [CODEX_TEST_PLAN.md](CODEX_TEST_PLAN.md) | The step-by-step tests Codex executes (T0-T11) |
| [evaluation/CODEX_JUDGE.md](evaluation/CODEX_JUDGE.md) | How Codex scores one answer, and the score-file format |
| [INSTALL.md](INSTALL.md) | One-time server setup |

## Layout

```text
tasks/Q01..Q30/task_info.json            agent-facing query, data groups, paper and its period match
tasks/Q01..Q30/evaluator/rubric.json     evaluator only: criteria, findings, answer key, probes (draft)
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
