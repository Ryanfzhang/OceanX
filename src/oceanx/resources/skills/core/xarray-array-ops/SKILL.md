---
name: xarray-array-ops
description: Verify NumPy/xarray indexing, broadcasting, per-column take_along_axis, masks versus flattened arrays, and axis-order changes. Use when transforming multidimensional ocean data or fixing shape/index errors.
metadata:
  origin: oceanmind
  roles:
    - ocean_process_expert
    - statistical_inference_expert
---

# Array operations

Keep coordinate meaning attached to dimensions. Equal lengths do not prove two axes
refer to the same locations. Before `.values`, choose an explicit dimension order;
with labeled arrays, align shared coordinates exactly before combining fields.

The helper functions below are in [oceanx_array_ops.py](/skills/xarray-array-ops/scripts/oceanx_array_ops.py).
The OceanX Python kernel has already imported them as `ao`; in a script you run yourself,
start with `import oceanx_array_ops as ao`. They check structure, not scientific validity:
no data are inspected automatically, and every scientific choice (dimensions, units,
weights) is an argument you pass. To check installation: `ao.self_test()`.

<!-- oceanx:tools max=12 -->
<!-- /oceanx:tools -->

Read [examples](/skills/xarray-array-ops/references/examples.md) for the specific
operation in use, then compare a few output values with a direct scalar calculation.
When correcting an error, inspect the current variable: in a persistent kernel an
earlier cell may have reassigned it. Use `time_values` and `time_module` rather than
using `time` for both an array and the imported module. No kernel restart is needed
just to repair an ordinary shape error.
