---
name: scientific-figure-design
description: Declare scientifically meaningful interactive figures from already-computed ocean-analysis arrays.
metadata:
  origin: oceanmind
  roles:
    - ocean_process_expert
    - statistical_inference_expert
---

# Scientific figure design

## when_to_use
Use when an analysis result needs a user-facing interactive map or chart. Construct a
`ScientificFigure` from the computed arrays, explicit axes and explicit layers, then call
`figure.save("name.nc")`. That save declares a figure; ordinary NetCDF files remain data files.
Do not write renderer JSON. Omit visual style arguments when the Workbench defaults are sufficient.
Keep intermediate arrays and ordinary NetCDF caches in `OCEAN_WORK_DIR` (the default working
directory). Save only final user-facing figures with `ScientificFigure.save(...)`, which writes
to `OCEAN_OUTPUT_DIR`; task scratch can be cleaned after the task becomes idle.

## Palette semantics

Choose a palette from the meaning of the variable, not merely from its numerical range:

- For an ordinary non-negative or otherwise one-directional continuous quantity, omit the palette
  or use `ocean_teal`. OceanX uses Ocean teal as the sequential default.
- For anomalies, differences, signed tendencies, correlations, or any quantity with a meaningful
  centre, use `palette="blue_red"`. When equal positive and negative departures must be compared
  visually, also pass a `color_domain` symmetric about the scientifically meaningful centre (zero
  for ordinary anomalies and differences).
- For ordered groups, bins, or stages, use `grouped`; it uses the same continuous blue-to-red
  progression. For unordered nominal classes, use `categorical` so neighbouring classes do not
  imply an ordering.
- When a different scale better expresses the result, explicitly request one of `viridis`,
  `cividis`, `magma`, `plasma`, `blues`, `depth`, `thermal`, or `chlorophyll`. An explicit supported
  palette always overrides the defaults.
- A custom continuous palette may be supplied as two or more six-digit hexadecimal colour stops.
  Do not use colours to imply a centre, order, threshold, or category that the data do not have.

## Figure construction

Before drawing your first figure, read [the complete Figure API reference](API.md) to its end
({{FIGURE_API_LINE_COUNT}} lines: call read_file with limit=300 and continue from the offset it
reports until no lines remain). It is
generated from the same implementation as the `Result API reference` file named in your system
prompt; use its exact signatures, plot-kind restrictions and runnable examples rather than
reading OceanX source code or testing guessed arguments. Save trial figures with `_`-prefixed
names and final figures with plain names. Names starting with `.` are also drafts; their files
and previews stay on disk but are not listed as results.

Match the plot to the data structure: maps for spatial fields, time series for evolution, profiles
for vertical structure, heatmaps for two-dimensional coordinates, and scatter plots for paired
observations. Keep titles interpretive but short. Use compact axis and colourbar labels with units;
put definitions, baselines, selections, and limitations in the result summary or report instead of
forcing them into labels.

Choose every scientific encoding explicitly. Add each comparison as its own line or scatter layer.
Use `color_values` only when a third variable should encode point colour and a colorbar genuinely
adds information. Never repeat x or y as colour merely to decorate the plot.

For every spatial map, preserve the scientific validity mask. Land, missing retrievals, and cells
outside the analysis or comparison domain must be `NaN`/`None`, or excluded with
`field2d(..., valid_mask=valid_cells)`, so the Workbench leaves them transparent over the basemap.
Never turn those cells into a plotted sentinel such as category `0`. Categorical spatial maps
and continuous spatial maps both require an explicit Boolean `valid_mask`; values then describe
only cells that belong to the display domain. A genuine zero measurement remains valid when its
mask is `True`—for example, zero satellite retrievals over valid ocean must not be conflated with
land.

```python
import numpy as np
from oceanx.scientific_view import ScientificFigure

lag = np.arange(-3, 4)
correlation = np.array([0.1, 0.3, 0.6, 0.9, 0.6, 0.3, 0.1])
figure = ScientificFigure(plot_kind="scatter", title="Lag correlation")
panel = figure.panel(x=lag, y=correlation, x_label="Lag", y_label="Correlation")
panel.scatter()
figure.save("lag.nc")
```

```python
import numpy as np
from oceanx.scientific_view import ScientificFigure

salinity = np.array([34.5, 34.8, 35.0, 35.2])
temperature = np.array([26.0, 20.0, 14.0, 8.0])
depth = np.array([0.0, 50.0, 200.0, 800.0])
figure = ScientificFigure(plot_kind="ts_diagram", title="Water-mass structure")
panel = figure.panel(x=salinity, y=temperature, x_label="Salinity", y_label="Temperature")
panel.scatter(color_values=depth, palette="depth", colorbar_label="Depth (m)")
figure.save("samples.nc")
```

```python
import numpy as np
from oceanx.scientific_view import ScientificFigure

longitude = np.array([120.0, 121.0, 122.0, 123.0])
latitude = np.array([20.0, 21.0, 22.0])
comparison_class = np.array([[1, 1, 2, 3], [1, 2, 2, 3], [1, 2, 3, 3]])
wet_cells = np.ones(comparison_class.shape, dtype=bool)
wet_cells[0, 0] = False
comparison_domain = np.ones(comparison_class.shape, dtype=bool)
comparison_domain[-1, -1] = False
figure = ScientificFigure(plot_kind="spatial_map", title="Comparison domain")
panel = figure.panel(x=longitude, y=latitude, x_label="Longitude", y_label="Latitude")
panel.field2d(
    comparison_class,
    valid_mask=wet_cells & comparison_domain,
    field_kind="categorical",
    category_labels={1: "Both sources", 2: "Model only", 3: "Satellite only"},
    variable="comparison_class",
    units="1",
    palette="categorical",
)
figure.save("comparison-domain.nc")
```

For a model-chosen sequential alternative, pass `palette="viridis"` to the layer. For a centred
anomaly, pass `palette="blue_red"` and a scientifically justified symmetric `color_domain`.

Preview images are optional scientific evidence. Inspect one only when interpreting the image is
part of the analysis, for example to identify a spatial pattern. Do not add a separate visual review
or repair round after the figure has been saved.
