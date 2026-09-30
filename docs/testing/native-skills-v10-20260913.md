# Native Skills and coordination follow-ups — 2026-09-13

## Implemented

- Every Agent Server role factory supplies `skills=["/skills/"]` to DeepAgents.
  Native SkillsMiddleware discovers metadata; native `read_file` reads selected documents.
  Removed `ocean_list_skills` and `ocean_load_skill`, including their schemas and registration.
- Read-only skill/reference mounts contain a role-scoped, task-owned library snapshot.
  Existing task-role snapshots remain stable; later curated revisions affect new libraries.
- Added `xarray-array-ops`: explicit dimension ordering, exact coordinate alignment,
  per-column indexing, mask/flatten correspondence and bounded examples. The optional
  `oceanx_array_ops` helper is installed in each computational Expert's code directory.
- Coordinator instructions describe question/purpose, existing result paths and useful returns;
  shared prerequisites may be obtained before dependent work. Experts return new-question leads
  and can continue in the same thread/kernel. No mandatory sequencing or scope classifier added.
- Retained native model-call retries with `on_failure="error"`; no whole-Expert replay added.

## Verification

Regression command `python -m pytest tests/test_oceanx tests/test_sandbox -q`:
543 passed, 3 skipped (129.37 seconds). The additional HTTP-503 graph regression was added
after that run collected tests; the final native-Skills suite separately passed all 5 tests.
Targeted lint and `git diff --check` pass. Existing NumPy/netCDF4 and Zarr warnings remain.

`tests/test_oceanx/test_native_skills.py` verifies initial metadata without body injection,
on-demand reading, checkpoint follow-up without a second read, role scoping, write denial,
path containment, numerical helper outputs and invalid-shape rejection. A real graph with a
deterministic model fails twice with HTTP 503 after a tool succeeds: the tool executes once,
and the final answer appears once.

The actual local Agent Server integration's code case reads the Skill, imports/runs its helper,
delivers a report through review, and follows up in the original thread. The follow-up reuses
both Python variables and the imported helper without rereading the Skill. Separate kernel
tests cover isolation and cancellation. These tests start real local processes but use no paid API.

The helper also passes its self-test with the ARM `oceanx` Conda interpreter. Skill schema
validation passes. Wheel inspection confirms inclusion of the native integration, Skill body,
examples and helper module.

## Interpretation limits

Native metadata discovery makes the Skill visible; it does not guarantee a model selects it.
Read Skill bodies can later be summarized out of conversation history; they remain available
to read again. Imported helpers survive only while their Python kernel lives.

No new paid Campeche run was conducted for this change. Reduced token use, less duplicate
analysis, better question decomposition and more useful research follow-ups are not established
by deterministic tests. Do not reclassify the previous failed paid run as successful.

Reference: [DeepAgents native Skills documentation](https://docs.langchain.com/oss/python/deepagents/skills).
