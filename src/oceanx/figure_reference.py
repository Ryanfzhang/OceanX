"""The complete Figure API reference an Expert reads before it draws its first figure.

One text, generated from ``scientific_view``, is the only description of the API: the Expert
prompt points to it, ``.runtime/result-api.md`` is this text, and the figure-design skill refers
to it. Every signature comes from ``inspect.signature``, so it cannot drift from the code; the
notes, the limits and the examples are checked by ``tests/test_oceanx/test_figure_api_reference.py``.
"""
from __future__ import annotations

import inspect
from functools import lru_cache

from oceanx.palettes import ALIASES, PALETTES
from oceanx.scientific_view import ScientificFigure, ScientificPanel

# What the Expert prompt says in place of the API itself.
DRAFT_RULE = (
    "Save a trial figure under a name starting with `_` and a final figure under a plain name: "
    "only final figures are listed as results. Names starting with `.` are also drafts. "
    "A trial figure and its preview stay on disk."
)

_READING_RULE = (
    "Before drawing your first figure, read the complete Figure API at {path} to its end "
    "({lines} lines: call read_file with limit=300 and continue from the offset it reports "
    "until no lines remain). Do not read OceanX source code or probe the API by trial."
)

# For each plot kind: what it is for, and the limits the code enforces (the others are conventions).
PLOT_KINDS: dict[str, str] = {
    "spatial_map": (
        "A regular longitude/latitude field. x is longitude and y is latitude (1-D, strictly monotonic, "
        "at least two values each; longitudes in 0-360 are folded into -180..180) and `z` has shape "
        "(len(y), len(x)). Enforced: exactly one panel holding exactly one layer, a `field2d`, which must "
        "have `valid_mask` and non-empty `units`. `heatmap` (it has no `units`), a second layer of any "
        "kind (contours, vectors, annotations, references) and a second panel are rejected when you save. "
        "`add_feature` is available."
    ),
    "time_series": (
        "A quantity against time. datetime64, datetime and ISO strings automatically become time axes; "
        "x_scale='time' explicitly declares one. Integer "
        "epochs on a declared time axis are rejected. Without a declared time scale, numeric coordinates "
        "remain a linear axis. Typical layers: `line`, `scatter`, `band`, `reference`, `annotations`."
    ),
    "profile": (
        "A quantity against depth or pressure at a station. x is the quantity and y is depth, with "
        "`y_reverse=True` so the surface is at the top. Typical layers: `line` (a short ordered `scatter` "
        "of at most 1,000 points is drawn connected), `band`."
    ),
    "section": (
        "A field on a vertical plane. x is distance, longitude or latitude, y is depth (`y_reverse=True`) "
        "and `z` has shape (len(y), len(x)). Typical layers: `field2d`, `contour_grid`."
    ),
    "hovmoller": (
        "A field against time and a second coordinate. x is time and y is latitude, longitude or depth. "
        "Typical layer: `field2d`; for anomalies use `palette='blue_red'` and a `color_domain` symmetric "
        "about zero."
    ),
    "scatter": (
        "Paired samples. Typical layers: `scatter` (with `color_values` for a third variable), `line` for "
        "a 1:1 line, `field2d` for a density, `categories` for classes. Use `columns=2` or `3` for panels "
        "side by side."
    ),
    "ts_diagram": (
        "Temperature against salinity. x is salinity, y is temperature. Typical layer: `scatter`, coloured "
        "by depth with `color_values`."
    ),
}

