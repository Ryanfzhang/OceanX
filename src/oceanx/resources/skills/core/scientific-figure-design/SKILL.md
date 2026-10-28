---
name: scientific-figure-design
description: Draw any figure for a researcher, a paper's figure being reproduced included; choose the plot, lay it out as a journal prints it, draw maps and check the saved figure once.
metadata:
  origin: oceanmind
  roles:
    - ocean_process_expert
    - statistical_inference_expert
    - literature_reproduction_expert
---

# Scientific figure design

## when_to_use
Use before drawing any figure for a researcher, including a figure of a paper being reproduced. The
code-level details of matplotlib, such as colour maps, masks, text that stays editable and dense fields,
are in /references/coding/matplotlib.md.
<!-- interactive -->
A user-facing interactive map or chart is a `ScientificFigure`: [interactive.md](interactive.md) describes
it and the Figure API reference it rests on. Draw with matplotlib, as below, a figure it does not suit and
every figure of a paper being reproduced.
<!-- /interactive -->

## Results, not new analysis
A figure draws results that were computed and saved before it. The plotting code reads them and does
not resample, average, smooth, detrend or normalise them again. When a figure needs another treatment,
compute it as a step of the analysis, say in the answer that the method changed, and compare it with the
result it replaces in a separate supplementary figure, not in the main one.

Fits, correlations and budget residuals are analysis results too: save them with the series, sample
selection and processing they describe, then read them for annotations. An annotation describing a
plotted curve uses that curve's samples, filtering and period. If a statistic instead describes the
raw series or another timescale, label that distinction explicitly.

Select the saved time-resolved series for an evolution plot; an annual summary table does not set
the plot's time resolution. A smoothed main curve retains the timestamps of the series smoothed,
unless the scientific quantity being shown is explicitly defined on a coarser time interval.

Draw the coastline and land as Maps says, and leave empty the cells outside the diagnostic's saved
validity mask: a surface coastline alone does not define the support of a depth layer or derived field.
Keep signed quantities signed; show an absolute magnitude only when
labelled as such and retain its direction separately. Interpretation labels must follow the computed
evidence. When copying a paper's layout, distinguish its claimed pattern from what this run actually
establishes; do not copy the conclusion as a label merely because the original figure uses it.

## Choosing the figure
Match the plot to the data structure: maps for spatial fields, time series for evolution, profiles
for vertical structure, heatmaps for two-dimensional coordinates, and scatter plots for paired
observations. Use compact axis and colourbar labels with units; put definitions, baselines,
selections, and limitations in the result summary or report instead of forcing them into labels.

## Publication figures

A figure drawn for a researcher, or after a paper's figure, meets the standard of a Nature figure.

For a reproduced figure, the original's layout, colours, symbols and line styles take precedence over
generic style defaults; use those defaults where the original is unspecified. This does not override
the computed values, valid support, coordinate registration or the delivery format.

### Size and type
Size it as printed: 89 mm (3.5 in) wide for one column or 183 mm (7.2 in) across a page, and at most
247 mm (9.7 in) high. Use a sans-serif type such as Arial: 7 pt for axis labels and other text, 6 pt for
tick labels and legends, never less than 5 pt, with data lines of about 1 pt and thinner axes and ticks.
Letter each panel a, b, c in 8 pt bold just above the top-left corner of its axes; a reproduced figure
keeps its original's letters. Leave out a figure title, which the answer carries; a panel may carry a
short label of what it shows, such as Upper layer. Write axis labels in sentence case with the unit in
parentheses, such as Temperature (°C). Create the figure with `layout='constrained'`, as in
`plt.subplots(2, 2, figsize=(7.2, 5), layout='constrained')`, so that labels and colour bars make room
for each other. Give panels of one kind the same size and aligned axes, and let stacked panels share
their time axis, with years on top and bottom when the original shows them.

### Ranges come from the values
Set every axis and colour range from the values drawn, the panel's main series first. Draw noisier or
secondary series lighter behind it; use an inset or a separate panel when their range obscures the main
variation. Keep the main series, every bar and error bar inside the axes; bars start at zero, and a
colour field spans most of its colour scale. If a zoomed or cropped view is needed, label it explicitly
and state which values lie outside the displayed range. A range taken from another figure, the paper's
included, is kept only when the main values fit it; when they do not, draw yours in full and treat the
difference as a result to explain.

### Colour
A quantity of one sign, such as temperature, concentration, speed or depth, takes a perceptually uniform
sequential map such as `viridis` or `cividis`. A quantity with a meaningful zero, such as an anomaly,
trend, correlation, vorticity, streamfunction or velocity component, takes a diverging map such as
`RdBu_r`, white at zero with symmetric limits (`vmin=-vmax`, or `norm=TwoSlopeNorm(0)`). Do not use
`jet` or `rainbow` in a figure of your own: they show edges the data do not have and hide the zero; a
reproduced figure may keep its original's map, with zero where the original puts it. Lines and
categories take the style's colour cycle; never tell two series apart by red against green alone, and
add line styles or markers beyond four series. Every colour field has a colour bar labelled with its
quantity and unit.

