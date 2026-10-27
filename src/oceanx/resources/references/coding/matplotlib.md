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

A figure drawn for a researcher, or after a paper's figure, meets the standard of a Nature figure.

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
Fit each axis to the panel's main series, in a time series the smoothed curve with its fills and trend
lines, and set the limits from it after drawing (`ax.set_ylim(...)`): matplotlib otherwise widens the axis
to every line drawn, and a noisy monthly series then flattens the curve the panel is about. Draw the raw
or a secondary series faintly behind the main one and let the axes cut it off; that is intended, never a
reason to widen the axis or to leave the series out. Every bar, every error bar and the main series stay
inside the axes, bars start at zero, and a colour field spans most of its colour scale. A range taken
from another figure, the paper's included, is kept only when your main series fits in it; when it does
not, draw it in full and treat the difference as a result to explain, never clip it.

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

### Words and numbers
Text on a panel is limited to axis and tick labels, the panel letter, a legend and short labels of
features or of values you computed. Every number on a figure is yours; a paper's value may stand beside
yours for comparison, never alone. Put legends and values such as r or a trend in empty space, never
across the data, another label or a frame. Caveats, missing data, sources and method notes go in the
answer, not on the figure, and so does what error bars or shading show (standard deviation, standard
error or a confidence interval) with the number of values behind them.

### No overlaps
Nothing on a figure covers anything else: no text, tick label, legend, colour bar or panel letter touches
another one, a frame or data it does not label. Let the layout place them: create the figure with
`layout='constrained'`, attach every colour bar to its axes with `fig.colorbar(mappable, ax=ax, label=...)`,
and place a legend with `ax.legend` or `fig.legend(loc='outside right upper')`. Never place a colour bar,
legend or text at hand-set figure coordinates (`fig.add_axes`, `fig.text`, or a `cax` made with them):
the layout does not move them, and they land on each other. Two colour bars for one map go one to the
right and one below (`location='bottom'`); side by side they need a figure about 5 in wide or more, or
they squeeze the map away. Keep tick labels apart with fewer ticks (`ax.locator_params(axis='y', nbins=5)`),
`matplotlib.dates.ConciseDateFormatter` for dates, and on a map degree labels on the left and bottom
only (`gl.top_labels = gl.right_labels = False`). Break a long label over two lines rather than let it
run into its neighbour.

### Schematics
A schematic, a globe or a three-dimensional stack of maps is drawn as flat panels of the data it rests
on, in the same arrangement, with its arrows, labels and numbers taken from your results. Never draw
boxes of text in place of a figure, and add no 3-D effects, shadows or decoration to any figure.

### Saving and checking
Save with `bbox_inches='tight'`, as a vector PDF where your instructions ask for one, and as SVG too
when the researcher asks for it. OceanX's style stores text as TrueType for editing in Illustrator; keep
`pdf.fonttype=42`. Keep lines and colour bars vector (`cbar.solids.set_rasterized(False)` when the colour
bar has solids). For a compact publication PDF, a dense field can use `rasterized=True` at `dpi=300`;
that field then remains an image and cannot be edited as individual shapes. If the researcher needs
those shapes editable, keep them vector. Fonts must also be available on the editing machine.

When your model reads images, look at the figure once and fix what is wrong before delivering it: a
bar, error bar, main series or panel cut off by the axes, a main series flattened by a range set for
something else, a colour field without a visible pattern, anything covering something else (text, tick
labels, legends, colour bars, panel letters), a panel squeezed small by its colour bars, panels of uneven
size, type too small to read. A faint raw series running off the axes is not a fault.

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
