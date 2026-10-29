"""One generated, executable Figure API reference reaches every interactive Expert."""

import inspect
import re
from pathlib import Path
from typing import get_args

import numpy as np
import pytest
import xarray as xr

from oceanx.artifacts.models import InteractiveViewContent
from oceanx.figure_reference import EXAMPLES, LAYER_NOTES, PLOT_KINDS, figure_api_reference
from oceanx.native_text import text_read
from oceanx.research import graphs
from oceanx.research.services import AgentRun
from oceanx.scientific_view import ScientificFigure, ScientificPanel
from tests.test_oceanx.test_saved_data_index import _backend

SKILL = Path(__file__).parents[2] / "src/oceanx/resources/skills/core/scientific-figure-design/SKILL.md"


def _signature(name, function):
    sig = inspect.signature(function)
    parameters = [p for p in sig.parameters.values() if p.name != "self"]
    text = str(inspect.Signature(parameters))
    for parameter in parameters:
        if isinstance(parameter.annotation, str):
            text = text.replace(repr(parameter.annotation), parameter.annotation)
    return name + text


def test_reference_has_every_declared_kind_layer_and_exact_signature():
    reference = figure_api_reference()
    kinds = set(get_args(InteractiveViewContent.model_fields["view_kind"].annotation))
    methods = {name: method for name, method in inspect.getmembers(ScientificPanel, inspect.isfunction)
               if not name.startswith("_")}
    assert set(PLOT_KINDS) == set(EXAMPLES) == kinds
    assert set(LAYER_NOTES) == set(methods)
    for name, method in methods.items():
        assert f"### panel.{name}" in reference
        assert f"`{_signature(name, method)}`" in reference
        assert LAYER_NOTES[name].strip() and LAYER_NOTES[name] in reference
    for name in ("panel", "add_feature", "save"):
        assert f"`{_signature(name, getattr(ScientificFigure, name))}`" in reference
    assert f"`{_signature('ScientificFigure', ScientificFigure.__init__)}`" in reference
    assert "panel(figure:" not in reference
    assert "In interactive mode" not in reference
    assert "name starting with `_`" in reference
    for kind in kinds:
        assert f"### {kind}" in reference
        assert PLOT_KINDS[kind] in reference


@pytest.mark.parametrize("kind", sorted(EXAMPLES))
def test_each_reference_example_saves_one_self_describing_figure_and_preview(tmp_path, monkeypatch, kind):
    monkeypatch.setenv("OCEAN_OUTPUT_DIR", str(tmp_path))
    reference = figure_api_reference().split("## Examples\n", 1)[1]
    programs = dict(re.findall(r"### (\w+)\n\n```python\n(.*?)\n```", reference, flags=re.DOTALL))
    assert set(programs) == set(EXAMPLES)
    exec(compile(programs[kind], f"reference:{kind}", "exec"), {"__name__": "__main__"})  # noqa: S102 - trusted bundled example
    paths = list(tmp_path.glob("*.nc"))
    assert len(paths) == 1
    assert paths[0].with_suffix(".preview.png").stat().st_size > 0
    with xr.open_dataset(paths[0]) as dataset:
        assert dataset.attrs["ocean_view_schema"] == "ocean-view-netcdf/v1"
        assert dataset.data_vars


def test_every_skill_example_is_self_contained_and_uses_the_shared_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("OCEAN_OUTPUT_DIR", str(tmp_path))
    text = SKILL.read_text()
    assert "API.md" in text
    programs = re.findall(r"```python\n(.*?)\n```", text, flags=re.DOTALL)
    assert programs
    for i, program in enumerate(programs):
        exec(compile(program, f"figure-skill:{i}", "exec"), {"__name__": "__main__"})  # noqa: S102 - trusted bundled example
    paths = list(tmp_path.glob("*.nc"))
    assert len(paths) == 3
    assert all(path.with_suffix(".preview.png").stat().st_size > 0 for path in paths)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ocean_process_expert", "statistical_inference_expert", "literature_reproduction_expert"])
async def test_interactive_expert_reads_shared_reference_not_inline_api_trials(tmp_path, monkeypatch, role):
    monkeypatch.setenv("OCEANX_FIGURE_DELIVERY", "interactive")
    async with _backend(tmp_path, monkeypatch) as (host, task, config, seen):
        run = AgentRun.from_config(config, role, question="B1: figure reference")
        await graphs.build(config, role, run=run)
        root = host.task_workspace_projector.expert_session_root(task.task_id, run.thread_id)
        api = root / ".runtime/result-api.md"
        reference = figure_api_reference()
        assert api.read_text() == reference
        prompt = seen["system_prompt"]
        assert str(api) in prompt and "before drawing your first figure" in prompt.lower()
        assert "Figure API" in prompt and "In interactive mode" not in prompt
        assert "ScientificFigure(*," not in prompt
        assert "Examples:" not in prompt
        reading = next(line for line in prompt.splitlines() if "complete Figure API" in line)
        assert "to its end" in reading and "once" not in reading
        assert f"{len(reference.splitlines())} lines" in reading
        assert "limit=300" in reading and "offset" in reading
        skeleton = next(line for line in prompt.splitlines() if "fig = ScientificFigure" in line)
        assert "panel = fig.panel(x=..., y=...)" in skeleton
        assert "fig.save('name.nc')" in skeleton
        for name, _method in inspect.getmembers(ScientificPanel, inspect.isfunction):
            if not name.startswith("_"):
                assert f"panel.{name}" in skeleton
        library = Path(seen["skill_library"])
        skill = library / "skills/scientific-figure-design"
        if role != "literature_reproduction_expert":
            assert (skill / "API.md").read_text() == reference
            assert "API.md" in (skill / "SKILL.md").read_text()
            skill_text = (skill / "SKILL.md").read_text()
            assert "to its end" in skill_text and "reference](API.md) once" not in skill_text
            assert f"{len(reference.splitlines())} lines" in skill_text
            assert "limit=300" in skill_text and "offset" in skill_text
        else:
            assert not skill.exists()  # role scoping stays unchanged


