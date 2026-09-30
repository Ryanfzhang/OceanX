# Native file and shell tools — 2026-09-13

## Implemented

- Coordinator and executing Experts use DeepAgents native filesystem middleware:
  `ls`, `glob`, `grep`, `read_file`, `write_file`, `edit_file`, `delete`, `execute`.
- `BaseSandbox` provides the file operations. OceanX adapts command execution to
  its existing OS sandbox; it does not use unrestricted `LocalShellBackend`.
- Real absolute source/result paths are shared across native tools and Python.
  The shell and persistent kernel use the same per-Expert outputs directory and
  configured scientific interpreter. Shell processes do not share kernel RAM.
- Native filesystem helpers and archive transfers do not create scientific
  execution records. Explicit Expert shell commands use the existing execution,
  snapshot, candidate-output and review pipeline.
- Source data, other agents' published evidence and Skill libraries are read-only.
  Writable workspaces are per agent. Shells do not inherit server credentials.
- Removed the custom dataset listing, dataset inspection, text reading and
  context-archive reading tools. Archives now use native `read_file` too.
- Discussion Partner remains read-only: `ls`, `glob`, `grep`, `read_file` only.
  No shell/Python execution, file modification, or subagent delegation tools are exposed.

## Verification

Full local regression: **543 passed, 3 skipped**, 122.84 seconds (four dependency warnings):

```sh
.venv/bin/python -m pytest tests/test_oceanx tests/test_sandbox -q --tb=short
```

New integration tests execute actual processes inside the macOS sandbox with a
deterministic model fixture, not an external model API:

- Native ls/glob/read/write/execute round trip through the DeepAgents graph.
- macOS grep uses the upstream Python search implementation with safe shell quoting.
- Actual Discussion graph exposes only read-only file tools; a model-requested
  `execute` call is rejected and produces no code-execution record.
- A short shell Python script reads a nested NetCDF file's dimensions and units.
- Configured interpreter selection, source-write denial and unrelated-file denial.
- Command cancellation, explicit per-command timeout and subsequent execution.
- Shell-generated files read by persistent Python; kernel variables survive
  intervening shell commands. Commands use the same outputs directory.
- Shell-generated ScientificFigure NetCDF retains renderer metadata.
- Command outputs enter immutable snapshots and canonical report links.
- File/archive transfers do not trigger scientific review.
- Native archive reading survives a checkpoint restart (StateBackend fixture).

Tests do not establish that a real Coordinator will avoid checklist delegation,
that research answers improve, or that token/wall-clock costs decrease. No paid
research run was started. Linux/WSL uses the existing bubblewrap execution path
but was not live-tested here; the POSIX shell adapter does not add native Windows
support. Existing processes/bundled applications must load the new code before a
new research test can exercise it.
