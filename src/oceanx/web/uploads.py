"""Bounded PDF staging for the browser; native source import still binds the paper."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from urllib.parse import unquote

import anyio
from starlette.requests import Request

MAX_PDF_BYTES = 25 * 1024 * 1024


class InvalidUpload(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.status = status


async def stage_pdf(request: Request, workspace: Path) -> Path:
    name = unquote(request.headers.get("x-filename", ""))
    if (not name or len(name.encode("utf-8")) > 200 or name in {".", ".."}
            or any(c in name for c in "/\\") or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or Path(name).suffix.lower() != ".pdf"):
        raise InvalidUpload("invalid_pdf_name")
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/pdf":
        raise InvalidUpload("invalid_pdf")
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError as exc:
        raise InvalidUpload("invalid_pdf") from exc
    if declared < 0:
        raise InvalidUpload("invalid_pdf")
    if declared > MAX_PDF_BYTES:
        raise InvalidUpload("pdf_too_large", 413)

    # Outside private backend state so the existing source.import validation applies.
    root = workspace / "Uploaded papers"
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or root.resolve() != workspace.resolve() / root.name:
        raise InvalidUpload("upload_unavailable")
    directory = Path(tempfile.mkdtemp(prefix="paper-", dir=root))
    complete = False
    try:
        temporary = directory / ".upload"
        size, signature = 0, bytearray()
        async with await anyio.open_file(temporary, "xb") as stream:
            temporary.chmod(0o600)
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_PDF_BYTES:
                    raise InvalidUpload("pdf_too_large", 413)
                signature.extend(chunk[:max(0, 5 - len(signature))])
                await stream.write(chunk)
        if signature != b"%PDF-":
            raise InvalidUpload("invalid_pdf")
        path = directory / name
        temporary.rename(path)
        complete = True
        return path.resolve()
    finally:
        if not complete:
            # Cancellation and disconnected clients must not leave partial papers.
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(shutil.rmtree, directory)
