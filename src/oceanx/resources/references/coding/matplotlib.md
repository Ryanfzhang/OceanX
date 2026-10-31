# Matplotlib Practices

Use a non-interactive backend such as `Agg` for sandboxed static figures. Keep
the plotted array, coordinate orientation, colour mapping, and the data written
to NetCDF as separate inspectable outputs; a visually plausible image does not
validate registration or values.

For current Matplotlib releases, obtain a colormap through
`matplotlib.colormaps` or `matplotlib.pyplot.get_cmap`. Do not rely on the
removed `matplotlib.cm.get_cmap` compatibility function. For transparent missing
data in a static image, use an explicit validity mask; distinguish missing cells
from valid values at the low end of the colour scale.

Choose colour limits from declared values and retain them in the artifact
metadata. Do not use rendering output as the only numerical check: independently
verify the field dimensions, units, coordinate order, and outer edges.

## Publication figures

A figure drawn for a researcher, or after a paper's figure, is laid out as a journal prints it.
Size it as printed, about 7 in wide across a page or 3.5 in for one column, with 8 to 10 pt
text and lines of about 1 pt. Letter each panel in bold inside its top-left corner and leave out
a figure title; the caption or the answer carries it. Stacked panels share their time axis, with
years on top and bottom when the original shows them. Fit each axis to the series the panel is
about: draw a noisier or secondary series lighter behind it and let it run off the axis rather
than squash the main one, and set bar and colour limits that show every bar and value. Put
legends and values such as r or a trend in empty space, never across the data. Save a vector PDF with `bbox_inches='tight'` when requested; set `pdf.fonttype=42` to keep text editable.
Save PNG previews at 300 dpi.

When your model reads images, open the saved figure once and fix what is wrong before delivering
it: clipped or empty panels, squashed curves, overlapping text, panels of uneven size, type too
small to read. For a PDF, open the preview image drawn beside it after the run.

## Maps

Draw a spatial field on a map, never on bare longitude and latitude axes: cartopy axes in the paper's
projection or PlateCarree, the data drawn with `transform=ccrs.PlateCarree()`, land filled light grey and
coastlines drawn from Natural Earth at the scale of the region
(`ax.add_feature(cfeature.LAND.with_scale('50m'), facecolor='0.9')`, `ax.coastlines('50m', linewidth=0.5)`,
and `'10m'` for a strait or a stretch of coast), with labelled degree gridlines
(`ax.gridlines(draw_labels=True, linewidth=0.3)`). Leave the data's invalid cells empty, so that the map,
not a colour of the field, shows the land. cartopy fetches the Natural Earth files on first use and keeps
them in the agent's folder; if that fails, outline the data's land mask as the coastline and say so.
