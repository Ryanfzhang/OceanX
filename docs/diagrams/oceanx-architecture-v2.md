# OceanX architecture figure

Reviewed against the local implementation on 2026-10-05. The SVG is the editable,
authoritative source; the PNG is a 3360 × 2560 rendering. Only diagram assets were
added. No runtime configuration, source code, running task, or library was changed.

## Reading the figure

- Panel a represents one research execution. The Coordinator owns scientific tree
  decisions, delegation, adjudication, and final synthesis. Expert follow-ups are
  proposals, not automatic tree edits.
- Ocean and Statistics Experts use isolated workspaces and a persistent Python
  kernel for each attempt. The shared analysis box represents their execution
  facilities, not a shared kernel. Search consultation supplies literature evidence;
  explicitly requested reproduction or acquisition can also use code.
- The Discussion Partner is advisory, not a mandatory acceptance gate.
- Skills are role-scoped guidance; `ao` is an executable Python helper module.
  These are distinct from model-visible file, shell, and kernel tools.
- Panel b represents cross-task library maintenance. Task digests and repeated
  analysis code supply evidence to the meta-agent. New lessons and learned functions
  require evidence from at least three distinct research questions. Tool admission
  includes static checks and sandbox tests; normal review workflows also supply a
  separate review call. That call need not use a different model.
- Owner right/wrong marks, change logs, and content hashes support oversight and
  versioning. Benchmark library snapshots are frozen during evaluation.
- RSI here denotes the implemented cross-task improvement mechanism for skills and
  helper functions, not model-weight training or evidence of improved performance.
  The diagram does not establish that a particular run used learned assets.

## Implementation references

| Relation | Source |
|---|---|
| Specialist identities and authority | `src/oceanx/team/profiles.py` |
| Coordinator ownership of the research tree | `src/oceanx/runtime.py` |
| Background delegation and receipt delivery | `src/oceanx/research/background_experts.py` |
| Agent setup, execution, reports, and per-attempt kernel cleanup | `src/oceanx/research/graphs.py` |
| Model-visible tool registries | `src/oceanx/tools.py` |
| Role-scoped immutable skill copies | `src/oceanx/native_skills.py` |
| Lesson support, revision, retirement, and owner marks | `src/oceanx/research/lessons.py` |
| Repeated-code mining, tool admission, and usage tracking | `src/oceanx/research/toolbook.py` |
| Project library rendering, versions, and snapshots | `src/oceanx/research/review.py` |
| Task digests | `src/oceanx/research/memory.py` |
| Background maintenance and frozen-library guard | `src/oceanx/backend/router.py` |

## Design

Two levels distinguish the live research process from subsequent-task learning.
Navy denotes orchestration, muted teal scientific work, and ochre reusable knowledge.
Solid arrows denote operational flow; dashed lines denote guidance, advisory links,
archiving, and next-task feedback. Configuration-dependent counts and call budgets
are deliberately omitted. Two image-generated drafts were discarded because their
connections were inaccurate; the delivered figure uses explicit vector paths.
