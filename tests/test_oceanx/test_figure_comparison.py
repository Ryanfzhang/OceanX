"""A figure named after a paper's figure is put beside its original after the run (figure_comparison.py):
left to reopen the original itself, an agent drew from a look taken some fifty calls earlier and then
looked only at its own figure (2026-10-27)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from oceanx.backend.host import OceanBackendHost
from oceanx.figure_comparison import compare_reproduced_figures
from oceanx.figure_delivery import is_delivered_figure
from oceanx.pdf_text import paper_figure, pdf_text
from oceanx.sandbox import get_sandbox_execution_capabilities
from tests.test_oceanx.test_research_library_router import _open_project


def _paper(root: Path) -> tuple[Path, Path]:
    """An extracted paper text as pdf_text.py writes it: Fig. 1 embedded, Fig. 2 drawn as vectors (only
    its page image), Figs. 3 and 4 on one page, and a citation that starts a line."""
    folder = root / "paper.figures"
    folder.mkdir(parents=True)
    for name, colour in (("page-02-figure-1.jpg", "red"), ("page-03.jpg", "white"),
                         ("page-04-figure-1.jpg", "blue"), ("page-04-figure-2.jpg", "green")):
        Image.new("RGB", (400, 300), colour).save(folder / name)
    text = root / "paper.txt"
    text.write_text(
        "=== Page 1 of 4 ===\nThe deep layer strengthens, as\nFig. 2c) and Fig. 3 show.\n\n"
        f"=== Page 2 of 4 ===\n[Figure image: {folder / 'page-02-figure-1.jpg'}]\nFig. 1. Layered circulation.\n\n"
        f"=== Page 3 of 4 ===\n[Page image: {folder / 'page-03.jpg'}]\nFigure 2: A figure drawn as vectors.\n\n"
        f"=== Page 4 of 4 ===\n[Figure image: {folder / 'page-04-figure-1.jpg'}]\n"
        f"[Figure image: {folder / 'page-04-figure-2.jpg'}]\nFig. 3. Budget.\nFig. 4. Schematic.\n",
        encoding="utf-8")
    return text, folder


def test_a_papers_figure_is_found_by_its_caption(tmp_path: Path):
    text, folder = _paper(tmp_path)
    assert paper_figure(text, 1) == folder / "page-02-figure-1.jpg"
    assert paper_figure(text, 2) == folder / "page-03.jpg"  # a vector figure: the page's image
    assert [paper_figure(text, n).name for n in (3, 4)] == ["page-04-figure-1.jpg", "page-04-figure-2.jpg"]
    assert paper_figure(text, 5) is None and paper_figure(tmp_path / "missing.txt", 1) is None


def test_a_reproduced_figure_is_put_beside_its_original_twice_at_most(tmp_path: Path):
    text, _ = _paper(tmp_path)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    figure, other = outputs / "fig1_circulation.png", outputs / "sst_map.png"
    Image.new("RGB", (800, 600), "black").save(figure)
    Image.new("RGB", (800, 600), "black").save(other)
    ledger = tmp_path / ".runtime" / "figure-comparisons.json"
    saved = [(figure.name, figure), (other.name, other)]

    (note,) = compare_reproduced_figures(outputs, saved, (text,), ledger, "req-1")
    assert "outputs/fig1_circulation.png reproduces Fig. 1 of the paper" in note
    assert "open outputs/_compare_fig1_circulation.png, the original on the left" in note
    comparison = outputs / "_compare_fig1_circulation.png"
    with Image.open(comparison) as image:
        # both at one height, the original's red on the left and the figure's black on the right
        assert image.size == (2490, 974)
        red, black = image.getpixel((40, 500)), image.getpixel((image.width - 60, 500))
        assert red[0] > 240 and max(red[1:]) < 20 and black == (0, 0, 0)  # the original is a JPEG
    assert not is_delivered_figure(comparison)  # a draft, never a result
    (second,) = compare_reproduced_figures(outputs, saved[:1], (text,), ledger, "req-1")
    assert second.endswith("This was the last comparison of this figure.")
    assert compare_reproduced_figures(outputs, saved[:1], (text,), ledger, "req-1") == ()
    assert compare_reproduced_figures(outputs, saved[:1], (text,), ledger, "req-2")  # a later request compares anew
    assert compare_reproduced_figures(outputs, saved[:1], (), ledger, "req-3") == ()  # no paper attached
    # A PDF figure is compared through the preview drawn beside it, and only once that exists.
    pdf = outputs / "fig3_budget.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    assert compare_reproduced_figures(outputs, [(pdf.name, pdf)], (text,), ledger, "req-1") == ()
    Image.new("RGB", (800, 600), "black").save(outputs / "fig3_budget.pdf.preview.png")
    (note,) = compare_reproduced_figures(outputs, [(pdf.name, pdf)], (text,), ledger, "req-1")
    assert "reproduces Fig. 3" in note and (outputs / "_compare_fig3_budget.png").is_file()


def _real_paper(folder: Path) -> Path:
    """A one-page PDF whose figure is an embedded image above the caption 'Fig. 1. ...'."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    figure = plt.figure(figsize=(6, 7))
    axes = figure.add_axes((0.1, 0.25, 0.8, 0.7))
    axes.imshow(np.random.default_rng(0).random((500, 500)), interpolation="none")
    figure.text(0.1, 0.1, "Fig. 1. Layered circulation of the test sea.")
    pdf = folder / "paper.pdf"
    figure.savefig(pdf)
    plt.close(figure)
    return pdf


