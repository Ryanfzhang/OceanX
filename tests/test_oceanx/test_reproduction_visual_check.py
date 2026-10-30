"""Image-backed comparison advice without a display gate."""
import json
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from oceanx.reproduction import reproduction_tools
from oceanx.reproduction_images import render_pdf_regions, save_reproduction_figure
from oceanx.reproduction_review import check_figure, metadata_findings
from oceanx.reproduction_state import (
    MethodAdjustment, ReferenceSource, FigureRegion, ReproductionStore,
    ReviewFinding, FigureAdvice, VisualPanelCheck,
)
from tests.test_oceanx.test_reproduction_continuity import spec, DownloadBackend


def visual_result(category=None):
    return FigureAdvice(panels=[VisualPanelCheck(panel="b", original_labels=["Year", "C"],
        generated_labels=["Year", "C"], readable=True, observation="Both show C over years")],
        findings=[] if category is None else [ReviewFinding(category=category, kind={"structure": "missing_series", "scientific_difference": "value_or_trend", "uncertain": "unreadable"}[category], panel="b",
            detail="Different result", evidence="Original and generated panel b", suggestion="Check the missing content or calculation against the source.")])


class VisualModel:
    profile = {"image_inputs": True}

    def __init__(self, result):
        self.result = result
        self.calls = []

    def with_structured_output(self, schema, **kwargs):
        assert schema is FigureAdvice
        return self

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self.result.model_copy(deep=True)


