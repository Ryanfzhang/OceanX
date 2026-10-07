# Run OceanX, Claude Code and Finch from one settings file

All commands run on the Linux server from the OceanX checkout, with `oceanx-bench` active. No Docker is
used. Finish [INSTALL.md](INSTALL.md), install Claude Code, and finish the separate
[Finch setup](finch/README.md) first. The three commands do not install dependencies, download data or
start learning.

## 1. Configure once

```bash
cp -n benchmarking/.env.example benchmarking/.env
chmod 600 benchmarking/.env
```

Edit the ignored `.env`; do **not** source it. The key is never written to a record. The template
includes every setting the three commands need. The main choices:

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
BENCH_RESUME=true
```

- `BENCH_EXPERIMENT`: the name of the results folder. It can stay the same after the code, the settings
  or the data change.
- `BENCH_TASKS=available`: every question whose data are complete now. A question without data is
  printed and left out; it runs at a later launch, once its data are there.
- `BENCH_TASKS=all`: every question of the suite or set; the launch stops if one lacks data.
- `BENCH_TASKS=Q07,Q08,Q09`: exactly these questions; commas or spaces are accepted.
- `BENCH_RESUME=true`: skip the questions already completed and run the rest. `false`: run every chosen
  question again.
- `BENCH_OCEANX_EXPERT_CALL_LIMIT=40`: model calls one Expert may use (10 to 60; 60 is the desktop's
  limit). Compare runs only at the same value.
- For an unscored smoke run: `BENCH_SUITE=evolution`, `BENCH_TASKS=E10` and an experiment name of its own.
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
Python 3.12 environment. `BENCH_FINCH_EXECUTION_TIMEOUT` defaults to 1200 seconds (20 minutes),
matching upstream Finch. It limits each full notebook replay; `edit_cell` re-executes all
cells. The separate case timeout remains `BENCH_TIMEOUT_SECONDS` (10800 seconds by default).
No `--queries`, `--output`, model flags or exported path variables are needed.

Each method runs its questions one after another, into a folder of its own. Run under `tmux` to survive
an SSH disconnection.

```text
BENCH_OUTPUT_ROOT/BENCH_EXPERIMENT/runs/
  OceanX/<question>/attempt-*/      one folder per attempt; nothing is ever overwritten
  OceanX/results.jsonl              one line per finished attempt
  OceanX/launches.jsonl             one line per launch: when, commit, settings, questions
  OceanX/arm.json                   what the method folder is; written at the first launch
  Claude/...    Finch/...           the same
