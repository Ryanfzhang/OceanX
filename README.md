安装与环境配置见 [INSTALL.md](INSTALL.md)；测评见 [benchmarking/INSTALL.md](benchmarking/INSTALL.md)。

# OceanX

## Native release: start with a new workspace state

This release intentionally does not import old tasks, result formats, or database versions.
Project state now lives in `.oceanx/`; `.oceanmind/` databases and old task folders are left
untouched and are not opened by the new application. Select the project again, create a new
task, and attach its datasets. Dataset attachment remains read-only and does not require
copying the original scientific files. Existing API credentials/settings are retained.

The database is created from `src/oceanx/backend/schema.sql`, with no historical migration
chain. Explicitly pointing `--state-dir` at an old database is rejected, not upgraded.
Agent Server owns native conversation checkpoints. Native Expert tasks have isolated model
contexts. Each research-tree node has its own backend-assigned workspace, and its Python kernel
lives for one attempt; another attempt at the node continues in its files. Old local execution
checkpoints are not imported.

Interactive figures use self-describing NetCDF files saved through
`oceanx.scientific_view.ScientificFigure`. Ordinary NetCDF files are not user-facing figures.
Saved interactive figures whose filenames start with `_` or `.` are drafts, including inside
output subdirectories: their files and previews remain on disk but are not listed as results.
Their previews and interactive views are generated deterministically; there is no Visualization
Expert or model-authored figure specification. Old
JSON/column payloads and previous scientific figure schemas are not converted. The former
Research Tree scheduler and async-tool wrappers have been removed. The current tree is a
question/evidence document edited by the Coordinator; it has no agent lifecycle state. Its decision
log, outcomes and labels feed a human-gated research-policy improvement loop (see
[research-policy operations](docs/research-policy-operations.md)).

After updating, close the running desktop and run `npm start` in `frontend/ocean-desktop`
from the activated OceanX conda environment. It rebuilds an outdated sidecar and frontend.
Do not use an already-running old backend to evaluate these changes.

OceanX is a local-first multi-agent workbench for ocean-science research. It supports
ordinary conversation, paper and dataset inspection, reproducible scientific analysis,
interactive results, and longer autoresearch workflows through one Coordinator-led loop.

## Runtime architecture

For server-side evaluation without Electron, use `ocean run --query ... --output ...`
or `ocean batch --queries queries.jsonl --output ...`. See the
[headless benchmark guide](docs/evals/headless-benchmark.md) for Linux sandbox setup,
read-only shared data, interaction policies and batch resume. Desktop and agent
orchestration behavior are unchanged by this additional client.

```text
Electron Desktop
    ↕ Ocean protocol v2
Local Agent Server (automatically launched)
    ├─ Coordinator (Deep Agents)
    ├─ Native synchronous Expert tasks (Deep Agents)
    ├─ Ocean domain tools
    ├─ report.md summaries + self-describing NetCDF results
    ├─ Native server checkpoints + SQLite UI/file projections
    └─ Isolated persistent scientific Python kernels
```

For open research, the Coordinator selects a bounded subquestion whose answer informs the next
direction, rather than outsourcing the whole investigation as a diagnostic checklist. It updates
a compact backend-owned question tree from returned report summaries, deepening a question,
opening another direction, or concluding. The tree records scientific questions and observations;
it does not schedule agents or duplicate their run state. Simple output requests can be delegated
directly. Delegation uses DeepAgents' native synchronous `task` tool. Independent questions on the
same research-tree frontier can be issued in one Coordinator turn and run concurrently; dependent
questions remain sequential. The server owns task execution, checkpoints and cancellation; the old
orchestrator is deleted, not wrapped inside another scheduler.
There is no separate Data Expert. Before the first analysis Expert of a task starts, the backend
reads the supplied data's metadata once; DatasetContext then lists its variables, dimensions, units
and time ranges for every later agent, and each analysis Expert inspects further detail only when its
question needs it. The backend also supplies the original user request. Native task model
contexts are isolated; each tree node has its own working/output directory and reads the folders
of the nodes it continues read-only. Experts choose their methods and
write the canonical `report.md`, beginning with a short `## Summary`; no second result summary is
generated. If an attempt leaves an existing nonempty report unchanged, it delivers that report
and its original Summary; a short closing reply goes only into the Coordinator receipt. Without
closing prose, the receipt states that fact and the model-call stop reason. The backend saves
the closing reply as `report.md` only when no nonempty report exists, for the Discussion Partner,
or when that reply contains a nonempty `## Summary`. On its last allowed model call an Expert
writes the report as that reply. Another
attempt at the same question is pointed to what the earlier one left. In research mode each
receipt tells the Coordinator the time used; with `OCEANX_RESEARCH_BUDGET_MINUTES` set, no new
Expert assignment starts after 75% of it. Scheduling, cancellation and child completion remain native DeepAgents/Agent Server
state. OceanX does not mirror them into a second database lifecycle. There is no automatic
author/reviewer loop. The Coordinator may explicitly ask another Expert or the read-only Discussion
Partner when a scientific disagreement warrants it. A native task returns its report Summary,
report path and saved `.nc` outputs to the same Coordinator run.
Dependencies determine question order, not an instruction to merge the whole project into one task.
An explicit `task.node_id` must exist after the short node-write wait; otherwise the task returns
an error without starting the Expert. A node ID inferred only from description text may still
run unbound if it does not exist.
Scale reasoning is part of the physics method guide; there is no separate scale-framing Skill.

