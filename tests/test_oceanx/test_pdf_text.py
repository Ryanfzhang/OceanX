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
    TEXT_NOTE,
    PdfTextError,
    document_text_allowed,
    pdf_figures,
    pdf_text,
    readable_texts,
    source_text_context,
)
from oceanx.storage import OceanPaths

WORKSPACE = "ws_pdf_source"


def _write_pdf(path: Path, pages: list[str]) -> Path:
    """A minimal PDF with one line of Helvetica per page; an empty string gives a blank page."""

    font = 3 + 2 * len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>",
    ]
    for i, text in enumerate(pages):
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""
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


def test_text_is_extracted_page_by_page_once_and_follows_the_file(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    pdf = _write_pdf(tmp_path / "paper.pdf", ["Upper layer cyclonic", "Middle layer anticyclonic"])

    text = pdf_text(pdf, paths)

    assert text.parent == paths.cache / "pdf-text"
    content = text.read_text(encoding="utf-8")
    assert "=== Page 1 of 2 ===\nUpper layer cyclonic" in content
    assert "=== Page 2 of 2 ===\nMiddle layer anticyclonic" in content
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
    assert sorted(readable_texts(folder, paths)) == sorted(
        Path(item["text_path"]) for item in context["pdf_texts"])
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
        assert readable_texts(source, host.paths) == [text]

        builder.set_policy(workspace_id=WORKSPACE, policy=ModelDataDisclosurePolicy(
            provider_id="deepseek", policy_version=2, document_text="deny"))
        withheld = builder.build(workspace_id=WORKSPACE, provider_id="deepseek",
                                 task_id=task.task_id).payload["task_sources"][0]
        assert withheld["document_text"] == "withheld by the workspace disclosure policy"
        assert "pdf_texts" not in withheld
        assert not document_text_allowed(host.store, WORKSPACE)
    finally:
        await host.close()


def test_deepseek_models_are_sent_no_pdf_attachments():
    flash = OceanChatDeepSeek(model="deepseek-flash", api_key="test")
    assert flash.profile == {"pdf_inputs": False}
    listed = OceanChatDeepSeek(model="deepseek-v4-flash", api_key="test")
    assert listed.profile["pdf_inputs"] is False
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
    assert f"=== Page 1 of 1 ===\n[Figure image: {figure}]\nFig. 2 Layer vorticity" in text.read_text(encoding="utf-8")
    from PIL import Image

    with Image.open(figure) as saved:
        assert saved.size == (1600, 800)  # long edge bounded, aspect kept
    if os.name == "posix":
        assert stat.S_IMODE(figure.stat().st_mode) == 0o600
    assert readable_texts(pdf, paths) == [text, figure.parent]
    assert source_text_context(pdf, paths, allowed=True)["pdf_texts"][0]["figure_images"] == [str(figure)]