# What each layer method takes and what it refuses (the signature is added from the code).
LAYER_NOTES: dict[str, str] = {
    "line": "Connects points. Needs at least two finite (x, y) pairs. Without x or y it uses the panel's.",
    "scatter": (
        "Samples. `color_values` (a third variable, same length) requires `colorbar_label`, and "
        "`colorbar_label` without `color_values` is an error. `color_domain` is [low, high] with low < high; "
        "`radius` must be positive, `opacity` is between 0 and 1; `palette` applies only with "
        "`color_values`."
    ),
    "heatmap": (
        "An alias of `field2d` with filled contours. It takes no `variable`, `units`, `field_kind`, "
        "`render` or `levels`: use `field2d` for those, and for every `spatial_map`."
    ),
    "field2d": (
        "One regular 2-D field `z` of shape (len(y), len(x)) on the panel's x and y. `valid_mask` is a "
        "boolean array of the same shape, True where the cell belongs to the display domain: land, missing "
        "values and cells outside the analysis domain are False and are never encoded as a number. "
        "`field_kind='categorical'` draws cells. When supplied, `category_labels` must cover exactly the "
        "values present; otherwise generic class labels are generated. `category_labels` is an error "
        "for a continuous field. `levels` is an integer from 3 to 32 "
        "or a list of 2 to 32 boundaries. `render` is `filled_contour`, `smooth` or `cells`; `interpolation` "
        "is `linear` or `nearest`. `variable` names the saved array."
    ),
    "categories": (
        "Samples at (x, y) coloured by a category per sample (`category_values`, same length as x; at "
        "least one non-null). `labels` maps a category value to the text shown."
    ),
    "band": "A filled range between `lower` and `upper`, both aligned with x (the panel's x by default).",
    "vector": "An arrow at each (x, y) with components (`u`, `v`). x, y, u and v are 1-D arrays of one length.",
    "contour_paths": (
        "Contour lines you already computed: `paths` is an iterable of dicts "
        "`{'level': float, 'points': [(x, y), ...]}` with an optional 'label'. At most 128 paths of at "
        "most 1,000 points are kept."
    ),
    "contour_grid": (
        "Contour lines of a grid `z` of shape (len(y), len(x)) at the given `levels` (matplotlib "
        "computes them; `z` must be numeric)."
    ),
    "annotations": (
        "Text at data coordinates: `items` is an iterable of dicts with `x`, `y`, `text` and optional "
        "`dx`, `dy`, `arrow`, `align`. At least one item."
    ),
    "reference": "A reference line at `value` on the 'x' or 'y' axis, for example zero or a threshold.",
}

FIGURE_NOTES: dict[str, str] = {
    "panel": (
        "Adds one panel with its own axes. `x` and `y` are 1-D arrays: they define the axes, and a layer "
        "method called without x or y plots against them. For `field2d` and `heatmap` they are the grid "
        "coordinates. `x_scale` and `y_scale` are `linear`, `log`, `time` or `category`; "
        "datetime64, datetime and ISO strings automatically become time axes. "
        "`x_range` and `y_range` take two values."
    ),
    "add_feature": (
        "Names a region, point, interval or curve so the answer can cite it. Give exactly one of "
        "`geometry` (GeoJSON in the panel's data coordinates), `mask` (a boolean array shaped "
        "(len(y), len(x))), `point` (x, y), `bounds` (xmin, ymin, xmax, ymax) or `layer_id` (a `line` or "
        "`scatter` layer). `id` is a unique identifier of letters, digits, `_` or `-` that starts with a "
        "letter. On a map, latitude is within [-90, 90]. Lines and polygons that cross the antimeridian "
        "are rejected: the caller must split them before calling `add_feature`."
    ),
    "save": (
        "Writes the figure as one self-describing NetCDF file, adds the `.nc` suffix if missing, puts a "
        "relative name under `OCEAN_OUTPUT_DIR` and writes a preview image beside it. Saving is what "
        "delivers the figure. Every panel needs at least one layer."
    ),
}