Scientific code execution persists valid outputs as they are produced. The canonical child
handoff is its backend-assigned `report.md`. A provider interruption therefore does not erase
completed figures or rerun finished code.

Agent Server checkpoints are the source of truth for participant conversation state. The
OceanX task database stores product state, final task results, code-execution provenance, and a
compact user-facing transcript for the Desktop UI.

Python and sandbox checks run when an analysis Expert starts (the one-time metadata read) or
invokes code execution, not when a text-only or literature assignment starts. Code execution
still fails closed if its runtime is unavailable.

Python RAM is not part of a graph checkpoint: kernel/server loss is reported and recovery
uses durable files. Cancellation stops the actual kernel. Current persistent-kernel sandbox
support is macOS/Linux; Windows kernel support has not yet been migrated.

The embedded server uses pinned LangGraph API 0.13.3 and persistent single-host local runtime,
not a PostgreSQL/Redis production cluster. No manual server launch is required. It binds
loopback and uses ephemeral authentication; desktop file attachment requires a separate token.
Install updated dependencies in the selected environment with
`python -m pip install -r requirements.txt`, then rebuild/restart the desktop.
See [current migration design](refine.md) for boundaries and validation.

Transient provider failures are retried at the failed model call without replaying the graph or
Python tools. DeepAgents owns conversation summarization; OceanX does not generate a second result
summary or replace native message history. Authentication, exhausted provider
credit and invalid requests fail explicitly; user cancellation interrupts provider waits.
Each Expert task has at most 60 effective model calls, including native summarization and handoff.
After 48 calls the same DeepAgents run can only read existing evidence and write its assigned report;
one final no-tool call is reserved for delivery. Retryable provider failures (including
API timeouts) do not consume this allowance; their attempts and elapsed time remain
logged. Code execution defaults to a 300-second per-call limit. Kernel death returns
an execution failure immediately instead of waiting indefinitely for an idle message.
Each native task receives its own allowance. These are execution boundaries, not a
scientific acceptance test or a whole-research token budget.

Each analysis round has one editable `supplementary/analysis-*/analysis.ipynb`. A later round
gets a separate notebook; retries do not overwrite existing files or user edits. Notebooks
read the accepted NetCDF results in place, without copying scientific data. Their renderer
preserves contour, uncertainty-band, vector and category layers, axis scales and color domains;
unsupported layers raise an error rather than silently disappear.

## Experience and Skills

Coordinator and executing Experts have DeepAgents' native `ls`, `glob`, `grep`, `read_file`, `write_file`,
`edit_file`, `delete` and `execute` tools. Attached data and shared evidence use real absolute
paths; shell and persistent Python share each Expert's fixed outputs directory. Native shell
execution uses the configured scientific Python environment and existing OS sandbox, not an
unrestricted host shell. Sources, shared evidence and Skills remain read-only. Commands do not
inherit server credentials. Native filesystem operations do not count as scientific executions;
explicit Expert commands use the existing execution records and artifact snapshots.
Agents choose how to inspect data (e.g. a short xarray script), without a required startup scan.
The duplicate OceanX listing, dataset-inspection and text-reading tools have been removed.
Shell processes are fresh; the existing Python tool retains kernel variables within one attempt.
Discussion Partner is read-only: only native `ls`, `glob`, `grep` and `read_file` are exposed,
with no shell/Python execution or file-modification tools.

