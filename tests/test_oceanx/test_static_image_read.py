"""A static run's image read never crashes the Expert: a preview that cannot be made is an error message."""

import asyncio
from types import SimpleNamespace

import pytest
from deepagents.backends.protocol import ExecuteResponse, ReadResult
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain_core.messages import ToolMessage
from PIL import Image

from oceanx.figure_delivery import FIGURE_DELIVERY_ENV
from oceanx.native_backend import OceanSandbox
from tests.test_oceanx.test_saved_data_index import _backend


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, "static")
    sandbox = OceanSandbox(service=object(), work_root=tmp_path / "expert", read_roots=lambda: ())

    async def local_execute(command, *, timeout=None):
        process = await asyncio.create_subprocess_exec(
            "/bin/bash", "-c", command, cwd=sandbox.cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return ExecuteResponse(
            output=(stdout + stderr).decode("utf-8", errors="replace"), exit_code=process.returncode)

    monkeypatch.setattr(sandbox, "aexecute", local_execute)
    return sandbox


async def read_file(backend, path):
    """The real deepagents read_file tool, the way an Expert's model calls it."""
    tool = next(t for t in FilesystemMiddleware(backend=backend).tools if t.name == "read_file")
    return await tool.coroutine(
        file_path=str(path), runtime=SimpleNamespace(tool_call_id="call-1"), offset=0, limit=100)


@pytest.mark.asyncio
async def test_a_missing_image_is_a_not_found_read_result_like_any_other_missing_file(backend):
    missing = backend.outputs / "nope.png"

    result = await backend.aread(str(missing))

    assert isinstance(result, ReadResult)
    assert result.error and str(missing) in result.error and "file_not_found" in result.error


@pytest.mark.asyncio
async def test_a_corrupt_image_is_a_read_result_that_says_what_failed(backend):
    corrupt = backend.outputs / "bad.png"
    corrupt.write_bytes(b"not a png")

    result = await backend.aread(str(corrupt))

    assert isinstance(result, ReadResult)
    assert result.error and "preview" in result.error and "UnidentifiedImageError" in result.error
    assert "Traceback" not in result.error  # the exception line, not a page of stack frames


@pytest.mark.asyncio
@pytest.mark.parametrize("name, contents", [("nope.png", None), ("bad.png", b"not a png")])
async def test_read_file_returns_an_error_message_for_an_unreadable_image(backend, name, contents):
    path = backend.outputs / name
    if contents is not None:
        path.write_bytes(contents)

    message = await read_file(backend, path)  # must not raise: an exception ends the Expert's run

    assert isinstance(message, ToolMessage) and message.status == "error"
    assert message.text.startswith("Error: ")


@pytest.mark.asyncio
async def test_read_file_still_returns_the_image_when_the_preview_can_be_made(backend):
    path = backend.outputs / "figure.png"
    Image.new("RGB", (3000, 1800), "navy").save(path)

    message = await read_file(backend, path)

    assert isinstance(message, ToolMessage) and message.status != "error"
    assert [block["type"] for block in message.content] == ["image"]


@pytest.mark.asyncio
async def test_the_real_sandbox_makes_the_preview_and_reports_unreadable_images(tmp_path, monkeypatch):
    # The same reads through the OS sandbox (bubblewrap on Linux): the Pillow import, the preview
    # written under the agent's own temporary folder, and the preview read back.
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, "static")
    async with _backend(tmp_path, monkeypatch) as (host, task, _config, _seen):
        root = host.task_workspace_projector.expert_session_root(task.task_id, "image-preview")
        real = OceanSandbox(service=host.expert_code_execution, work_root=root, read_roots=lambda: ())
        figure = real.outputs / "figure.png"
        Image.new("RGB", (3000, 1800), "navy").save(figure)
        corrupt = real.outputs / "bad.png"
        corrupt.write_bytes(b"not a png")

        shown = await real.aread(str(figure))
        missing = await real.aread(str(real.outputs / "nope.png"))
        broken = await real.aread(str(corrupt))

        assert shown.error is None and shown.file_data["encoding"] == "base64"
        assert missing.error and "file_not_found" in missing.error
        assert broken.error and "UnidentifiedImageError" in broken.error
        previews = list((real.temporary / "image-previews").glob("*.jpg"))
        assert len(previews) == 1 and previews[0].stat().st_size <= 450 * 1024
        assert figure.stat().st_size > 0  # the full-resolution figure is untouched
