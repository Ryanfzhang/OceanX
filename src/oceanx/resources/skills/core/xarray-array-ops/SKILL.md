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

The optional helper [oceanx_array_ops.py](/skills/xarray-array-ops/scripts/oceanx_array_ops.py)
is available in the OceanX Python kernel as `import oceanx_array_ops as ao`.
Import it once and reuse it. It checks structure, not scientific validity; no data
are inspected automatically. To check installation: `ao.self_test()`.

- `ao.check_dims(field, ("time", "depth", "lat", "lon"))` verifies the intended order.
- `ao.exact_align(field, mask)` refuses silently intersected/misaligned coordinates.
- `ao.column_take(array, indices, axis=1)` gathers one index per remaining column,
  rejecting flattened, out-of-range or differently shaped indices.
- `ao.masked_values(field, mask)` supports a same-shape mask, refusing an accidental
  mix of flattened and two-dimensional arrays. Preserve the same point order for weights.
- `ao.small_sample(ds, n=5)` takes a bounded positional sample without loading the
  whole dataset. Include a wet point and relevant boundary cases yourself: the first
  five positions may be land and are not a scientifically representative sample.

Read [examples](/skills/xarray-array-ops/references/examples.md) for the specific
operation in use, then compare a few output values with a direct scalar calculation.
When correcting an error, inspect the current variable: in a persistent kernel an
earlier cell may have reassigned it. Use `time_values` and `time_module` rather than
using `time` for both an array and the imported module. No kernel restart is needed
just to repair an ordinary shape error.