@pytest.mark.asyncio
async def test_a_run_compares_a_reproduced_figure_with_the_attached_papers(tmp_path: Path, monkeypatch):
    capabilities = get_sandbox_execution_capabilities()
    if not capabilities.available:
        pytest.skip(capabilities.reason or "sandbox backend is unavailable")
    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        client, recorder, context = await _open_project(host, tmp_path, "ws_compare")
        await host.router.handle_payload(client, {
            "protocol_version": 2, "request_id": "req_task", "type": "task.create",
            "payload": {"title": "reproduction"}, "context": context})
        task_id = recorder.result("req_task")["task"]["task_id"]
        service = host.expert_code_execution
        # The paper attached to the task gives its extracted text once the context has read it.
        pdf = _real_paper(tmp_path)
        text = pdf_text(pdf, host.paths)
        assert paper_figure(text, 1) is not None
        assert service._paper_texts("ws_compare", (SimpleNamespace(paths=(pdf,)),)) == (text,)
        monkeypatch.setattr(type(service), "_paper_texts", lambda self, workspace_id, sources: (text,))
        run = {"workspace_id": "ws_compare", "task_id": task_id, "agent_thread_id": "single-agent-x",
               "server_run_id": "run", "origin_request_id": "req_reproduce"}
        code = ("import os\nimport matplotlib.pyplot as plt\nfig, ax = plt.subplots()\nax.plot([0, 1], [1, 0])\n"
                "fig.savefig(os.path.join(os.environ['OCEAN_OUTPUT_DIR'], 'fig1_circulation.pdf'))\n")
        first = await service.run_python(**run, purpose="Reproduce Fig. 1", code=code)
        assert first.state == "succeeded", first.as_payload()
        (note,) = first.figure_notes
        assert note.startswith("outputs/fig1_circulation.pdf reproduces Fig. 1 of the paper")
        assert (Path(first.work_root) / "outputs" / "_compare_fig1_circulation.png").is_file()
        second = await service.run_shell(**{k: v for k, v in run.items()},
                                         command=f"python -c \"{code.replace(chr(10), '; ')}\"")
        assert second.state == "succeeded" and second.figure_notes[-1].endswith("last comparison of this figure.")
        third = await service.run_python(**run, purpose="Again", code=code)
        assert third.figure_notes == ()
    finally:
        await host.close()