Research agents use DeepAgents' native `skills=` discovery and `read_file` loading.
Their initial context contains the role's Skill names/descriptions, not all document bodies.
The selected document and references are read on demand from read-only `/skills/` and
`/references/` mounts. The former `ocean_list_skills` / `ocean_load_skill` tools are removed.
Task-role libraries are immutable, content-addressed snapshots of the current bundled files.
Changing bundled guidance selects a new snapshot. Database-generated Skill revisions are not part
of the runtime.

`xarray-array-ops` covers indexing, dimension order, broadcasting and masks. Its optional
`oceanx_array_ops` module is available in the persistent Python kernel; it is not imported or
executed automatically. Small structural checks do not establish scientific correctness.

Runtime guidance changes require an explicit edit to the bundled Skill files. Agents load only the
role-appropriate method documents they need; no background process rewrites Skills from prior runs.
The one exception is a project's approved lessons (`docs/research-policy-operations.md`). In research
mode they are written into the copy of a bundled Skill that the task's library holds, at the end of
the section each lesson names: research-tree decisions into the Coordinator's
`research-trajectory-planning`, analysis lessons into the analysis Skills. The packaged files are not
modified, and a lesson is written only after the project owner approves its exact wording and place.

## Model providers

The Desktop settings support Anthropic-compatible and OpenAI-compatible APIs. OpenAI-compatible
profiles can point at providers such as DeepSeek through a custom base URL. New credentials are
stored outside the project under `~/.oceanmind`; existing local settings can be read once from the
previous configuration location during migration.

## Project state

New projects use:

```text
<project>/.oceanx/
    workspace.sqlite3
    artifacts/
    datasets/
    runs/
    staging/
    exports/
```

## Development

Create the `oceanx` environment once with `conda env create -f environment.yml`.
For an existing environment, use `conda env update -n oceanx -f environment.yml`.
This installs Python 3.11, Node.js 24, and the Python requirements in one environment.

```bash
conda activate oceanx
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"

cd frontend/ocean-desktop
npm ci
npm run check
npm run build
```

Keep `conda activate oceanx` active when running `npm start`, `npm run dev`, or
`npm run build:sidecar`. Local desktop startup and sidecar builds use that
environment's Python and installed dependencies, not a repository `.venv`.
`requirements.txt` includes the scientific runtime and PyInstaller build dependency.
Node.js is managed by `environment.yml`. On Apple Silicon, check that
`node -p process.arch` reports `arm64`; after changing Node architecture, rerun
`npm ci` to replace platform-specific frontend dependencies.
`OCEAN_PYTHON` is an explicit override; otherwise `CONDA_PREFIX` takes priority
over Python on `PATH`. A broken active Conda environment reports an error rather
than silently selecting another interpreter. Installed desktop packages still
use their bundled backend. Scientific code execution also follows active Conda
by default; `OCEAN_CONDA_ENV` and `OCEAN_SANDBOX_PYTHON` remain explicit scientific
runtime overrides. Without activation, scientific execution still looks for the
named `oceanx` environment.

### CARTO basemap key

Copy `frontend/ocean-desktop/.env.example` to `.env.local` in the same directory
and set `VITE_CARTO_BASEMAPS_API_KEY` to your project's
[CARTO Basemaps key](https://carto.com/basemaps/apikey/). The local file is ignored
by Git. Vite reads it for both development and production builds; CI can instead
set the same environment variable. Restart the development server or rebuild the
desktop after changing the key (`npm start` rebuilds; `npm run start:cached` does not).
The key is included in the renderer bundle and sent to CARTO with tile requests.
Keep the existing CARTO and OpenStreetMap map attribution visible.

### Runtime context summaries

Coordinator and Expert graphs use DeepAgents' native conversation summarization unchanged.
OceanX does not maintain a second summary state or copy another agent's transcript into a model
prompt. Expert handoff is instead file-backed: the parent receives the short `## Summary` from
`report.md`, its path and any saved `.nc` results. It reads the full report only when the next
scientific decision or final synthesis needs the detail. Internal summarization prose is metered
but never presented as a participant answer.

Run the OceanX backend tests:

```bash
python -m pytest -q tests/test_oceanx
```

The macOS scientific sandbox starts a nested Seatbelt process. When tests are themselves running
inside another restrictive sandbox, run the trusted-execution tests from a normal host terminal.

Build and inspect the Python wheel:

```bash
python -m hatchling build -t wheel
python scripts/check_ocean_wheel_contents.py
```

The wheel contains only `oceanx`; the former agent-runtime package is not shipped.