# One complete program per plot kind. Each runs as written and saves a figure.
EXAMPLES: dict[str, str] = {
    "spatial_map": '''\
import numpy as np
from oceanx.scientific_view import ScientificFigure

longitude = np.linspace(-98, -80, 19)
latitude = np.linspace(18, 30, 13)
sst = 27 - 0.35 * (latitude[:, None] - 18) + 0.05 * (longitude[None, :] + 98)  # (len(y), len(x))
ocean = np.ones(sst.shape, dtype=bool)
ocean[:4, :5] = False                              # land is False in valid_mask, never a fill value

fig = ScientificFigure(plot_kind="spatial_map", title="Sea-surface temperature",
                       caption="Annual mean over the northern Gulf of Mexico.")
panel = fig.panel(x=longitude, y=latitude, x_label="Longitude", y_label="Latitude")
panel.field2d(sst, valid_mask=ocean, variable="sst", units="degC", colorbar_label="SST (degC)")
fig.add_feature(id="study_box", label="Study box", bounds=[-96, 20, -84, 28])
fig.save("sst-map.nc")
''',
    "time_series": '''\
import numpy as np
from oceanx.scientific_view import ScientificFigure

time = np.arange("2020-01", "2022-01", dtype="datetime64[M]").astype("datetime64[ns]")
bay = 18 + 4 * np.sin(2 * np.pi * np.arange(24) / 12)
gulf = bay + 1.5

fig = ScientificFigure(plot_kind="time_series", title="Monthly temperature",
                       caption="Bay and Gulf monthly means with the bay's spread.")
panel = fig.panel(x=time, y=bay, x_label="Time", y_label="Temperature", y_units="degC")
panel.line(label="Bay")                            # no x or y: the panel's own x and y
panel.line(y=gulf, label="Gulf")                   # the panel's x, its own y
panel.band(bay - 0.8, bay + 0.8, label="Bay spread")
panel.reference(axis="y", value=20.0, label="Threshold")
fig.save("time-series.nc")
''',
    "profile": '''\
import numpy as np
from oceanx.scientific_view import ScientificFigure

depth = np.array([0.0, 10, 25, 50, 100, 200, 400, 800])
temperature = np.array([20.1, 19.9, 18.7, 16.0, 12.4, 9.0, 6.1, 4.2])

fig = ScientificFigure(plot_kind="profile", title="Temperature profile")
panel = fig.panel(x=temperature, y=depth, x_label="Temperature", x_units="degC",
                  y_label="Depth", y_units="m", y_reverse=True)   # the surface at the top
panel.line(label="Station A")
fig.save("profile.nc")
''',
    "section": '''\
import numpy as np
from oceanx.scientific_view import ScientificFigure

distance = np.linspace(0, 400, 9)
depth = np.array([0.0, 50, 100, 200, 400])
temperature = 22 - 0.03 * depth[:, None] - 0.004 * distance[None, :]   # (len(y), len(x))

fig = ScientificFigure(plot_kind="section", title="Temperature section")
panel = fig.panel(x=distance, y=depth, x_label="Distance", x_units="km",
                  y_label="Depth", y_units="m", y_reverse=True)
panel.field2d(temperature, variable="temperature", units="degC",
              colorbar_label="Temperature (degC)", palette="thermal")
panel.contour_grid(temperature, levels=[8, 12, 16, 20], label="Isotherms")
fig.save("section.nc")
''',
    "hovmoller": '''\
import numpy as np
from oceanx.scientific_view import ScientificFigure

time = np.arange("2020-01", "2021-01", dtype="datetime64[M]").astype("datetime64[ns]")
latitude = np.linspace(-20, 20, 9)
anomaly = 2 * np.sin(np.deg2rad(latitude))[:, None] * np.cos(2 * np.pi * np.arange(12) / 12)[None, :]

fig = ScientificFigure(plot_kind="hovmoller", title="Zonal-mean SST anomaly")
panel = fig.panel(x=time, y=latitude, x_label="Time", y_label="Latitude", y_units="degrees_north")
panel.field2d(anomaly, variable="sst_anomaly", units="degC", palette="blue_red",
              color_domain=[-2, 2], colorbar_label="SST anomaly (degC)")
fig.save("hovmoller.nc")
''',
    "scatter": '''\
import numpy as np
from oceanx.scientific_view import ScientificFigure

rng = np.random.default_rng(0)
observed = rng.normal(20, 3, 200)
modelled = observed + rng.normal(0, 0.8, 200)
group = np.where(observed > 20, "warm", "cool")

fig = ScientificFigure(plot_kind="scatter", title="Model against observations", columns=2)
left = fig.panel(x=observed, y=modelled, x_label="Observed", y_label="Modelled",
                 x_units="degC", y_units="degC")
left.scatter(label="Samples", opacity=0.4)
limits = np.array([observed.min(), observed.max()])
left.line(x=limits, y=limits, label="1:1")
right = fig.panel(x=observed, y=modelled, x_label="Observed", y_label="Modelled")
right.categories(group, labels={"warm": "Warm", "cool": "Cool"})
fig.save("scatter.nc")
''',
    "ts_diagram": '''\
import numpy as np
from oceanx.scientific_view import ScientificFigure

salinity = np.array([34.5, 34.8, 35.0, 35.2, 35.4, 35.5])
temperature = np.array([26.0, 22.0, 18.0, 14.0, 10.0, 6.0])
depth = np.array([0.0, 50, 100, 200, 400, 800])

fig = ScientificFigure(plot_kind="ts_diagram", title="Water-mass structure")
panel = fig.panel(x=salinity, y=temperature, x_label="Salinity", y_label="Temperature", y_units="degC")
panel.scatter(color_values=depth, palette="depth", colorbar_label="Depth (m)", radius=3, opacity=0.9)
fig.save("ts-diagram.nc")
''',
}


class _Raw(str):
    """An annotation printed as written, without the quotes ``from __future__ import annotations`` adds."""

    __repr__ = str.__str__


def signature(name: str, function, *, exclude=()) -> str:
    """``name(...)`` with the parameters as the code declares them, without ``self``."""
    parameters = [
        parameter.replace(annotation=_Raw(parameter.annotation)
                          if isinstance(parameter.annotation, str) else parameter.annotation)
        for parameter in inspect.signature(function).parameters.values()
        if parameter.name not in {"self", *exclude}
    ]
    return f"{name}{inspect.Signature(parameters)}"


