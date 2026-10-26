"""A figure an agent saves can be edited in Illustrator: its text is text in TrueType fonts, its colour
bar is vector, and only a dense field is an image. Typhoon Mangkhut figures of 2026-10-26 used Type 3
fonts, held some 430,000 path segments and carried their colour bars as images."""
import re
import sys
import asyncio
import threading
from pathlib import Path

import pytest

from oceanx.backend.host import OceanBackendHost
from oceanx.figure_delivery import FIGURE_DELIVERY_ENV, matplotlib_settings
from oceanx.figure_style import EDITABLE, publication_style
from oceanx.sandbox import get_sandbox_execution_capabilities
from tests.test_oceanx.test_research_library_router import _open_project

FIGURE = """
import os
import matplotlib.pyplot as plt
import numpy as np

print("RC", plt.rcParams["pdf.fonttype"], plt.rcParams["svg.fonttype"], plt.rcParams["font.sans-serif"][0])
lon, lat = np.linspace(108, 124, 321), np.linspace(12, 25, 261)
field = np.cos(np.radians(lon))[None, :] * np.sin(np.radians(lat))[:, None]
fig, ax = plt.subplots(figsize=(7, 3.5))
mesh = ax.pcolormesh(lon, lat, field, rasterized=True)   # the dense field: one image
cbar = fig.colorbar(mesh, ax=ax, label="SST change (°C)")
cbar.solids.set_rasterized(False)                         # the colour bar stays vector
ax.plot([110, 122], [20, 18], "k-")
ax.set_xlabel("Longitude (°E)")
out = os.environ["OCEAN_OUTPUT_DIR"]
fig.savefig(os.path.join(out, "cooling.pdf"), bbox_inches="tight")
fig.savefig(os.path.join(out, "cooling.svg"), bbox_inches="tight")
"""


CARELESS = """
import os
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["pdf.fonttype"] = 3
field = np.random.default_rng(0).random((300, 300))
fig, ax = plt.subplots()
fig.colorbar(ax.pcolormesh(field), ax=ax, label="x")
fig.savefig(os.path.join(os.environ["OCEAN_OUTPUT_DIR"], "careless.pdf"))
"""


def pdf_contents(path: Path) -> tuple[set[str], int]:
    """The font types of a PDF's text and how many images it holds."""
    from pypdf import PdfReader
    fonts, images = set(), 0
    for page in PdfReader(path).pages:
        resources = page["/Resources"]
        for font in (resources.get("/Font") or {}).values():
            font = font.get_object()
            fonts.add(str(font["/Subtype"]))
            for descendant in font.get("/DescendantFonts") or []:
                fonts.add(str(descendant.get_object()["/Subtype"]))
        for item in (resources.get("/XObject") or {}).values():
            images += item.get_object().get("/Subtype") == "/Image"
    return fonts, images


def test_one_style_serves_the_figures_agents_draw_and_the_drawing_of_interactive_figures(monkeypatch):
    """The settings agents' code reads and the renderer of interactive figures come from figure_style.py."""
    import matplotlib as mpl

    from oceanx.figure_reproduction import _FIXED_RENDERER_SOURCE
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, "interactive")
    lines = matplotlib_settings().splitlines()
    assert "pdf.fonttype: 42" in lines and "font.sans-serif: Arial, Helvetica, Liberation Sans, DejaVu Sans" in lines
    assert "font.size: 7" in lines and "axes.prop_cycle: cycler('color', ['147D78'" in matplotlib_settings()
    with mpl.rc_context():
        renderer = compile(_FIXED_RENDERER_SOURCE, "<oceanx-fixed-renderer>", "exec")
        exec(renderer, {})  # noqa: S102 - the bundled renderer
        drawn = {key: mpl.rcParams[key] for key in publication_style()}
    assert drawn == {**publication_style(), "font.family": ["sans-serif"]}  # matplotlib keeps families as a list
    # A benchmark run keeps matplotlib's look: only how fonts are stored changes.
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, "static")
    assert matplotlib_settings() == "pdf.fonttype: 42\nps.fonttype: 42\nsvg.fonttype: none\n" and EDITABLE


@pytest.mark.asyncio
async def test_a_saved_figure_has_editable_text_and_a_vector_colour_bar(tmp_path: Path, monkeypatch):
    capabilities = get_sandbox_execution_capabilities()
    if not capabilities.available:
        pytest.skip(capabilities.reason or "sandbox backend is unavailable")
    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, "interactive")
    from oceanx import expert_execution
    prepare = expert_execution._prepare_pdf_figures
    loop = asyncio.get_running_loop()

    def responsive_prepare(*args):
        pulse = threading.Event()
        loop.call_soon_threadsafe(pulse.set)
        assert pulse.wait(2), "PDF preparation blocked the event loop"
        return prepare(*args)

    monkeypatch.setattr(expert_execution, "_prepare_pdf_figures", responsive_prepare)
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        client, recorder, context = await _open_project(host, tmp_path, "ws_editable")
        await host.router.handle_payload(client, {
            "protocol_version": 2, "request_id": "req_task", "type": "task.create",
            "payload": {"title": "figures"}, "context": context})
        task_id = recorder.result("req_task")["task"]["task_id"]
        run = {"workspace_id": "ws_editable", "task_id": task_id, "agent_thread_id": "single-agent-x",
               "server_run_id": "run"}
        kernel = await host.expert_code_execution.run_python(**run, purpose="Draw the map", code=FIGURE)
        assert kernel.state == "succeeded", kernel.as_payload()
        assert re.search(r"RC 42 none \w", kernel.stdout), kernel.stdout
        shell = await host.expert_code_execution.run_shell(
            **run, command="python -c \"import matplotlib as m; print('RC', m.rcParams['pdf.fonttype'])\"")
        assert shell.state == "succeeded" and "RC 42" in shell.stdout, shell.as_payload()
        outputs = Path(kernel.work_root) / "outputs"
        fonts, images = pdf_contents(outputs / "cooling.pdf")
        assert fonts and "/Type3" not in fonts and fonts & {"/TrueType", "/CIDFontType2"}, fonts
        assert images == 1  # the field; the colour bar is vector
        assert "<text" in (outputs / "cooling.svg").read_text(encoding="utf-8")
        # The run gives the PDF its picture, which the agent and the desktop both look at, and finds
        # nothing to fix.
        assert (outputs / "cooling.pdf.preview.png").is_file() and kernel.figure_notes == ()
        # A figure drawn against the style is caught, and the agent is told what to change.
        careless = await host.expert_code_execution.run_python(**run, purpose="Draw it again", code=CARELESS)
        assert careless.state == "succeeded", careless.as_payload()
        notes = " ".join(careless.figure_notes)
        assert "outputs/careless.pdf: its text is stored in Type 3 fonts" in notes
        assert len(careless.figure_notes) == 1  # font evidence only; no guesses from paths or image shapes
    finally:
        await host.close()


