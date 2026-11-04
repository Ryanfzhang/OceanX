"""A PDF attached to a Task reaches the agents as extracted text (ADR 0023)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from oceanx.backend.events import BackendClient
from oceanx.backend.host import OceanBackendHost
from oceanx.context import ModelDataDisclosurePolicy, OceanContextBuilder
from oceanx.local_sources import resolve_local_source
from oceanx.model_config import OceanChatDeepSeek
from oceanx.pdf_text import (
    MAX_FOLDER_PDFS,
    MAX_IMAGE_BYTES,
    TEXT_NOTE,
    PdfTextError,
    document_text_allowed,
    pdf_figures,
    pdf_text,
    readable_texts,
    source_text_context,
    task_pdf_texts,
)
from oceanx.storage import OceanPaths

WORKSPACE = "ws_pdf_source"


def _write_pdf(path: Path, pages: list[str], *, raw: bool = False) -> Path:
    """A minimal PDF with one line of Helvetica per page, or each page's own content stream when `raw`;
    an empty string gives a blank page."""

    font = 3 + 2 * len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>",
    ]
    for i, text in enumerate(pages):
        content = text if raw or not text else f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                       f"/Resources << /Font << /F1 {font} 0 R >> >> >>")
        objects.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    body, offsets = b"%PDF-1.4\n", []
    for number, item in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n{item}\nendobj\n".encode("latin-1")
    table = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    body += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{table}\n%%EOF\n".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def _paths(tmp_path: Path) -> OceanPaths:
    return OceanPaths.for_state_root(tmp_path / "state").ensure()


def _parts(folder: Path, page: int, columns: tuple[str, ...] = ("left-", "right-")) -> str:
    """The enlarged parts of a page as its text block names them; a page whose text keeps off the middle
    of the page counts as two columns."""

    return ", ".join(str(folder / f"page-{page:02d}-{column}{row}.jpg")
                     for column in columns for row in ("top", "middle", "bottom"))


def test_text_is_extracted_page_by_page_once_and_follows_the_file(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    pdf = _write_pdf(tmp_path / "paper.pdf", ["Upper layer cyclonic", "Middle layer anticyclonic"])

    text = pdf_text(pdf, paths)

    assert text.parent == paths.cache / "pdf-text"
    content = text.read_text(encoding="utf-8")
    images = text.with_suffix(".figures")
    assert (f"=== Page 1 of 2 ===\n[Page image: {images / 'page-01.jpg'}]\n"
            f"[Enlarged parts: {_parts(images, 1)}]\nUpper layer cyclonic") in content
    assert (f"=== Page 2 of 2 ===\n[Page image: {images / 'page-02.jpg'}]\n"
            f"[Enlarged parts: {_parts(images, 2)}]\nMiddle layer anticyclonic") in content
    if os.name == "posix":
        assert stat.S_IMODE(text.stat().st_mode) == 0o600
    import pypdf

    monkeypatch.setattr(pypdf, "PdfReader", lambda *_args: pytest.fail("extracted twice"))
    assert pdf_text(pdf, paths) == text
    monkeypatch.undo()
    _write_pdf(pdf, ["Deep layer cyclonic"])
    changed = pdf_text(pdf, paths)
    assert changed != text and "Deep layer cyclonic" in changed.read_text(encoding="utf-8")


def test_a_pdf_without_text_or_readable_structure_says_so(tmp_path):
    paths = _paths(tmp_path)
    with pytest.raises(PdfTextError, match="no text layer"):
        pdf_text(_write_pdf(tmp_path / "scan.pdf", [""]), paths)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 not really")
    with pytest.raises(PdfTextError, match="could not be read"):
        pdf_text(broken, paths)
    assert source_text_context(broken, paths, allowed=True)["pdf_texts"][0]["pdf"] == "broken.pdf"
    assert "text_error" in source_text_context(broken, paths, allowed=True)["pdf_texts"][0]


def test_a_folder_offers_its_first_pdfs_and_other_sources_nothing(tmp_path):
    paths = _paths(tmp_path)
    folder = tmp_path / "papers"
    for number in range(MAX_FOLDER_PDFS + 2):
        _write_pdf(folder / f"paper{number:02d}.pdf", [f"Finding {number}"])
    (folder / "data.nc").write_bytes(b"CDF\x01")
    _write_pdf(folder / "nested" / "hidden.pdf", ["Not offered"])

    context = source_text_context(folder, paths, allowed=True)

    assert [item["pdf"] for item in context["pdf_texts"]] == [
        f"paper{number:02d}.pdf" for number in range(MAX_FOLDER_PDFS)]
    assert context["pdf_texts_omitted"] == 2
    assert context["text_note"] == TEXT_NOTE
    texts = [Path(item["text_path"]) for item in context["pdf_texts"]]
    assert sorted(readable_texts(folder, paths)) == sorted(  # each text and its page images
        [*texts, *(text.with_suffix(".figures") for text in texts)])
    assert source_text_context(folder / "data.nc", paths, allowed=True) == {}
    assert source_text_context(folder, paths, allowed=False) == {
        "document_text": "withheld by the workspace disclosure policy"}


class _Recorder:
    def __init__(self) -> None:
        self.events = []

    async def send(self, event) -> None:
        self.events.append(event)


async def _send(host: OceanBackendHost, client: BackendClient, request_type: str, payload: dict,
                **extra) -> None:
    await host.router.handle_payload(client, {
        "protocol_version": 2, "request_id": "req_" + request_type.replace(".", "_"),
        "type": request_type, "payload": payload, **extra})


@pytest.mark.asyncio
async def test_an_imported_pdf_source_is_listed_with_its_text_unless_the_policy_withholds_it(tmp_path):
    workspace = tmp_path / "workspace"
    _write_pdf(workspace / "papers" / "zheng2026.pdf",
               ["Three-layer circulation regime transition", "Deep layer strengthens after 2009"])
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        recorder = _Recorder()
        client = BackendClient(transport="stdio", expected_client_kind="desktop", sender=recorder.send)
        await host.event_bus.register(client)
        await _send(host, client, "system.handshake", {
            "client_kind": "desktop", "client_version": "test", "supported_protocol_versions": [2]})
        context = {"client_id": str(client.client_id), "session_id": str(client.session_id),
                   "workspace_id": WORKSPACE}
        await _send(host, client, "workspace.open", {"path": str(workspace)}, context=context,
                    expected_workspace_revision=0)
        task = host.store.create_research_task(workspace_id=WORKSPACE, title="Reproduce a paper")
        await _send(host, client, "source.import",
                    {"relative_path": "papers/zheng2026.pdf", "title": "Zheng et al. 2026"},
                    context={**context, "task_id": task.task_id}, expected_workspace_revision=1)
        created = [event for event in recorder.events if event.type == "artifact.created"]
        assert created, recorder.events
        source = resolve_local_source(store=host.store, workspace_id=WORKSPACE,
                                      ref=created[-1].payload.artifact.ref).path
        builder = OceanContextBuilder(store=host.store, paths=host.paths)

        entry = builder.build(workspace_id=WORKSPACE, provider_id="deepseek",
                              task_id=task.task_id).payload["task_sources"][0]

        assert entry["path"] == str(source) and entry["format"] == "pdf"
        assert entry["text_note"] == TEXT_NOTE
        text = Path(entry["pdf_texts"][0]["text_path"])
        assert entry["pdf_texts"][0]["pdf"] == "zheng2026.pdf"
        assert "Deep layer strengthens after 2009" in text.read_text(encoding="utf-8")
        assert document_text_allowed(host.store, WORKSPACE)
        assert readable_texts(source, host.paths) == [text, text.with_suffix(".figures")]
        # The single agent is given the paper skill with these paths, whatever room the context has left.
        papers = task_pdf_texts(host.store, host.paths, workspace_id=WORKSPACE, task_id=task.task_id)
        assert papers == [str(text)]

        builder.set_policy(workspace_id=WORKSPACE, policy=ModelDataDisclosurePolicy(
            provider_id="deepseek", policy_version=2, document_text="deny"))
        withheld = builder.build(workspace_id=WORKSPACE, provider_id="deepseek",
                                 task_id=task.task_id).payload["task_sources"][0]
        assert withheld["document_text"] == "withheld by the workspace disclosure policy"
        assert "pdf_texts" not in withheld
        assert not document_text_allowed(host.store, WORKSPACE)
        assert task_pdf_texts(host.store, host.paths, workspace_id=WORKSPACE, task_id=task.task_id) == []
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_the_single_agent_keeps_the_paper_skill_from_the_call_after_it_opened_it(
        tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.messages import AIMessage, HumanMessage

    from oceanx.research import graphs
    from oceanx.research.routing import PAPER_SKILL, SINGLE_AGENT
    from tests.test_oceanx.test_deep_agent_runtime import _BoundFakeModel

    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    workspace = tmp_path / "workspace"
    _write_pdf(workspace / "papers" / "zheng2026.pdf", ["Three-layer circulation regime shift"])
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        recorder = _Recorder()
        client = BackendClient(transport="stdio", expected_client_kind="desktop",
                               sender=recorder.send)
        await host.event_bus.register(client)
        await _send(host, client, "system.handshake", {
            "client_kind": "desktop", "client_version": "test", "supported_protocol_versions": [2]})
        context = {"client_id": str(client.client_id), "session_id": str(client.session_id),
                   "workspace_id": WORKSPACE}
        await _send(host, client, "workspace.open", {"path": str(workspace)}, context=context,
                    expected_workspace_revision=0)
        task = host.store.create_research_task(workspace_id=WORKSPACE, title="Apply a paper")
        await _send(host, client, "source.import",
                    {"relative_path": "papers/zheng2026.pdf", "title": "Zheng et al. 2026"},
                    context={**context, "task_id": task.task_id}, expected_workspace_revision=1)
        [text] = task_pdf_texts(host.store, host.paths, workspace_id=WORKSPACE,
                                task_id=task.task_id)
        config = {"configurable": {"workspace_id": WORKSPACE, "workspace_path": str(workspace),
                                   "task_id": task.task_id, "thread_id": "paper",
                                   "request_id": "req_paper"}}
        monkeypatch.setattr(graphs, "host", lambda: host)
        monkeypatch.setattr(graphs, "load_model_profile",
                            lambda _: SimpleNamespace(provider="openai"))
        monkeypatch.setattr("oceanx.research.metering.CallMeter",
                            lambda *args, **kwargs: BaseCallbackHandler())
        read = {"name": "read_file", "args": {"file_path": PAPER_SKILL}, "id": "skill"}
        model = _BoundFakeModel(responses=[AIMessage(content="", tool_calls=[read]),
                                           AIMessage(content="Done.")])
        monkeypatch.setattr("oceanx.deep_runtime.create_chat_model", lambda _: model)

        graph = await graphs.build(config, SINGLE_AGENT)
        # The repro_spec.md the agent keeps in its working directory comes with the skill.
        scratch = host.task_workspace_projector.ensure_task_root(task.task_id) / "agents" / "coordinator" / "scratch"
        assert scratch.is_dir()
        (scratch / "repro_spec.md").write_text("Fig. 4 (f)-(h): trend maps are computable\n", encoding="utf-8")
        await graph.ainvoke({"messages": [HumanMessage(content="Apply its method to my data")]})

        first, second = (messages[0].text for messages in model.seen_messages)
        assert "# Attached paper" in first and text in first and "# Paper skill" not in first
        assert "# Paper skill" in second
        assert "Before computing anything, write repro_spec.md" in second
        assert "trend maps are computable" in second and "trend maps are computable" not in first
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_the_single_agent_sees_the_original_when_it_opens_its_own_figure(tmp_path, monkeypatch):
    # A run of 2026-11-04 opened the original once, at its start, and later judged its own previews
    # against a repro_spec.md that had dropped the original's fills.
    import base64
    import sys
    from io import BytesIO
    from types import SimpleNamespace

    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from PIL import Image

    from oceanx.research import graphs
    from oceanx.research.routing import ORIGINAL_NOTE, PAPER_SKILL, REPRO_SPEC, SINGLE_AGENT
    from tests.test_oceanx.test_deep_agent_runtime import _BoundFakeModel

    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    workspace = tmp_path / "workspace"
    (workspace / "papers").mkdir(parents=True)
    _write_pdf_with_images(workspace / "papers" / "zheng2026.pdf", "Fig. 1. Layer circulation", [(600, 400)])
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        recorder = _Recorder()
        client = BackendClient(transport="stdio", expected_client_kind="desktop", sender=recorder.send)
        await host.event_bus.register(client)
        await _send(host, client, "system.handshake", {
            "client_kind": "desktop", "client_version": "test", "supported_protocol_versions": [2]})
        context = {"client_id": str(client.client_id), "session_id": str(client.session_id),
                   "workspace_id": WORKSPACE}
        await _send(host, client, "workspace.open", {"path": str(workspace)}, context=context,
                    expected_workspace_revision=0)
        task = host.store.create_research_task(workspace_id=WORKSPACE, title="Apply a paper")
        await _send(host, client, "source.import",
                    {"relative_path": "papers/zheng2026.pdf", "title": "Zheng et al. 2026"},
                    context={**context, "task_id": task.task_id}, expected_workspace_revision=1)
        [text] = task_pdf_texts(host.store, host.paths, workspace_id=WORKSPACE, task_id=task.task_id)
        [original] = pdf_figures(Path(text))
        assert original.name == "page-01-figure-1.jpg"
        config = {"configurable": {"workspace_id": WORKSPACE, "workspace_path": str(workspace),
                                   "task_id": task.task_id, "thread_id": "paper",
                                   "request_id": "req_paper"}}
        monkeypatch.setattr(graphs, "host", lambda: host)
        monkeypatch.setattr(graphs, "load_model_profile", lambda _: SimpleNamespace(provider="openai"))
        monkeypatch.setattr("oceanx.research.metering.CallMeter",
                            lambda *args, **kwargs: BaseCallbackHandler())
        scratch = host.task_workspace_projector.ensure_task_root(task.task_id) / "agents" / "coordinator" / "scratch"
        mine = scratch / "fig1-layers.pdf.preview.png"
        skill = {"name": "read_file", "args": {"file_path": PAPER_SKILL}, "id": "skill"}
        look = {"name": "read_file", "args": {"file_path": str(mine)}, "id": "look"}
        model = _BoundFakeModel(responses=[AIMessage(content="", tool_calls=[skill]),
                                           AIMessage(content="", tool_calls=[look]), AIMessage(content="Done.")])
        monkeypatch.setattr("oceanx.deep_runtime.create_chat_model", lambda _: model)

        graph = await graphs.build(config, SINGLE_AGENT)
        (scratch / REPRO_SPEC).write_text("### Fig. 1 — page-01-figure-1.jpg — layer circulation\n",
                                          encoding="utf-8")
        buffer = BytesIO()
        Image.new("RGB", (40, 30), (200, 40, 40)).save(buffer, format="PNG")
        mine.write_bytes(buffer.getvalue())
        await graph.ainvoke({"messages": [HumanMessage(content="Apply its method to my data")]})

        [seen] = [message for message in model.seen_messages[2]
                  if isinstance(message, ToolMessage) and message.tool_call_id == "look"]
        assert [block["type"] for block in seen.content] == ["image", "text", "image"]
        assert seen.content[1]["text"] == ORIGINAL_NOTE.format(original="Fig. 1 (page-01-figure-1.jpg)",
                                                               spec=REPRO_SPEC)
        assert base64.b64decode(seen.content[2]["base64"]) == original.read_bytes()
    finally:
        await host.close()


def test_deepseek_models_are_sent_no_pdf_attachments():
    flash = OceanChatDeepSeek(model="deepseek-flash", api_key="test")
    assert flash.profile == {"pdf_inputs": False, "image_inputs": True}
    listed = OceanChatDeepSeek(model="deepseek-v4-flash", api_key="test")
    assert listed.profile["pdf_inputs"] is False and listed.profile["image_inputs"] is True
    assert listed.profile["max_input_tokens"] == 1_000_000  # the rest of the profile is kept


def _write_pdf_with_images(path: Path, caption: str, images: list[tuple[int, int]]) -> Path:
    """One page of text that also draws JPEG images of the given (width, height)."""

    from io import BytesIO

    from PIL import Image

    jpegs = []
    for width, height in images:
        buffer = BytesIO()
        Image.new("RGB", (width, height), (20, 90, 160)).save(buffer, format="JPEG")
        jpegs.append(buffer.getvalue())
    names = " ".join(f"/Im{i} {6 + i} 0 R" for i in range(len(images)))
    draws = " ".join(f"q 200 0 0 100 72 {600 - 120 * i} cm /Im{i} Do Q" for i in range(len(images)))
    content = f"BT /F1 12 Tf 72 720 Td ({caption}) Tj ET {draws}".encode("latin-1")
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
         f"/Resources << /Font << /F1 5 0 R >> /XObject << {names} >> >> >>").encode(),
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for (width, height), jpeg in zip(images, jpegs):
        objects.append(
            (f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace /DeviceRGB "
             f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n").encode()
            + jpeg + b"\nendstream")
    body, offsets = b"%PDF-1.4\n", []
    for number, item in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + item + b"\nendobj\n"
    table = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    body += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{table}\n%%EOF\n".encode()
    path.write_bytes(body)
    return path


def test_embedded_figures_are_saved_beside_the_text_and_named_under_their_page(tmp_path):
    paths = _paths(tmp_path)
    pdf = _write_pdf_with_images(tmp_path / "paper.pdf", "Fig. 2 Layer vorticity", [(2400, 1200), (120, 80)])

    text = pdf_text(pdf, paths)

    (figure,) = pdf_figures(text)  # the small logo-sized image is not a figure
    assert figure.name == "page-01-figure-1.jpg" and figure.parent.name == text.name.replace(".txt", ".figures")
    page = figure.parent / "page-01.jpg"
    assert (f"=== Page 1 of 1 ===\n[Page image: {page}]\n[Enlarged parts: {_parts(figure.parent, 1)}]\n"
            f"[Figure image: {figure}]\nFig. 2 Layer vorticity") in text.read_text(encoding="utf-8")
    from PIL import Image

    with Image.open(figure) as saved:
        assert saved.size == (1600, 800)  # long edge bounded, aspect kept
    if os.name == "posix":
        assert stat.S_IMODE(figure.stat().st_mode) == 0o600
    assert readable_texts(pdf, paths) == [text, figure.parent]
    assert source_text_context(pdf, paths, allowed=True)["pdf_texts"][0]["figure_images"] == [str(figure)]


def test_each_page_is_rendered_for_a_model_that_reads_images(tmp_path, monkeypatch):
    """Equations, symbols and tables survive only in a page image, as Claude reads a PDF page by page."""

    import sys

    from PIL import Image

    import oceanx.pdf_text as pdf_module

    paths = _paths(tmp_path)
    pdf = _write_pdf(tmp_path / "paper.pdf", ["Eq. (1)", "Eq. (2)"])
    text = pdf_text(pdf, paths)
    pages = sorted(text.with_suffix(".figures").glob("page-??.jpg"))
    assert [page.name for page in pages] == ["page-01.jpg", "page-02.jpg"]
    with Image.open(pages[0]) as image:
        assert max(image.size) == 1600  # long edge bounded like a figure's
    if os.name == "posix":
        assert stat.S_IMODE(pages[0].stat().st_mode) == 0o600
    assert pdf_figures(text) == []  # a page image is not an embedded figure
    assert readable_texts(pdf, paths) == [text, pages[0].parent]
    # Only the first pages are rendered.
    monkeypatch.setattr(pdf_module, "MAX_PAGE_IMAGES", 1)
    first, second = pdf_text(_write_pdf(tmp_path / "long.pdf", ["One", "Two"]), paths).read_text(
        encoding="utf-8").split("=== Page 2")
    assert "[Page image:" in first and "[Page image:" not in second
    # Without the renderer the text stands alone.
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    plain = pdf_text(_write_pdf(tmp_path / "plain.pdf", ["Text only"]), paths)
    assert "[Page image:" not in plain.read_text(encoding="utf-8")
    assert not plain.with_suffix(".figures").exists()


def test_each_page_is_also_saved_enlarged_in_parts_that_hold_an_equation_whole(tmp_path, monkeypatch):
    """On the page image of Zheng et al. (2026), page 3, deepseek-flash read f × V as f V three times in
    three; at twice the scale it kept the cross three times in three (2026-11-01)."""

    from PIL import Image

    import oceanx.pdf_text as pdf_module

    paths = _paths(tmp_path)
    lines = range(40)
    two_columns = " ".join(f"BT /F1 10 Tf {x} {700 - 14 * i} Td ({side} column line {i}) Tj ET"
                           for x, side in ((72, "Left"), (330, "Right")) for i in lines)
    across = "One column running across the page " * 2
    one_column = " ".join(f"BT /F1 10 Tf 72 {700 - 14 * i} Td ({across}) Tj ET" for i in lines)
    text = pdf_text(_write_pdf(tmp_path / "paper.pdf", [two_columns, one_column], raw=True), paths)

    folder = text.with_suffix(".figures")
    content = text.read_text(encoding="utf-8")
    assert f"[Page image: {folder / 'page-01.jpg'}]\n[Enlarged parts: {_parts(folder, 1)}]\n" in content
    assert f"[Page image: {folder / 'page-02.jpg'}]\n[Enlarged parts: {_parts(folder, 2, ('',))}]\n" in content
    with Image.open(folder / "page-01.jpg") as page:
        width, height = page.size
    with Image.open(folder / "page-01-left-middle.jpg") as part:
        # at twice the scale, half a page is as tall as the whole page image
        assert part.height == height and part.width == pytest.approx(0.52 * 2 * width, abs=2)
    with Image.open(folder / "page-02-bottom.jpg") as part:
        assert part.size == (pytest.approx(2 * width, abs=2), height)
    if os.name == "posix":
        assert stat.S_IMODE((folder / "page-02-bottom.jpg").stat().st_mode) == 0o600
    assert pdf_figures(text) == []  # nor are the parts embedded figures
    # Only the first pages are enlarged.
    monkeypatch.setattr(pdf_module, "MAX_ENLARGED_PAGES", 1)
    later = pdf_text(_write_pdf(tmp_path / "long.pdf", ["One", "Two"]), paths).read_text(encoding="utf-8")
    assert later.count("[Enlarged parts:") == 1 and "[Page image:" in later.split("=== Page 2")[1]


def test_page_and_figure_images_stay_small_enough_for_read_file(tmp_path):
    """read_file opens an image only up to 500 KiB. The equation page of Zheng et al. (2026) was 589 KiB as a
    JPEG of quality 85, and an agent opened it only after two failures and shrinking it itself."""

    import numpy as np
    from PIL import Image

    from oceanx.pdf_text import _save_jpeg

    dense = Image.fromarray(np.random.default_rng(0).integers(0, 255, (1200, 1600, 3), dtype=np.uint8))
    _save_jpeg(dense, tmp_path / "dense.jpg", quality=85)
    assert (tmp_path / "dense.jpg").stat().st_size <= MAX_IMAGE_BYTES
    with Image.open(tmp_path / "dense.jpg") as saved:
        assert saved.width / saved.height == pytest.approx(1600 / 1200, rel=0.01)
    plain = Image.new("RGB", (1600, 1200), (20, 90, 160))
    _save_jpeg(plain, tmp_path / "plain.jpg", quality=85)
    with Image.open(tmp_path / "plain.jpg") as saved:
        assert saved.size == (1600, 1200)  # an image that fits keeps its size