```

The folder names follow `BENCH_OCEANX_ARM`, `BENCH_CLAUDE_ARM`, `BENCH_FINCH_ARM`; choose distinct names.

### Running again

An experiment is only this folder. Nothing in it is frozen, and a launch compares nothing with an
earlier one. Every launch chooses its questions again from the settings and the data present.

| You want to | Do this |
|---|---|
| Continue after an interruption, or retry what failed | Run the same command again. Completed questions are skipped; a question that failed, timed out or never started gets a new attempt. It is not a resume of a conversation in flight. |
| Run the questions whose data have arrived since | Run the same command again with `BENCH_TASKS=available`. |
| Run a completed question again | Set `BENCH_TASKS` to those questions and `BENCH_RESUME=false` (or pass `--no-resume`). The new attempt is stored beside the earlier one, and the evaluation reads each question's latest attempt. |
| Go on after updating the code or changing a setting | Keep the experiment name and run the command. |

`launches.jsonl` is what tells runs apart afterwards. Every launch adds a line with the commit, one hash
of the runner code, all settings (never the key) and its questions; an attempt belongs to the last launch
that started before it.

This leaves one thing to you: attempts made with different code or settings can sit in one folder. For a
comparison you report, run every method on one commit and one set of settings, and do not rerun a
question to get a better score. Use another `BENCH_EXPERIMENT` when results should be kept apart, for
example for a second repeat.

One runner writes a method folder at a time; a second one stops with "Another runner is writing". The
system drops that lock when the runner ends, however it ends.

**One settings file per runner.** By default all three commands read `benchmarking/.env`. A runner that
finds a file of its own next to it loads that one instead: `run_oceanx.py` reads `.env.oceanx`,
`run_claude.py` `.env.claude`, `run_finch.py` `.env.finch`. `--config <file>` and `OCEAN_BENCH_CONFIG`
still come first, and each runner prints the file it uses as its first line.

```bash
cp benchmarking/.env benchmarking/.env.oceanx   # then set its own BENCH_TASKS, BENCH_RESUME, ...
```

Use this to give the methods different questions or resume flags, or different experiments. Do not edit
a settings file that a running batch uses: a runner fixes its experiment, questions and resume flag at
start, but OceanX's server process and Finch's worker read the same file again at the start of every
case for the model, endpoint, key and token limit. `check_setup.py` reads `benchmarking/.env` unless
given `--config`.

Command-line flags still override single settings. Explicit `--queries` or `--query` requires explicit
`--output` and takes the questions from that file instead of the settings.

## Run settings and comparison limits

- OceanX benchmark runs use `OCEANX_FIGURE_DELIVERY=static`: when the researcher requested a
  visual, or a figure is necessary scientific evidence, Experts save it as an ordinary PNG image.
  OceanX's interactive plotting interface is not exposed to the models; the desktop's interactive
  mode is unchanged. Reading one of these images gives the model a JPEG preview bounded to 1024 px
  on its longest edge, while the full-resolution result remains on disk. A preview that cannot be
  made (a missing or corrupt file) is an ordinary error message, as for any other file. In these runs
  the Coordinator also cannot re-delegate a node that already has a result just to publish a figure
  the researcher's question did not ask for; the desktop keeps the prompt rule alone.
- OceanX benchmark runs have one skill that the desktop does not have:
  `benchmarking/skills/scientific-figure-style`, which says how to choose and draw a figure saved as an
  image file and names no plotting interface. The two data Experts get it, and one sentence added to their
  policy points to it. `benchmark_agent_server.py` installs both in the benchmark's own Agent Server
  process; OceanX's code and packaged skills are unchanged. `arm.json` and each attempt's
  `model_protocol.json` list it under `benchmark_skills`.
- Each arm's agent is told to report what it has before it runs out. OceanX: the research time budget
  below. Claude Code: its prompt says the run is one turn and nothing resumes after the final response.
  Finch: its prompt states the runner's tools, inputs and limits, and the worker says when 10, 5, 3, 2 and
  1 steps remain. An attempt that still ends without a final answer is judged on what it kept
  (`evaluation/CODEX_JUDGE.md`); no substitute answer is written for it.
- The Expert's last, tool-free delivery call may issue an extra provider request if its first
  reply contains tool markers rather than a report. Context compaction requests are counted
  separately as summary calls. Both appear in the per-call ledger and belong in time and token totals;
  the Expert call limit (60 on the desktop; `BENCH_OCEANX_EXPERT_CALL_LIMIT`, 10 to 60, in benchmark runs
  and recorded in `arm.json`) is not an exact count of all provider requests. At a lower limit the report
  checkpoint falls at half of it and the wind-down at four fifths, as at 30 and 48 of 60.
- A model reply whose tool-call arguments are valid JSON plus stray closing brackets is repaired and the tool runs;
  a reply with no runnable tool call is asked for once more. Before this, one such reply ended the Coordinator and
  failed the whole question (Q07 of the 40-call batch, after 21 seconds).
- `BENCH_OCEANX_MAX_PARALLEL_EXPERTS=3`: data Experts that may work at once; a Search Expert has its own slot
  (`BENCH_OCEANX_MAX_PARALLEL_SEARCH_EXPERTS=1`), so up to four Experts run together. Watch memory in the first run
  with this setting; `arm.json` records both. The desktop has the same setting under Settings, Research runtime
  (1 to 4, default 2); it travels with each request (`session.submit.max_parallel_experts`).
- Experts work in the background of the Coordinator's run. A `task` call returns when the next running Expert
  finishes, not when the slowest of its batch has, and `await_experts` is how the Coordinator waits: for the next
  one, for named nodes, or for all. The Coordinator decides whether to continue one node's own line at once or to
  wait for several results that a new question depends on; it cannot finish while an Expert is running. Each
  Expert's own `task` tool run still ends with its own receipt. Elapsed times of runs made before this change
  (every batch waited for its slowest Expert) are not comparable with later ones.
- Before the final answer the Coordinator reads every returned node's complete Result and Evidence and limitations
  with `update_research_tree(changes=[], view='results')`. The ordinary tree view clips each Result to 320 characters
  and each limit to one sentence, which hid a correction in Q08 of the 40-call batch (0.879 to 0.778 m/s) from the final
  answer. Experts begin a Result that changes an earlier node's number with `Corrects B1.x: ...`.
- Only the user's own question authorizes dataset acquisition. The Coordinator and Expert prompts say so;
  an assignment that says an Expert "is authorized" is not a request (Q08 of the 40-call batch downloaded WOA18
  and Argo on the Coordinator's own authorization and used them in the answer).
- `BENCH_TIMEOUT_SECONDS` supplies OceanX's research budget: after 75% no new Expert assignment
  starts. This is a run setting that changes Coordinator behavior, not merely an external timeout;
  disclose it alongside the commit, model, delivery mode and other run settings.
- Finch-local has no literature-search agent; it is not the full Robin system.
  Claude Code's search depends on its configured tools. OceanX consults Search Expert on demand
  for definitions, methods or published mechanisms the data context does not settle. These search
  capabilities are not identical; report them when comparing methods. Search Expert has one
  independent slot by default and therefore does not occupy either data-analysis slot.
- Failure categories describe observed messages, not blame. A read-only refusal may correctly
  protect another node's evidence, and a timeout may reflect slow computation. Inspect logs before
  assigning a cause; collection completeness and a successful run do not establish scientific correctness.

## OceanX review delivery

If a follow-up attempt leaves its question's nonempty `report.md` unchanged, OceanX
delivers that report and its original Summary; a short closing reply is added only to
the Coordinator receipt. The closing reply becomes the report only when no nonempty
report exists, for the Discussion Partner, or when it contains a nonempty `## Summary`.
Without closing prose, the receipt explicitly says so and gives the model-call stop reason.
If an Expert reaches model call 30 without saving a report, analysis tools pause until it writes a
defensible partial `report.md`; it may then continue analysis and update the report. This is a
checkpoint, not a lower replacement for the call limit.
Every Expert is told its call budget in its instructions, and each call after the first ends its last tool
result with a line such as `[Budget: model call 13 of 40; 20 left for analysis, then 8 only to finish the
report.]`. The line is added to that request only and is never saved in the conversation, so the cached
prompt prefix does not change. This applies to the desktop's Experts too.