@pytest.mark.parametrize("failure", ["mask", "extra_layer", "second_panel", "heatmap", "scatter_color", "epoch"])
def test_documented_restrictions_are_enforced_without_changing_the_api(tmp_path, failure):
    if failure == "scatter_color":
        figure = ScientificFigure(plot_kind="scatter", title="Paired")
        with pytest.raises(ValueError, match="colorbar_label"):
            figure.panel(x=[1, 2], y=[2, 3]).scatter(color_values=[10, 20])
        return
    if failure == "epoch":
        figure = ScientificFigure(plot_kind="time_series", title="Time")
        with pytest.raises(ValueError, match="integer epoch"):
            figure.panel(x=[1700000000, 1700000001], y=[2, 3], x_scale="time")
        return
    figure = ScientificFigure(plot_kind="spatial_map", title="Map")
    panel = figure.panel(x=[-96, -95], y=[20, 21])
    values = np.ones((2, 2))
    if failure == "mask":
        with pytest.raises(ValueError, match="valid_mask"):
            panel.field2d(values, units="degC")
        return
    if failure == "heatmap":
        panel.heatmap(values, valid_mask=values.astype(bool))
        message = "explicit units"
    else:
        panel.field2d(values, valid_mask=values.astype(bool), units="degC")
        if failure == "extra_layer":
            panel.reference(axis="x", value=-95.5)
            message = "exactly one field2d layer"
        else:
            figure.panel(x=[1, 2], y=[2, 3]).scatter()
            message = "exactly one panel"
    with pytest.raises(ValueError, match=message):
        figure.save(tmp_path / "invalid.nc")


def test_time_notes_distinguish_declared_time_axes_from_numeric_axes():
    reference = figure_api_reference()
    assert "x_scale='time'" in reference
    assert "on a declared time axis" in reference
    # A numeric x axis is legal even for a time_series: the reference must not claim otherwise.
    figure = ScientificFigure(plot_kind="time_series", title="Numeric index")
    panel = figure.panel(x=[1, 2], y=[2, 3])
    assert panel.payload["axes"]["x"]["scale"] == "linear"


def test_reference_reading_rule_and_real_reader_reach_the_end_in_two_pages(tmp_path):
    reference = figure_api_reference()
    introduction = reference.split("```python", 1)[0]
    assert "to its end" in introduction and "once" not in introduction
    assert f"{len(reference.splitlines())} lines" in introduction
    assert "limit=300" in introduction and "offset" in introduction
    source = tmp_path / "result-api.md"
    source.write_text(reference, encoding="utf-8")
    pages, offset = [], 0
    for _ in range(3):
        page = text_read(source, offset, 300, tmp_path / "pages")
        pages.append(page["content"])
        if "next_offset" not in page:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert len(pages) == 2, "Reference grew beyond two pages; review the reading instruction."
    assert "".join(pages) == reference


def test_documented_panel_kwargs_are_only_forwarded_parameters_and_all_work():
    reference = figure_api_reference()
    panel_section = reference.split("### fig.panel\n", 1)[1].split("### fig.add_feature", 1)[0]
    match = re.search(r"`kwargs\((.*?)\)`", panel_section)
    assert match is not None, "Document forwarded panel keywords in the fig.panel section."
    parameters = inspect.signature(ScientificPanel.__init__).parameters
    names = set(parameters) - {"self", "figure", "panel_id", "x", "y"}
    documented = set(re.findall(r"(\w+):", match[1]))
    assert documented == names
    examples = {"title": "Station", "subtitle": "Monthly", "label": "a",
                "x_label": "Index", "y_label": "Value", "x_units": "days", "y_units": "degC",
                "x_scale": "linear", "y_scale": "linear", "x_range": [0, 4], "y_range": [0, 4],
                "x_reverse": True, "y_reverse": True, "x_grid": True, "y_grid": False,
                "display": {"legend": True}}
    assert set(examples) == names
    for name, value in examples.items():
        fig = ScientificFigure(plot_kind="scatter", title="Panel keywords")
        assert fig.panel(x=[1, 2], y=[2, 3], **{name: value}) is fig.panels[0]


def test_missing_layer_note_does_not_prevent_reference_generation(monkeypatch):
    figure_api_reference.cache_clear()
    try:
        monkeypatch.delitem(LAYER_NOTES, "vector")
        reference = figure_api_reference()
        assert "### panel.vector" in reference
        assert f"`{_signature('vector', ScientificPanel.vector)}`" in reference
    finally:
        figure_api_reference.cache_clear()


def test_reference_explains_automatic_time_axes_and_caller_split_antimeridian():
    reference = figure_api_reference()
    assert "datetime64, datetime and ISO strings automatically become time axes" in reference
    assert "caller must split" in reference
    assert "source_handle` selects" in reference
    assert "conclusions` records" in reference
    assert "spatial_context` supplies" in reference
