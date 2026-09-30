# Native integration fixes — 2026-09-13

## Scope

Three integration fixes only; no changes to research prompts, roles, Tree,
budgets, model IDs, or credentials in this change.

1. `context.py`, `research/graphs.py`, `backend/router.py`, `tools.py`:
   expose the authorized, resolved dataset path alongside its source handle in
   model context and the Coordinator's resource response. Resolution uses the
   existing dataset resolver, not paths copied from cached metadata. Dataset
   access remains read-only and task-scoped. Metadata disclosure denial still
   takes precedence. This does not add a data-inspection stage.
2. `model_config.py`: select the DeepSeek adapter for explicitly configured
   DeepSeek providers and the official DeepSeek endpoint, including existing
   profiles labelled `openai`. Preserve genuine `reasoning_content` both when
   reading model streams and serializing historical assistant messages for the
   next call, including plain waiting answers before asynchronous resume. Do
   not fabricate missing reasoning or disable thinking.
3. `native_backend.py`: stage native large-edit payloads in the owning agent's
   writable temporary directory, not hardcoded `/tmp/.deepagents_edit_*`.
   Reuse the upstream edit algorithm and existing OS write protection. Clean
   up staging files after success or failure.

DeepSeek's [thinking-mode documentation](https://api-docs.deepseek.com/guides/thinking_mode/)
requires historical reasoning to be returned in tool conversations. The installed
integration's response extraction alone was insufficient; outgoing serialization
also needed correction. See also the [LangChain DeepSeek integration](https://docs.langchain.com/oss/python/integrations/chat/deepseek).

## Automated verification

Command: `.venv/bin/python -m pytest tests/test_oceanx tests/test_sandbox -q --tb=short`

Result: **553 passed, 3 skipped, 4 warnings in 132.37 seconds**.
Warnings were NumPy/xarray deprecation and Zarr v3 consolidated-metadata warnings.

New coverage:

- Formal `dataset.import` of a nested, space-containing directory outside the
  workspace; Coordinator, Ocean Process Expert and Discussion Partner receive
  the actual source path. Real native tools use that model-visible path.
- Coordinator resource lookup returns the same path; native Python can open the
  NetCDF fixture and inspect its dimensions and units.
- Streaming reasoning survives a checkpoint round trip, tool-history repair,
  a plain waiting answer, and an Expert-result notification. Unrelated OpenAI
  endpoints are not reclassified by a model name.
- Large native edits work through sync and async routes; attached evidence
  remains unmodifiable. The actual summarizer archives a large first history
  and appends a second history; both remain readable in the saved archive.
- Existing Discussion Partner test confirms no execution, editing, or delegation
  tools are exposed to that role.

The full pytest suite used the development Python environment. The ARM Conda
environment does not contain pytest; it was verified through the production API
test below rather than installing test dependencies into the user's environment.

## Real API asynchronous handoff

Production entry point: `python -m oceanx run`, using the configured ARM Conda
Python, normal Agent Server, native asynchronous subagent tools, and existing
model profiles. No mock model or alternate handoff implementation.

Artifacts:
`output/deepseek-handoff-fix-20260913/query/attempt-1789286151653934000-72f6217f/`

The engineering query explicitly requested one Discussion Partner, a two-sentence
conceptual answer using existing knowledge, and a final Coordinator response after
that Expert returned. It prohibited analysis, search, file reads and figures for
this small test; these were test instructions, not production prompt changes.

Observed sequence (UTC):

- 07:55:57.991: initial Coordinator request started; an `OpenAITimeoutError`
  occurred after 5.026 seconds. The existing retry mechanism waited and retried;
  the task did not terminate.
- 07:56:32.562: successful Coordinator request; one Expert was dispatched.
- 07:56:36.637: Discussion Partner model call began and completed in 2.998 seconds.
  No code executions were recorded.
- 07:56:40.636: Coordinator resumed from the same thread after the Expert result.
  The provider accepted the resumed request (HTTP 200); no missing-reasoning 400.
- 07:56:51.886: the task completed and saved its final report.

**Wall time: 60.767 seconds.** All three processes (runner, backend, Agent Server)
exited afterwards; no paid run was left active.

Usage from `model_call_observations`, not the terminal envelope's zero-valued
Coordinator usage summary:

| Role | Successful calls | Input | Output | Cached input subset |
| --- | ---: | ---: | ---: | ---: |
| Coordinator | 4 | 33,902 | 1,395 | 19,072 |
| Discussion Partner | 1 | 3,716 | 299 | 128 |
| Total | 5 | 37,618 | 1,694 | 19,200 |

Recorded total: **39,312 tokens**. The initial timed-out call had no returned
usage, so these are recorded tokens, not a guarantee of the provider's billing
total. Cached input is a subset, not an additional chargeable token count here.
Successful model calls totalled 21.908 seconds (including overlapping roles).
The failed initial request and approximately 29.55-second retry interval explain
much of this tiny test's wall time; it was not a minute of scientific computation.

## Limits

This verifies the handoff/resume bug and local filesystem/context regressions,
not the quality or cost of a complete Campeche investigation. No full scientific
rerun was launched. The short model answer's phrasing about a 30-year baseline
was not a scientific acceptance criterion for this engineering test.

Historical checkpoints missing reasoning are not repaired with invented text.
Start a new test with the fixed backend to evaluate the corrected path. An
already-running or previously packaged desktop backend must be restarted or
rebuilt to load these source changes.