def layer_methods() -> list[str]:
    """The public layer methods of a panel, found in the code."""
    return sorted(name for name, _ in inspect.getmembers(ScientificPanel, inspect.isfunction)
                  if not name.startswith("_"))


def figure_reading_rule(path: str) -> str:
    """A paging instruction whose line count follows the generated document."""
    return _READING_RULE.format(path=path, lines=len(figure_api_reference().splitlines()))


def figure_call_skeleton() -> str:
    """The minimal construction sequence, with layer names from the implementation."""
    layers = ", ".join(f"panel.{name}" for name in layer_methods())
    return ("Figure calls: fig = ScientificFigure(plot_kind=..., title=...); "
            f"panel = fig.panel(x=..., y=...); layers: {layers}; fig.save('name.nc').")


@lru_cache(maxsize=1)
def figure_api_reference() -> str:
    """The complete Figure API reference, generated from ``scientific_view``."""
    figure_methods = {name: getattr(ScientificFigure, name) for name in ("panel", "add_feature", "save")}
    palette_names = ", ".join(sorted(PALETTES))
    aliases = ", ".join(f"`{alias}` = `{name}`" for alias, name in sorted(ALIASES.items()))
    lines = [
        "# Figure API reference",
        "",
        ("This is the complete API: every plot kind, every method with its exact signature, and a runnable "
        "example for each plot kind. " + _READING_RULE.format(path="this file", lines="{line_count}")),
        "",
        "```python",
        "from oceanx.scientific_view import ScientificFigure",
        "fig = ScientificFigure(plot_kind=..., title=...)",
        "panel = fig.panel(x=..., y=...)   # one panel is one pair of axes; add layers to it",
        "panel.line(...)                   # a layer method returns the panel, so calls chain",
        "fig.save('name.nc')               # writes the figure under OCEAN_OUTPUT_DIR and delivers it",
        "```",
        "",
        "## Rules",
        "",
        f"- {DRAFT_RULE} This also applies to files in subfolders of the output folder.",
        ("- Compute every array first and pass it in: 1-D lists, NumPy arrays or xarray DataArrays for axes "
        "and samples, 2-D arrays shaped (len(y), len(x)) for fields. NaN and infinity become missing values."),
        ("- datetime64, datetime and ISO strings automatically become time axes. "
        "Set x_scale='time' (or y_scale='time') to declare one explicitly. Integer epoch values on a "
        "declared time axis are rejected as ambiguous."),
        "- A panel with no layer cannot be saved. Layer ids, when given, are unique within a panel.",
        ("- `style` accepts only these keys: `color`, `opacity`, `width`, `dash`, `radius`, `fill`, "
        "`fill_opacity`, `palette`, `marker`. A color is a single browser color (a CSS name, `#RRGGBB` or "
        "`C0` to `C9`); pass numeric arrays through `scatter(color_values=...)`. Omit style arguments "
        "unless the science needs an override."),
        f"- Palettes: {palette_names}; or two or more `#RRGGBB` colour stops. Aliases: {aliases}.",
        "",
        "## ScientificFigure",
        "",
        f"`{signature('ScientificFigure', ScientificFigure.__init__)}`",
        "",
        ("`plot_kind` is one of the kinds listed below; `columns` lays several panels side by side; "
        "`caption` is the sentence under the figure. `source_handle` selects the supplied data source "
        "whose spatial context is inherited; `conclusions` records short scientific claims with the "
        "saved result; `spatial_context` supplies an explicit spatial domain instead of inheriting it."),
        "",
    ]
    for name, function in figure_methods.items():
        lines += [f"### fig.{name}", "", f"`{signature(name, function)}`", "", FIGURE_NOTES[name], ""]
        if name == "panel":
            lines += [
                "Keyword arguments accepted through `fig.panel(..., **kwargs)`:", "",
                f"`{signature('kwargs', ScientificPanel.__init__, exclude=('figure', 'panel_id', 'x', 'y'))}`", "",
            ]
    lines += [
        "## Layer methods (called on a panel)",
        "",
    ]
    for name in layer_methods():
        lines += [f"### panel.{name}", "", f"`{signature(name, getattr(ScientificPanel, name))}`", "",
                  LAYER_NOTES.get(name, ""), ""]
    lines += ["## Plot kinds", ""]
    lines += [f"- `{kind}`: {note}" for kind, note in PLOT_KINDS.items()]
    lines += ["", "## Examples", "", "Each program runs as written and saves one figure.", ""]
    for kind, code in EXAMPLES.items():
        lines += [f"### {kind}", "", "```python", code.rstrip(), "```", ""]
    reference = "\n".join(lines).rstrip() + "\n"
    return reference.replace("{line_count}", str(len(reference.splitlines())))
