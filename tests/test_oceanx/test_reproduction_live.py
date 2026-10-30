"""Opt-in provider regression using synthetic plots, never private task data.

OCEANX_RUN_VISUAL_EVAL=1 pytest tests/test_oceanx/test_reproduction_live.py
Uses the configured expert model. Each case is one real visual-model invocation.
"""
import json
import os
from pathlib import Path

import pytest

from oceanx.model_config import create_chat_model, load_model_profile
from oceanx.reproduction_images import preview_bytes, save_reproduction_figure
from oceanx.reproduction_review import check_figure
from oceanx.reproduction_state import FigureSpec, PanelSpec

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.environ.get("OCEANX_RUN_VISUAL_EVAL") != "1", reason="Explicit opt-in for real model calls")]


def draw(root, name):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(5, 3))
    years, values = [2000, 2001, 2002, 2003, 2004], [1, 2, 1, 3, 2]
    if name == "scatter":
        ax.scatter(values, years, label="C")
        ax.set(xlabel="C (m/s)", ylabel="Year")
    else:
        if name == "different_values":
            values = [3, 2, 4, 1, 2]
        ax.plot(years, values, label="C")
        ax.set(xlabel="Year", ylabel="C (kg)" if name == "wrong_units" else "C (m/s)")
    ax.legend()
    output = root / f"{name}.pdf"
    metadata = save_reproduction_figure(fig, output, panels={"a": [ax]}, source_code=__file__)
    plt.close(fig)
    return output, json.loads(Path(metadata).read_text())


@pytest.mark.parametrize("case,accepted", [("correct", True), ("different_values", True),
                                          ("scatter", False), ("wrong_units", False)])
async def test_real_visual_checker(tmp_path, case, accepted):
    original, _ = draw(tmp_path, "original")
    generated, metadata = draw(tmp_path, case)
    contract = FigureSpec(figure_id="sample", output_file="figure.pdf", reference_image=str(original),
        caption="Panel a: C as a function of Year.", panels=[PanelSpec(panel="a", plot_type="time series",
            x_axis="Year", y_axes=["C (m/s)"], quantities=["C"], units_scales="m/s",
            layout_overlays="one panel, line, legend C", verified_labels=["Year", "C (m/s)"])])
    model = create_chat_model(load_model_profile("expert"), request_timeout=240)
    review = await check_figure(model, contract, metadata, [
        ("Original full figure", preview_bytes(original)),
        ("Generated full figure", preview_bytes(generated))])
    (tmp_path / "verdict.json").write_text(review.model_dump_json(indent=2))
    assert review.accepts(contract) == accepted, review.model_dump_json()


async def test_real_eight_panel_checker_does_not_reject_a_correct_figure(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 4, figsize=(12, 6))
    panels = {}
    for name, ax in zip("abcdefgh", axes.flat):
        ax.plot([2000, 2001, 2002], [1, 2, 1], label="C")
        ax.set(xlabel="Year", ylabel="C (m/s)", title=name)
        ax.legend()
        panels[name] = [ax]
    fig.tight_layout()
    output = tmp_path / "figure.pdf"
    metadata_path = save_reproduction_figure(fig, output, panels=panels, source_code=__file__)
    plt.close(fig)
    metadata = json.loads(Path(metadata_path).read_text())
    contract = FigureSpec(figure_id="many-panels", output_file="figure.pdf", reference_image=str(output),
        caption="Eight panels, each showing C over years.", panels=[PanelSpec(panel=name,
            plot_type="time series", x_axis="Year", y_axes=["C (m/s)"], quantities=["C"],
            units_scales="m/s", layout_overlays="one line and legend C") for name in panels])
    pixels = preview_bytes(output)
    images = [("Original full figure", pixels), ("Generated full figure", pixels)]
    for panel in metadata["panels"]:
        raw = Path(panel["image"]).read_bytes()
        images.extend([(f"Original panel {panel['panel']}", raw), (f"Generated panel {panel['panel']}", raw)])
    model = create_chat_model(load_model_profile("expert"), request_timeout=240)
    review = await check_figure(model, contract, metadata, images)
    (tmp_path / "verdict.json").write_text(review.model_dump_json(indent=2))
    assert review.accepts(contract), review.model_dump_json()