@pytest.mark.parametrize("dense_vector", [False, True])
def test_image_shape_and_path_count_do_not_trigger_editability_advice(tmp_path, dense_vector):
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    import numpy as np
    from oceanx.figure_delivery import pdf_problems

    with mpl.rc_context({"pdf.fonttype": 42}):
        fig, ax = plt.subplots(figsize=(12, 1))
        if dense_vector:
            ax.pcolormesh(np.ones((150, 150)))
        else:
            # A long section, not a colour bar.
            ax.imshow(np.arange(1000).reshape(10, 100), aspect="auto")
        pdf = tmp_path / "section.pdf"
        fig.savefig(pdf)
        plt.close(fig)
    assert pdf_problems(pdf) == []


def test_an_interactive_figure_is_also_saved_as_an_editable_pdf_of_its_result(tmp_path: Path, monkeypatch):
    """The Workbench draws an interactive figure in the browser, which no editor can open; the same
    figure drawn by the preview renderer is saved beside it as a PDF and offered with its result."""
    import json
    from types import SimpleNamespace

    import numpy as np

    from oceanx.figure_delivery import is_delivered_figure, static_figure_files
    from oceanx.scientific_view import ScientificFigure
    from oceanx.task_results import TaskResultStore
    from tests.test_oceanx.test_explicit_figure_delivery import _Projector

    task_root = tmp_path / "task"
    work_root = task_root / "agents" / "single-agent-x"
    outputs = work_root / "outputs"
    outputs.mkdir(parents=True)
    manifest = work_root / ".runtime" / "results.jsonl"
    monkeypatch.setenv("OCEAN_OUTPUT_DIR", str(outputs))
    monkeypatch.setenv("OCEAN_RESULT_MANIFEST", str(manifest))
    lon, lat = np.linspace(108, 124, 161), np.linspace(12, 25, 131)
    field = np.cos(np.radians(lon))[None, :] * np.sin(np.radians(lat))[:, None]
    figure = ScientificFigure(plot_kind="spatial_map", title="SST response")
    figure.panel(x=lon, y=lat).field2d(field, valid_mask=np.isfinite(field), units="degC")
    saved = figure.save(outputs / "sst_response.nc")
    pdf = saved.with_suffix(".print.pdf")
    assert pdf.is_file() and saved.with_suffix(".preview.png").is_file()
    fonts, images = pdf_contents(pdf)
    assert fonts and "/Type3" not in fonts and images <= 1  # at most the field; the colour bar is vector
    (event,) = [json.loads(line) for line in manifest.read_text().splitlines()]
    assert event["pdf_output"] == "sst_response.print.pdf"
    # Derived from the figure like its preview, it is no figure of its own; the view's result offers it.
    assert not is_delivered_figure(pdf) and list(static_figure_files(task_root)) == []
    execution = SimpleNamespace(
        state="succeeded", result={"work_root": str(work_root), "discovered_results": [event]},
        request={"origin_request_id": "request"}, agent_thread_id="single-agent-x",
        execution_id="execution", ended_at="2026-10-26T00:00:00+00:00")
    store = TaskResultStore(task_workspaces=_Projector(task_root, execution))
    (view,) = store.list(task_id="task")
    assert view.kind == "interactive_view"
    assert view.content["pdf_file"] == "figure.pdf" and view.content["preview_file"] == "preview.png"
    assert ("figure.pdf", "application/pdf") in [(item.path, item.mime_type) for item in view.files]
    assert store.file_path(ref=view.ref, relative_path="figure.pdf") == pdf.resolve()


def test_the_preview_renderer_keeps_a_colour_bar_of_many_colours_vector(tmp_path: Path):
    """matplotlib stores a colour bar of 50 or more colours as an image unless told otherwise."""
    from oceanx.figure_reproduction import _FIXED_RENDERER_SOURCE
    namespace: dict = {}
    renderer = compile(_FIXED_RENDERER_SOURCE, "<oceanx-fixed-renderer>", "exec")
    exec(renderer, namespace)  # noqa: S102 - the bundled renderer
    plt, np = namespace["plt"], namespace["np"]
    figure, axes = plt.subplots()
    mesh = axes.pcolormesh(np.random.default_rng(0).random((60, 80)), rasterized=True)
    namespace["_add_colorbar"](figure, mesh, axes, "SST (°C)")
    figure.savefig(tmp_path / "bar.pdf")
    plt.close(figure)
    fonts, images = pdf_contents(tmp_path / "bar.pdf")
    assert images == 1 and "/Type3" not in fonts  # the field only
