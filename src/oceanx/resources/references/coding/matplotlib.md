# Matplotlib Practices

How to choose and lay out a figure, draw a map and check the result is in
/skills/scientific-figure-design/SKILL.md; this reference holds the code-level details.

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

## Vector arrows

In `quiver`, larger `scale` makes arrows shorter; `scale_units` determines their length units, while
`width` controls shaft width. Calibrate them together using the actual vectors and panel size, and
create `quiverkey` from that same quiver object. Defaults for short arrows can replace them with
dots: `minlength` is measured in shaft widths. If those dots obscure the field, `minlength=0` disables
that replacement; this changes glyph rendering, not the stored vector values. Thin arrow locations
for readability without averaging or normalising the underlying vector field during plotting.

## Editable PDF figures

OceanX's style stores text as TrueType for editing in Illustrator; keep `pdf.fonttype=42`.
Keep lines and colour bars vector (`cbar.solids.set_rasterized(False)` when the colour bar has solids).
For a compact publication PDF, a dense field can use `rasterized=True` at `dpi=300`; that field then
remains an image and cannot be edited as individual shapes. If the researcher needs those shapes
editable, keep them vector. Fonts must also be available on the editing machine.