Every OceanX attempt delivers ordinary images, as the Claude Code and Finch arms do:
`run_oceanx.py` starts the backend with `OCEANX_FIGURE_DELIVERY=static` and records
`figure_delivery` in `arm.json`. No prompt, tool description or skill the OceanX models read
names OceanX's plotting interface. A final figure is an image file (`.png`, `.jpg`, `.jpeg`,
`.svg`, `.pdf`) that an Expert saves under its node's `outputs/` folder; exploratory plots stay
in `scratch/`, and a file name starting with `_` or `.` is a draft. The result store lists
each delivered image as a `file` result (`render_status: "static"`), the Expert receipt lists
them under `Saved figures (cite these paths):`, and the collector copies them into the
figure gallery and rewrites the cited absolute paths to links.

The OceanX runner automatically creates a new `runs/OceanX/collected/collection-*`
folder after the batch. Open its `index.md`, then each attempt's `review.md` for the
answer, figure gallery, registered result data and links to saved reports/code.
The collector reads `outputs.json.task_results`; it does not discover results by
scanning ordinary NetCDF files, run models, rerun analysis, or modify the original answer.
After a completed attempt has a final answer and collection finishes without errors, the collector
deletes the files over 10 MB in every node's `scratch/` folder: the intermediate arrays, which were
99.6% of the 5.4 GB of one E10 run. Scripts, tables and notes under 10 MB stay, because reports cite
them and a recorded command only calls a script by name. `scratch_cleanup.json` lists every file
removed with its size, and the counts and bytes released and kept. Reports, code, registered outputs
and runtime records are never touched. If a final answer or any nested Expert report cites a scratch
folder by its absolute path, nothing is removed and the reason is recorded. If a removal fails part
way, the status is `partial` and the list shows what went. The collector now deletes files:
do not run it on an older run folder whose scratch you still want to inspect. Later inventory still
reports the released byte count from this record.

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
- Record the commit, actual task IDs, model, dependency versions, budgets, repeats and retry rule
  (each launch's line in `launches.jsonl` has the commit, settings and task IDs). Use
  [methods.example.yaml](experiments/methods.example.yaml) for the external-method comparison, not the
  B/C1/C2 library experiment template.
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
