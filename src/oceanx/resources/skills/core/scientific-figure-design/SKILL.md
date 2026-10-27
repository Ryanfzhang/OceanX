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

## Choosing the figure
Match the plot to the data structure: maps for spatial fields, time series for evolution, profiles
for vertical structure, heatmaps for two-dimensional coordinates, and scatter plots for paired
observations. Use compact axis and colourbar labels with units; put definitions, baselines,
selections, and limitations in the result summary or report instead of forcing them into labels.

## Publication figures
A figure drawn for a researcher, or after a paper's figure, is laid out as a journal prints it.
Size it as printed, about 7 in wide across a page or 3.5 in for one column, with 8 to 10 pt
text and lines of about 1 pt. Letter each panel in bold inside its top-left corner and leave out
a figure title; the caption or the answer carries it. Stacked panels share their time axis, with
years on top and bottom when the original shows them. By default, axis limits show the full range of
all plotted series, including raw and secondary series. Draw noisier series lighter; use an inset or
a separate panel when their range obscures the main variation. If a zoomed or cropped view is needed,
label it explicitly and state which values lie outside the displayed range. Set bar and colour limits
that show every bar and value. Put
legends and values such as r or a trend in empty space, never across the data. Save with
`bbox_inches='tight'`, as a vector PDF where your instructions ask for one, and as SVG too when the
researcher asks for it.

## Maps
Draw a spatial field on a map, never on bare longitude and latitude axes: cartopy axes in the paper's
projection or PlateCarree, the data drawn with `transform=ccrs.PlateCarree()`, land filled light grey and
coastlines drawn from Natural Earth at the scale of the region
(`ax.add_feature(cfeature.LAND.with_scale('50m'), facecolor='0.9')`, `ax.coastlines('50m', linewidth=0.5)`,
and `'10m'` for a strait or a stretch of coast), with labelled degree gridlines
(`ax.gridlines(draw_labels=True, linewidth=0.3)`). Leave the data's invalid cells empty, so that the map,
not a colour of the field, shows the land. cartopy fetches the Natural Earth files on first use and keeps
them in the agent's folder; if that fails, outline the data's land mask as the coastline and say so.

## Reproducing a paper's figure
Reproduce each of the paper's figures as one figure with the same panels, from the reproduced quantities:
the same variables, symbols, units, scales, colour encoding, fills, overlays, reference lines, annotations
and layout. Use matplotlib for the paper's layout, saving a vector PDF where your delivery instructions
ask for one. Show the raw series faintly behind smoothed curves at the paper's time resolution. When you
can read images, read that figure's image, named in the paper's extracted text, again right before drawing
it, since the image read at the start lies far back in the conversation. After saving, open the original
and yours together, compare them item by item (panel layout, fills, line styles, axis ranges and their
multipliers, panel letters, legends and annotations, text that crosses a line, unmarked clipping of any
series, or a main curve flattened by its axis range) and fix every
difference the data allow. Deliver every panel you computed, with any doubt written on it rather than
withholding it. Leave out only a panel whose data are missing, say why, and never fill it with another
quantity.

## Checking the figure
When your model reads images, look at the figure once and fix what is wrong before delivering
it: clipped or empty panels, squashed curves, overlapping text, panels of uneven size, type too
small to read.
