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

A figure for a researcher, or after a paper's figure, is drawn as Nature prints one. Size it as printed,
89 mm (3.5 in) wide for one column or 183 mm (7.2 in) across a page, with 7 pt text, 6 pt tick labels and
legends, and panel letters a, b, c in 8 pt bold above each panel's top-left corner; a reproduced figure
keeps its original's letters. Leave out a figure title, and put caveats, sources and missing data in the
answer, not on the figure.

Create the figure with `layout='constrained'` and attach each colour bar with
`fig.colorbar(mappable, ax=ax, label=...)`. Never place a colour bar, legend or text at hand-set figure
coordinates (`fig.add_axes`, `fig.text`): they land on each other. Nothing may cover anything else; put
legends and values in empty space, never across the data.

Fit each axis to the panel's main series and set its limits after drawing, since matplotlib otherwise
widens it to every line. Draw a raw series faintly behind the main one and let the axes cut it off, as
monthly means when daily values would cross the panel from edge to edge. A quantity with a meaningful
zero, such as an anomaly, trend, vorticity or streamfunction, takes a diverging map such as `RdBu_r`,
white at zero with symmetric limits; never use `jet` or `rainbow` in a figure of your own.

Save with `bbox_inches='tight'`, as a vector PDF where your instructions ask for one. OceanX's style stores
text as TrueType for editing in Illustrator; keep `pdf.fonttype=42`, keep colour bars vector
(`cbar.solids.set_rasterized(False)`), and give only a dense field `rasterized=True`, which then cannot
be edited as individual shapes. When your model reads images, look at the figure once and fix what
breaks these rules.

## Maps

Draw a spatial field on a map, never on bare longitude and latitude axes: cartopy axes in the paper's
projection or PlateCarree, the data drawn with `transform=ccrs.PlateCarree()`, land filled light grey and
coastlines drawn from Natural Earth at the scale of the region
(`ax.add_feature(cfeature.LAND.with_scale('50m'), facecolor='0.9')`, `ax.coastlines('50m', linewidth=0.5)`,
and `'10m'` for a strait or a stretch of coast), with labelled degree gridlines
(`ax.gridlines(draw_labels=True, linewidth=0.3)`). Show the whole region the figure is about, in a
reproduction the original's extent. Leave the data's invalid cells empty, so that the map, not a colour
of the field, shows the land, and set a field that has values on land, such as a streamfunction that is
constant along the coast, to NaN there. cartopy fetches the Natural Earth files on first use and keeps
them in the agent's folder; if that fails, outline the data's land mask as the coastline and say so in
the answer.
