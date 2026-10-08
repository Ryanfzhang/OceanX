# OceanX benchmark (v7)

Catalogue `2026-10-02-v7`:
- **Test suite (scored):** 30 questions.
  - Ten paper verifications. Each paper's study period lies inside the supplied data.
  - Twenty open problems: 7 on CMOMS in the South China Sea, and 13 on public data in the Arabian Sea, the
    Gulf of Mexico and the East China Sea.
- **Evolution suite (never scored):** 24 open problems on public reanalyses, in two sets of twelve: set A on
  the California Current System and set B on the Tasman Sea and East Australian Current. They ask about
  kinds of problems the test suite does not have (for example sound propagation, statistical prediction and
  observing-system design), so what is learned has to transfer across problems, not only across regions.
  OceanX learns lessons and tools from these runs in two rounds: set A yields the library L1, and set B,
  run with L1, yields L2.
- **Requested inputs:** small-region CMOMS primary-production/nitrate-uptake diagnostics (Q14) and
  surface air-sea CO2 flux/pCO2 diagnostics (Q16), both for 2011-2020.

Everything runs on the Linux server.
All runner/meta models use DeepSeek Flash via `benchmarking/.env`. Copy `.env.example`
to `.env` on the server and fill the single key, data/output paths and task selection;
only the example is committed. Then launch each method with no arguments (RUNNING.md).

| Read | For |
|---|---|
| [RUNNING.md](RUNNING.md) | 怎么跑（中文）：配置、三个方法跑测试题、续跑和重跑、进化两轮并冻结成库、带库跑测试题、跑完的检查 |
| [EVALUATION.md](EVALUATION.md) | How results are stored and judged; run settings to disclose; how lessons and tools are learned; what to check before a reported comparison |
| [evaluation/CODEX_REFERENCES.md](evaluation/CODEX_REFERENCES.md) | How Codex computes the reference answers and freezes a rubric, before any judging |
| [evaluation/CODEX_JUDGE.md](evaluation/CODEX_JUDGE.md) | How Codex scores one answer, and the score-file format |
| [evaluation/ASPECT_SCORES.md](evaluation/ASPECT_SCORES.md) | The six indicators per task type that the rubric total is divided into |
| [DESIGN.md](DESIGN.md) | What is tested: allocation, the 30 + 24 questions, verified papers, design rules |
| [summary.md](summary.md) | All 54 questions, required data (type, time, space, variables), and brief assessment criteria |
| [DATA.md](DATA.md) | Data groups, server layout, CMOMS staging, the extra CMOMS variables to request, download commands |
| [INSTALL.md](INSTALL.md) | One-time server setup |
| [finch/README.md](finch/README.md) | The local Finch baseline: isolated runtime, same inputs, saved evidence |

## Layout

```text
tasks/Q01..Q30/task_info.json            agent-facing query, data groups, paper and its period match
tasks/Q01..Q30/evaluator/rubric.json     evaluator only: criteria, findings, answer key, probes (draft)
evolution/E01..E24/task_info.json        evolution questions in two sets, A and B (no rubric)
download/                                data_manifest.json and download_all.py
server/                                  the three runners and what they share (below)
skills/                                  the one skill only benchmark runs of OceanX get (figure style)
evaluation/                              evaluate.py (blind, validate, rubric-check, freeze, summarize, process, inventory, library-check)
experiments/                             pre-registration templates
reviews/                                 dated reviews of finished runs
tests/                                   python -m pytest benchmarking/tests
```

| Script in `server/` | Purpose |
|---|---|
| `run_oceanx.py`, `run_claude.py`, `run_finch.py` | Run the chosen questions with one method. With no arguments everything comes from the settings file. |
| `benchmark_config.py`, `benchmark_run.py` | Read the settings file; choose the questions of a launch, skip the completed ones, record the launch. |
| `prepare_queries.py` | Turn questions and the data root into runner cases. As a command it writes a JSONL for the explicit `--queries` workflow. It refuses incomplete downloads and any evaluator material. |
| `collect_oceanx.py` | Collect finished OceanX attempts into `collected/` for reading (runs by itself after a batch). |
| `benchmark_agent_server.py`, `benchmark_models.py`, `benchmark_skills.py` | Give OceanX's own server process the benchmark's model settings and its one extra skill. |
| `finch_worker.py`, `finch_sandbox.py` | The Finch agent loop and its network-disabled notebook sandbox. |
| `check_setup.py` | Check the settings and the sandbox without a model call. |
| `research_cli.py` | Offline tree labels and library review for the evolution rounds. |

## The short version

```bash
python -u benchmarking/download/download_all.py public   --output "$DATA_ROOT" --execute
python -u benchmarking/download/download_all.py services --output "$DATA_ROOT" --execute
python benchmarking/download/download_all.py private --output "$DATA_ROOT"      # after staging CMOMS
# Configure benchmarking/.env, then in separate terminals:
python benchmarking/server/run_oceanx.py
python benchmarking/server/run_claude.py
python benchmarking/server/run_finch.py
```

Run the same three commands again whenever more data have arrived, a run was interrupted or the code
changed: completed questions are skipped and the rest run, in the same experiment folder.

Never mount the repository, `evaluator/` folders or `_evaluator_only/` data into an agent run, and never
commit CMOMS data or anything computed from it.
