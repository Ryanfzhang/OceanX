# Codex handoff: verify the 2026-10-03 fixes on E10 and decide what to change

Roles. **Leader: Claude** (designs and approves changes). **Executor: Codex** (runs the checks,
reports, and makes only the pre-approved fixes below). **Owner: the user** (commits every
version so any change can be reverted, and decides when the leader takes over again).
When something is not covered here, stop, write it in the Log at the end, and wait for the leader.

## 1. What changed since the slow run `methods-oceanx-flash-r1`

r1 ran at `f82bc4a`. Its OceanX attempt is under
`/import/home3/share/oceanx-bench/methods-oceanx-flash-r1/runs/OceanX/E10/`.

| Commit | Change | Main code |
|---|---|---|
| `8df7791` | A read-only root inside a writable root is ignored on every platform; on Linux the kernel is launched without a parent PID (ipykernel's parent watcher killed it under bubblewrap); kernel output goes to `<agent>/kernel/kernel.log` and a failed start reports its last lines | `sandbox/execution.py` `SandboxExecutionPolicy.__post_init__`; `kernels.py` |
| `e9f490e` | Kernel tests use the resolved launcher, as production does | `tests/test_oceanx/test_persistent_kernels.py` |
| `6cbd4f0` | One folder and one kernel per research node (not per root branch); the kernel closes after each attempt; an Expert is told the folders of the nodes above it and of its dependencies; team cards follow the bound node | `research/services.py` `expert_agent_key`; `research/graphs.py` `_close_kernel`, `_earlier_work`; `deep_runtime.py`; `backend/router.py` |
| next commit (report delivery, research budget, kernel preflight) | Call 60 writes the whole report as its reply, with one plain-text retry if the model prints tool markup; an attempt without `report.md` delivers its closing reply as the report; a repeat attempt is pointed to the earlier report and files; each Expert receipt shows time used and assignments, and with a budget no new assignment starts after 75% of it (the benchmark budget is the case time limit, 135 of 180 min); preflight starts a kernel and saves twice; `run_record` names failure causes | `research/graphs.py` `ExpertCallBudgetMiddleware`, `_prose`, `receipt`, `_earlier_attempt`, `ResearchBudgetMiddleware`, `RESEARCH_BUDGET_STOP`; `server/run_oceanx.py` `backend_environment`; `sandbox_self_check.py` `run_kernel_self_check`; `server/benchmark_config.py` `preflight`; `evaluation/evaluate.py` `code_failures` |

r1 baseline (partial, from the owner's diagnosis and a later scan):
- About 70 min in: 581 model calls, with a model call running 83% of the time.
- 326 code runs, 61 failed: 34 kernel start failures and 1 time limit. The later scan counted 355 runs: 321 shell and none in a working kernel.
- 32 "Read-only file system" lines, 26 of them in the agent's own outputs. Ten of the first 15 were write probes.
- Only 3 agent folders for the whole tree.
- B1.3.1 needed 3 attempts; B1.4.1.1 used 60 calls and produced no report.

## 2. Run the check (Linux server, `oceanx-bench`, from `/home/mafzhang/code/OceanX`)

1. Pull. Confirm `git log -1` is the commit the owner named. Change no code while a run is going.
2. Preflight. This now includes the kernel check, and it must print `"environment_ready": true`:

   ```bash
   python benchmarking/server/check_setup.py --agent oceanx
   ```

3. Linux-only tests. On macOS the Linux tests are skipped and seatbelt never enforced the read-only bug, so these must pass here:

   ```bash
   PYTHONPATH=src python -m pytest tests/test_sandbox tests/test_oceanx/test_persistent_kernels.py tests/test_oceanx/test_sandbox_self_check.py -q -p no:cacheprovider
   ```

4. In `benchmarking/.env`, change only these settings and keep everything else as in r1:
   - `BENCH_EXPERIMENT=methods-oceanx-flash-r2`
   - `BENCH_SUITE=evolution`, `BENCH_EVOLUTION_SET=`, `BENCH_TASKS=E10`
   - `BENCH_MODEL=deepseek-flash`, `BENCH_TIMEOUT_SECONDS=10800`
   - `BENCH_OCEANX_MAX_PARALLEL_EXPERTS=2`, `BENCH_RESUME=false`

   Then run `python benchmarking/server/run_oceanx.py` under tmux.
5. Check that the E10 query text and the datasets in `inputs/queries.jsonl` match r1. If they differ, r1 is not a comparator. Report this and stop.
6. Write run records for both runs. The new `evaluate.py` also classifies r1's failures:

   ```bash
   python benchmarking/evaluation/evaluate.py inventory --runs /import/home3/share/oceanx-bench/methods-oceanx-flash-r1/runs/OceanX --out /import/home3/share/oceanx-bench/methods-oceanx-flash-r1/eval/inventory
   ```

   ```bash
   python benchmarking/evaluation/evaluate.py inventory --runs /import/home3/share/oceanx-bench/methods-oceanx-flash-r2/runs/OceanX --out /import/home3/share/oceanx-bench/methods-oceanx-flash-r2/eval/inventory
   ```

7. Count kernel runs, shell runs and folders in the new attempt (read-only):

   ```bash
   python - /import/home3/share/oceanx-bench/methods-oceanx-flash-r2/runs/OceanX <<'EOF'
   import sys
   from pathlib import Path
   root = Path(sys.argv[1])
   runs = [p for p in root.glob("*/attempt-*/workspace/*/*/agents/*/.runtime/executions/*") if p.is_dir()]
   shell = sum((p / "code" / "command.sh").is_file() for p in runs)
   agents = {p.parents[2] for p in runs}
   folders = [p for p in root.glob("*/attempt-*/workspace/*/*/agents/*") if p.name != "coordinator"]
   logs = [p for p in root.glob("*/attempt-*/workspace/*/*/agents/*/kernel/kernel.log") if p.stat().st_size]
   print(f"code runs {len(runs)}: kernel {len(runs) - shell}, shell {shell}; "
         f"agents with code {len(agents)}; agent folders {len(folders)}; non-empty kernel logs {len(logs)}")
   EOF
   ```

## 3. Scorecard: what to look at

Read `run_record.md` of r1 and r2 side by side. Its "Code runs" line names the failure causes. Its question table gives each node's attempts, how many of them had no report, its minutes and its tokens.

| # | Check | Pass | If it fails |
|---|---|---|---|
| 1 | Preflight and the Linux tests | all pass | Case P |
| 2 | `kernel start` failures | 0 | Case K |
| 3 | `read only` failures | 0 | Case R |
| 4 | Attempts without a report (sum over nodes) | 0 | Case D |
| 5 | Most attempts at one node | at most 2 | Case A |
| 6 | Status `completed`, with a final report and `answer.md` | yes | Case T |
| 7 | Total minutes | under 180; no new assignment after about 135 | Case T |
| 8 | Agent folders compared with tree nodes | one folder per node and role; two nodes never share one | Case I |
| 9 | `code` failures as a share of code runs | report it next to r1's share from its new run record (r1's 61 of 326 failures were mostly kernel starts) | Case C (report only) |
| 10 | Kernel runs compared with shell runs (step 7) | informational | Case S (report only) |
| 11 | Wall time and model calls compared with r1 | report the change | Case W |

## 4. Situations and what to do

Pre-approved fixes are marked **Fix**. Make each one as a separate change (§5).

**P: preflight or a Linux test fails.** Read the reason. Kernel errors now include the kernel's own output.
- `bwrap: execvp ... No such file or directory`: the interpreter path is not mounted. Production must use `runtime.executable` (`_validate_python_launcher` resolves its folder). Find out which caller passes an unresolved path. **Fix** only if it is a caller that bypasses `runtime.executable`.
- `Parent appears to have exited`: the bubblewrap kernel was given a parent PID. Check `SandboxedKernelManager.independent` in `kernels.py`. **Fix** a regression there.
- `Read-only file system` in the kernel check: the policy normalization regressed. See R.
- Anything else: stop and report. Do not start the benchmark.

**K: kernel start failures > 0.** Read the error in `code_executions.result_json` (the run record counts it) and that agent's `kernel/kernel.log`.
- One or two failures with a port or address conflict (`Address already in use`, ZMQ bind): **Fix** by retrying the kernel start once in `KernelPool.execute`, with a new manager and a new connection file. Add a test with a manager whose first start fails.
- Systematic failures, or any other message: stop and report it with the log lines.

**R: read-only failures > 0.** Take the path from the stderr.
- The path is inside the agent's own folder: this is a regression. Check `SandboxExecutionPolicy.__post_init__` and the two policy builders, `expert_execution._run_started_python` (execute and kernel) and `native_backend.OceanSandbox.aexecute` (file tools). **Fix** it, with a test in `tests/test_sandbox/test_linux.py` that inspects `build_bubblewrap_command`.
- The path is another agent's folder or a data folder: this is by design. Report how often it happens and which node. Do not add prompt text and do not loosen the sandbox.

**D: an attempt has no report.** The node's receipt says `Result: No report — it reached its 60-call limit` or `it stopped after N calls`.
- The reply to call 60 was still tool markup after the retry: find the raw text in the Expert's checkpoint or conversation history. If it starts with a marker that `_TOOL_MARKUP` in `graphs.py` does not cover, **Fix** by adding that marker, with a test that uses the exact sample. Any other cause: report.
- The attempt ended by an exception (a provider error in `backend.log`): report it. Do not add retries.

**A: three or more attempts at one node.** Read each attempt's `Result:` line.
- The Coordinator asked again because the science was incomplete: that is policy behaviour. Report it and do not change it.
- The retries followed failures: handle them as K, R or D.
- A repeat attempt redid the heavy work instead of reusing the earlier files: report the node and the evidence. Prompt wording is the leader's decision.

**T: timeout, no final report, or assignments after the budget stop.**
- The receipts show no `Research status: ... of a 180-minute budget` line (grep the checkpoints with `grep -a -o "Research status: [^\"]*" -r <attempt>/state | tail`): the budget did not reach the Agent Server. Check `run_oceanx.backend_environment` and that the backend and Agent Server inherit the environment. **Fix** the wiring.
- The stamp is there and assignments were refused (`Not started: most of the research time budget`), but the Experts still running took more than 45 min after the stop: **Fix** by lowering `RESEARCH_BUDGET_STOP` in `graphs.py` to 0.65, and update the numbers in `RUNNING.md` and the tests.
- The Coordinator's synthesis itself was the slow part: report it.

**I: two nodes share a folder, or many delegations are unbound.** Count the tree events with `binding` set to `inferred` or `unbound` (the research tree store under `agents/coordinator`).
- Two bound nodes have the same `expert_agent_key`: **Fix** it, with a test in `tests/test_oceanx/test_native_subagents.py`.
- The Coordinator often omits `node_id`: report it. That is a prompt decision.

**C: code failures.** Group the stderr by type: shape or broadcast, missing names or keys, imports, others. Report the counts and two examples of each. Do not write skills, lessons or helper tools by hand; the meta-agent owns them.

**S: kernel compared with shell.** Report the share of runs that used the kernel and their failure rate. Whether to keep the kernel tool is the leader's decision.

**W: speed.** Report minutes, model calls, the share of time in model calls, attempts per node and the longest chain of nodes that ran one after another, for r1 and r2. If r2 is slower, say where the extra minutes went, from the question table. Do not tune anything.

All checks pass: report the scorecard. Do not start formal or test-suite runs, change parallelism or try reasoning settings without the leader.

## 5. How to make a change

- Change only what a **Fix** above names, one problem per change. Never touch:
  - the data, `download/data_manifest.json`, rubrics or references;
  - the policy `v2-nested` and the 60-call limit;
  - the learned library or skill regions;
  - sandbox strictness or network access.
- First add a test that fails without the fix. Keep the change minimal, in the named function, and follow the code's style.
- Run the whole suite. `benchmarking/tests/test_run_claude.py::test_timeout_kills_children_retains_outputs` is timing-sensitive; rerun it once before calling it a failure.

  ```bash
  PYTHONPATH=src python -m pytest tests benchmarking/tests -q -p no:cacheprovider
  ```

- Update `RUNNING.md` or `README.md` if the behaviour changes.
- Add an entry to the Log below. Then ask the owner to commit; never rewrite history or force-push.
- Re-check only after the owner commits, each time under a new experiment name (`methods-oceanx-flash-r3`, ...).
- If a change makes things worse, the owner reverts that commit with `git revert`.
- Privacy: CMOMS stays private. Never commit its data or anything computed from it, and never send either to outside services. Never show rubrics, references or answer keys to agents.

## 6. Report back to the leader

Write in the Log:
1. The scorecard for r1 and r2 (section 3).
2. Each situation you met, with its evidence: paths, counts and short excerpts.
3. Each change you made: the files, the new test, the commit the owner made, and the re-check result.
4. Open questions for the leader.

## Log

<!-- Codex: newest entry first. Date, situation, evidence, change (or "report only"), tests, re-check. -->