def draw(tmp_path, *, scatter=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    script = tmp_path / "plot.py"
    script.write_text("# The fixture plotting script\n")
    data = tmp_path / "data.csv"
    data.write_text("year,C\n2000,1\n2001,2\n")
    fig, ax = plt.subplots()
    (ax.scatter if scatter else ax.plot)([2000, 2001, 2002], [1, 2, 1], label="C")
    ax.set_xlabel("Year")
    ax.set_ylabel("C (m/s)")
    ax.legend()
    output = tmp_path / "outputs" / "figure.pdf"
    metadata = save_reproduction_figure(fig, output, panels={"b": [ax]},
        source_code=script, data_files=[data])
    plt.close(fig)
    return output, Path(metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize("category", [None, "scientific_difference", "structure", "uncertain"])
async def test_comparison_provides_advice_for_all_categories(tmp_path, category):
    output, metadata = draw(tmp_path)
    original = tmp_path / "original.png"
    from oceanx.reproduction_images import preview_bytes
    original.write_bytes(preview_bytes(output))
    model = VisualModel(visual_result(category))
    tools = {t.name: t for t in reproduction_tools(work_root=tmp_path, backend=DownloadBackend(), model=model)}
    contract = spec(str(original)).model_copy(update={"output_file": "figure.pdf"})
    await tools["record_reproduction_spec"].ainvoke({"spec": contract.model_dump()})
    response = await tools["review_reproduction_figure"].ainvoke({
        "figure_id": "figure-3", "output_file": "figure.pdf", "metadata_file": str(metadata)})
    assert "Comparison suggestions recorded" in response
    store = ReproductionStore(tmp_path)
    assert "accepted" not in store.attempts("figure-3")[-1]
    assert not hasattr(model.result, "accepts")
    assert len(model.calls) == 1
    messages = model.calls[0]
    assert [m.type for m in messages] == ["system", "human"]
    blocks = messages[1].content
    assert any(b.get("type") == "image_url" and b["image_url"]["detail"] == "original" for b in blocks)
    assert "Comparison findings (checker output only)" in (store.root / "repro_spec.md").read_text()
    assert "![Original]" in (store.root / "repro_spec.md").read_text()
    repeated = await tools["review_reproduction_figure"].ainvoke({
        "figure_id": "figure-3", "output_file": "figure.pdf", "metadata_file": str(metadata)})
    assert "Existing comparison suggestions" in repeated
    assert len(model.calls) == 1
    output.write_bytes(b"changed")
    stale = await tools["review_reproduction_figure"].ainvoke({
        "figure_id": "figure-3", "output_file": "figure.pdf", "metadata_file": str(metadata)})
    assert "Comparison unavailable" in stale and "remains available" in stale


@pytest.mark.asyncio
async def test_wrong_chart_gets_specific_suggestion_without_repeated_reviews(tmp_path):
    output, metadata = draw(tmp_path, scatter=True)
    from oceanx.reproduction_images import preview_bytes
    original = tmp_path / "source.png"
    original.write_bytes(preview_bytes(output))
    model = VisualModel(visual_result())  # intentionally misses the plot-type difference
    tools = {t.name: t for t in reproduction_tools(work_root=tmp_path, backend=DownloadBackend(), model=model)}
    await tools["record_reproduction_spec"].ainvoke({"spec": spec(str(original)).model_copy(
        update={"output_file": "figure.pdf"}).model_dump()})
    for _ in range(4):
        response = await tools["review_reproduction_figure"].ainvoke({"figure_id": "figure-3",
            "output_file": "figure.pdf", "metadata_file": str(metadata)})
    assert "Existing comparison suggestions" in response
    assert len(model.calls) == 1
    assert "Use the requested time axis" in response
    assert "Scatter artists" in ReproductionStore(tmp_path).context()


@pytest.mark.asyncio
async def test_stale_metadata_and_source_do_not_trigger_checker(tmp_path):
    output, metadata = draw(tmp_path)
    from oceanx.reproduction_images import preview_bytes
    source = tmp_path / "source.png"
    source.write_bytes(preview_bytes(output))
    model = VisualModel(visual_result())
    tools = {t.name: t for t in reproduction_tools(work_root=tmp_path, backend=DownloadBackend(), model=model)}
    await tools["record_reproduction_spec"].ainvoke({"spec": spec(str(source)).model_copy(
        update={"output_file": "figure.pdf"}).model_dump()})
    (tmp_path / "plot.py").write_text("changed code")
    response = await tools["review_reproduction_figure"].ainvoke({"figure_id": "figure-3",
        "output_file": "figure.pdf", "metadata_file": str(metadata)})
    assert "source changed" in response
    assert model.calls == []


@pytest.mark.asyncio
async def test_parameter_adjustment_and_user_authorized_quantity_change(tmp_path):
    output, _ = draw(tmp_path)
    from oceanx.reproduction_images import preview_bytes
    source = tmp_path / "source.png"
    source.write_bytes(preview_bytes(output))
    store = ReproductionStore(tmp_path)
    tools = {t.name: t for t in reproduction_tools(work_root=tmp_path, backend=DownloadBackend())}
    contract = spec(str(source)).model_copy(update={"adjustments": [MethodAdjustment(kind="parameter",
        description="Different smoothing window", reason="Record length and retained samples")]})
    assert "preserved" in await tools["record_reproduction_spec"].ainvoke({"spec": contract.model_dump()})
    contract.adjustments = [MethodAdjustment(kind="quantity", description="Mean instead of trend",
        reason="Only means computed", user_authorization="Use mean instead of trend", authorization_message_id="u1")]
    assert "matching user message" in await tools["record_reproduction_spec"].ainvoke({"spec": contract.model_dump(), "correction_reason": "change"})
    store.remember_users([HumanMessage(id="u1", content="Use mean instead of trend")])
    assert "preserved" in await tools["record_reproduction_spec"].ainvoke({"spec": contract.model_dump(), "correction_reason": "User changed goal"})
    assert store.user_messages()["u1"] == "Use mean instead of trend"


def test_pdf_region_pixels_and_literal_labels(tmp_path):
    output, _ = draw(tmp_path)
    result = render_pdf_regions(output.read_bytes(), 1,
        {"figure": (0, 0, 1, 1), "panel": (0, 0, 1, 1)}, tmp_path / "source")
    assert "Year" in result["regions"]["panel"]["text"]
    assert "C (m/s)" in result["regions"]["panel"]["text"]
    assert Path(result["overlay_image"]).is_file()
    with pytest.raises(ValueError, match="normalized"):
        render_pdf_regions(output.read_bytes(), 1, {"bad": (0, 0, 2, 1)}, tmp_path / "bad")


@pytest.mark.asyncio
async def test_record_source_renders_panels_and_retains_text_after_compaction(tmp_path):
    output, _ = draw(tmp_path)
    contract = spec().model_copy(update={"source": ReferenceSource(pdf=str(output), page=1,
        figure_box=(0, 0, 1, 1), panels=[FigureRegion(panel="b", box=(0, 0, 1, 1))])})
    tools = {t.name: t for t in reproduction_tools(work_root=tmp_path, backend=DownloadBackend())}
    response = await tools["record_reproduction_spec"].ainvoke({"spec": contract.model_dump()})
    assert "preserved" in response
    store = ReproductionStore(tmp_path)
    source = json.loads((store.directory("figure-3") / "source.json").read_text())
    assert "Year" in source["regions"]["panel-0"]["text"]
    assert str(store.root / "repro_spec.md") in ReproductionStore(tmp_path).context()
    assert "time (years)" in ReproductionStore(tmp_path).context()


@pytest.mark.asyncio
async def test_unreadable_label_cannot_be_claimed_as_verified(tmp_path):
    model = VisualModel(visual_result())
    contract = spec()
    contract.panels[0].verified_labels = ["Unreadable axis label"]
    metadata = {"panels": [{"panel": "b", "artist_types": ["line"]}]}
    result = await check_figure(model, contract, metadata, [])
    assert result.findings
    assert any("transcription" in f.detail for f in result.findings)


def test_missing_panels_detected_in_export():
    findings = metadata_findings(spec(), {"panels": []})
    assert findings[0].category == "structure"


def test_panel_previews_are_not_deliverables(tmp_path):
    from oceanx.figure_delivery import is_delivered_figure
    output, metadata = draw(tmp_path)
    assert is_delivered_figure(output)
    for panel in json.loads(metadata.read_text())["panels"]:
        assert not is_delivered_figure(Path(panel["image"]))


@pytest.mark.asyncio
async def test_many_panels_are_checked_in_bounded_groups():
    contract = spec()
    contract.panels = [contract.panels[0].model_copy(update={"panel": str(i)}) for i in range(8)]
    metadata = {"panels": [{"panel": str(i), "artist_types": ["line"]} for i in range(8)]}
    class GroupModel(VisualModel):
        async def ainvoke(self, messages):
            self.calls.append(messages)
            context = json.loads(messages[1].content[0]["text"])
            image_count = sum(b["type"] == "image_url" for b in messages[1].content)
            assert image_count < 15
            return FigureAdvice(panels=[VisualPanelCheck(panel=p["panel"],
                original_labels=[], generated_labels=[], readable=True, observation="matched")
                for p in context["specification"]["panels"]], findings=[])
    model = GroupModel(visual_result())
    images = [(label, b"pixels") for label in ("Original full figure", "Generated full figure",
                                               "Original page with region boxes", "Overview")]
    images += [(f"{side} panel {i}", b"pixels") for i in range(8) for side in ("Original", "Generated")]
    review = await check_figure(model, contract, metadata, images)
    assert sorted(p.panel for p in review.panels) == sorted(p.panel for p in contract.panels)
    assert not review.findings
    assert len(model.calls) == 2


def test_export_helper_is_available_in_the_actual_execution_support(tmp_path):
    import os
    import subprocess
    import sys
    from oceanx.expert_execution import _install_result_runtime
    support = tmp_path / "support"
    _install_result_runtime(support)
    result = subprocess.run([sys.executable, "-c",
        "from oceanx.reproduction_images import save_reproduction_figure; print(save_reproduction_figure.__module__)"],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(support)}, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "oceanx.reproduction_images"


@pytest.mark.asyncio
async def test_parser_failure_reports_unavailable_advice_not_rejection(tmp_path):
    class BrokenModel(VisualModel):
        async def ainvoke(self, messages):
            raise ValueError("invalid structured result")
    output, metadata = draw(tmp_path)
    from oceanx.reproduction_images import preview_bytes
    source = tmp_path / "source.png"
    source.write_bytes(preview_bytes(output))
    tools = {t.name: t for t in reproduction_tools(work_root=tmp_path,
        backend=DownloadBackend(), model=BrokenModel(visual_result()))}
    await tools["record_reproduction_spec"].ainvoke({"spec": spec(str(source)).model_copy(
        update={"output_file": "figure.pdf"}).model_dump()})
    response = await tools["review_reproduction_figure"].ainvoke({"figure_id": "figure-3",
        "output_file": "figure.pdf", "metadata_file": str(metadata)})
    assert "Comparison unavailable" in response and "remains available" in response
    assert output.is_file()
    assert "accepted" not in ReproductionStore(tmp_path).attempts("figure-3")[-1]


@pytest.mark.asyncio
async def test_parameter_adjustments_cannot_be_classified_as_structural_failures():
    result = visual_result()
    result.findings.append(ReviewFinding(category="structure", kind="parameter_adjustment", panel="b",
        detail="The period differs", evidence="The supplied record covers a different period", suggestion="Explain the period adjustment."))
    model = VisualModel(result)
    contract = spec()
    reviewed = await check_figure(model, contract, {"panels": [{"panel": "b", "artist_types": ["line"]}]}, [])
    assert reviewed.findings[0].category == "scientific_difference"


def test_pdf_crop_coordinates_keep_the_requested_panel(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(4, 6))
    axes[0].set_title("UPPER_PANEL")
    axes[1].set_title("LOWER_PANEL")
    for ax in axes:
        ax.plot([0, 1], [0, 1])
    source = tmp_path / "two-panels.pdf"
    fig.savefig(source)
    plt.close(fig)
    record = render_pdf_regions(source.read_bytes(), 1,
        {"upper": (0, 0, 1, 0.49), "lower": (0, 0.51, 1, 1)}, tmp_path / "crops")
    assert "UPPER_PANEL" in record["regions"]["upper"]["text"]
    assert "LOWER_PANEL" not in record["regions"]["upper"]["text"]
    assert "LOWER_PANEL" in record["regions"]["lower"]["text"]
    assert "UPPER_PANEL" not in record["regions"]["lower"]["text"]