### Vector arrows
Choose arrow spacing, length scale and shaft width together for the panel's printed size and the
range of vector magnitudes. Representative nonzero vectors should have readable arrowheads, not
merge into a field of dots or overlap their neighbours. Include a reference arrow with units; share
the scale across comparable panels, or give each panel its own labelled scale when they differ.
Preserve relative magnitudes; equal-length arrows show direction only and must be labelled as such.
Matplotlib's scale and short-arrow behaviour are explained in /references/coding/matplotlib.md.

### Words and numbers
Text on a panel is limited to axis and tick labels, the panel letter, a legend and short labels of
features or of values you computed. Every number on a figure is yours; a paper's value may stand beside
yours for comparison, never alone. Put legends and values such as r or a trend in empty space, never
across the data, another label or a frame. Caveats, missing data, sources and method notes go in the
answer, not on the figure, and so does what error bars or shading show (standard deviation, standard
error or a confidence interval) with the number of values behind them.

### Schematics
A schematic, a globe or a three-dimensional stack of maps is drawn as flat panels of the data it rests
on, in the same arrangement, with its arrows, labels and numbers taken from your results. Never draw
boxes of text in place of a figure, and add no 3-D effects, shadows or decoration to any figure.

### Saving
Save with `bbox_inches='tight'`, as a vector PDF where your instructions ask for one, and as SVG too
when the researcher asks for it.

## Maps

For continuous, gridded spatial patterns, prefer filled contours (`contourf`) to a scatter of grid
points. Use scatter for genuinely discrete observations; do not interpolate sparse samples merely
to obtain filled contours.

Draw a spatial field on a map, never on bare longitude and latitude axes: cartopy axes in the paper's
projection or PlateCarree, the data drawn with `transform=ccrs.PlateCarree()`, land filled light grey and
coastlines drawn from Natural Earth at the scale of the region
(`ax.add_feature(cfeature.LAND.with_scale('50m'), facecolor='0.9')`, `ax.coastlines('50m', linewidth=0.5)`,
and `'10m'` for a strait or a stretch of coast), with labelled degree gridlines
(`ax.gridlines(draw_labels=True, linewidth=0.3)`). Show the whole region the figure is about, in a
reproduction the original's extent. Leave the data's invalid cells empty, so that the map, not a colour
of the field, shows the land, and set a field that has values on land, such as a streamfunction that is
constant along the coast, to NaN there. cartopy fetches the Natural Earth files on first use and keeps
them in the agent's folder; if that fails, outline a verified land mask as the coastline and say so in
the answer.

## Reproducing a paper's figure
Reproduce each of the paper's figures as one figure with the same panels in the same arrangement,
from the checked quantities: the same variables, symbols, units, map extent, colour encoding, fills,
overlays, reference lines and panel letters. The numbers on the figure are yours; a paper's value may
stand beside a computed value for comparison, never alone. Draw every element the data support,
including estimated trends; leave an unsupported element out, name it in the answer and do not replace
it with another quantity or period.

Keep the original's visual hierarchy: raw series faintly behind the selected main curve and its fills,
with secondary variables on their own axes where the original uses them. Plot the saved time-resolved
series at the selected analysis resolution. Draw smoothed curves and fills only at valid timestamps.
Keep the original's axis and colour ranges when the main values fit them; otherwise show those values
and explain the difference. A noisy background series must not flatten the main curve: use a labelled
crop, inset or supplementary panel when needed. Method and smoothing-window comparisons belong in a
separate supplementary figure, not overlaid on the reproduction's main panels.

When you can read images, open the original again right before drawing it. After saving, open the
original and yours together and compare panel layout, fills, line styles, axis ranges and multipliers,
colour scales, panel letters, legends and labels. Fix overlaps, unreadable type, empty panels and main
curves flattened by their axes, and check for a series clipped where the original does not clip it.
Deliver every computed panel and put its doubts in the answer.

For definitions and adaptation of the scientific method, use /skills/paper-reproduction/SKILL.md.
Apply the publication and map standards above; implementation details remain in
/references/coding/matplotlib.md.

## Checking the figure
Check the figure's inputs against the selected saved results, including their units, signs, masks and
the series behind annotations. If a mismatch is in the computation, correct the analysis and regenerate
the affected figure; changing its sign, limits or labels is not a numerical correction.

When your model reads images, look at the figure once and fix what is wrong before delivering
it: clipped or empty panels, squashed curves, overlapping text, panels of uneven size, type too
small to read.
