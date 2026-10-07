---
name: scientific-figure-style
description: Choose the figure type, colour scale, labels and layout of a scientific figure saved as an image file, so that the figure shows the claim it is cited for. Use before making a final figure.
metadata:
  origin: oceanmind
  roles:
    - ocean_process_expert
    - statistical_inference_expert
---

# Scientific figure style

## when_to_use
Use before you make a final figure with matplotlib: a figure that a reader of your report will look
at. Exploratory plots in your working directory need none of this.

## Match the figure to the claim

- **Where something is** (a pattern, a gradient, a pathway, a front, an eddy, a region that differs
  from another): a map of the field itself, or a section when the structure is vertical. An area
  mean, a bar or a scatter cannot show where.
- **Change in time:** a time series, with the baseline or reference period drawn in.
- **Vertical structure at a place:** a profile, depth increasing downward.
- **Something that moves or evolves in space and time:** a time-distance or time-depth diagram.
- **A relation between two quantities:** a scatter with the fitted line and its uncertainty.
- **A comparison of a few cases:** points or bars with their intervals.

When a conclusion is spatial and you computed it as an index or a box mean, show the map the index
was taken from as well, with the box outlined on it.

## Colour

Choose the colour scale from the meaning of the variable, not from its numerical range.

- A one-directional quantity (temperature, speed, concentration): a sequential scale such as
  `viridis`, `cividis` or `YlGnBu`. If `cmocean` imports, its `thermal`, `haline`, `speed` and `deep`
  scales suit those variables.
- An anomaly, difference, trend, correlation or any quantity with a meaningful centre: a diverging
  scale (`RdBu_r`) with limits symmetric about that centre (`vmin=-v, vmax=v`). The centre is zero
  for ordinary anomalies and differences.
- Unordered classes: a qualitative palette (`tab10`). Ordered classes or bins: steps of one
  sequential scale.
- Never `jet` or `rainbow`. Do not use colour to suggest a centre, an order or a threshold that the
  data do not have.
- Panels that are compared share one colour scale and one colourbar.
- Set limits from robust percentiles (for example the 2nd and 98th) instead of the extremes, and use
  `extend="both"` on the colourbar when they clip.
- Lines: at most about six per panel, told apart by line style or marker as well as colour, with the
  mean or reference in neutral grey.

## Maps and sections

- Land, missing retrievals and cells outside the analysis domain stay missing (`NaN` or a masked
  array). They are never zero and never a colour of the scale. Give the axes a light grey
  background (`ax.set_facecolor("0.85")`) so that they read as "no data".
- Keep the geographic proportions: `ax.set_aspect(1 / np.cos(np.deg2rad(mean_latitude)))`. If
  `cartopy` imports, a projection with coastlines is better.
- Draw gridded fields with `pcolormesh`, and add a few labelled contours when a level matters, such
  as an isotherm, a sea-surface-height contour or a density surface.
- Outline every region, section and box over which the report gives an index, a mean or a budget.
- Label longitude and latitude in degrees east and north. On a section put distance or the varying
  coordinate on x and depth on y, increasing downward.

## Layout and text

- One message per figure. Two to six panels that the reader compares belong together; unrelated
  panels belong in separate figures. Mark panels (a), (b), ... in the upper left.
- `fig, axes = plt.subplots(nrows, ncols, figsize=(3.6 * ncols, 3.0 * nrows), constrained_layout=True)`.
- Every axis and every colourbar has a label with units. A title says what is shown in a few
  words; definitions, baselines and periods go in the report sentence that cites the figure.
- Text of 9 to 11 points. Put the legend outside the data when you can, without a frame.
- Show the uncertainty you computed: an interval band, error bars, or hatching where a trend or a
  difference is not significant.
- Time axes show years or months, not day counts.

```python
import matplotlib.pyplot as plt
import numpy as np

lon, lat = np.linspace(118, 128, 61), np.linspace(24, 34, 61)
x, y = np.meshgrid(lon, lat)
anomaly = 1.8 * np.exp(-((x - 124) ** 2 + (y - 30) ** 2) / 6) - 0.4
anomaly[(x < 120.5) & (y > 29)] = np.nan  # land stays missing

plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "legend.frameon": False})
fig, ax = plt.subplots(figsize=(5.4, 4.2), constrained_layout=True)
limit = np.nanpercentile(np.abs(anomaly), 98)
mesh = ax.pcolormesh(lon, lat, anomaly, cmap="RdBu_r", vmin=-limit, vmax=limit, shading="auto")
lines = ax.contour(lon, lat, anomaly, levels=[1.0], colors="k", linewidths=0.8)
ax.clabel(lines, fmt="%.0f °C")
ax.plot([122, 126, 126, 122, 122], [28, 28, 32, 32, 28], color="k", linestyle="--", linewidth=1)
ax.set_facecolor("0.85")
ax.set_aspect(1 / np.cos(np.deg2rad(float(lat.mean()))))
ax.set(xlabel="Longitude (°E)", ylabel="Latitude (°N)", title="Summer SST anomaly, 2023")
fig.colorbar(mesh, ax=ax, extend="both", label="SST anomaly (°C)")
fig.savefig("sst-anomaly-2023.png", dpi=150, bbox_inches="tight")
```

## Before you save

Check in the code, without opening the image: every axis and colourbar has units; compared panels
share their limits; masked cells are `NaN`; the regions named in the report are outlined. Then save
once. Do not spend further calls on appearance.
