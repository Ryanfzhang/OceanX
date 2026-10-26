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
legends and values such as r or a trend in empty space, never across the data. Save at 300 dpi
with `bbox_inches='tight'`.

When your model reads images, open the saved figure once and fix what is wrong before delivering
it: clipped or empty panels, squashed curves, overlapping text, panels of uneven size, type too
small to read.
