"""Large native edits return a result after writing, rather than crashing the agent."""

import asyncio

import pytest
from deepagents.backends.protocol import EditResult, ExecuteResponse
from PIL import Image

from oceanx.figure_delivery import FIGURE_DELIVERY_ENV
from oceanx.native_backend import OceanSandbox, ResearchSandbox
from tests.test_oceanx.test_saved_data_index import _backend


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_type", [OceanSandbox, ResearchSandbox])
@pytest.mark.parametrize("found", [True, False])
async def test_large_native_edit_returns_a_result_from_the_real_sandbox(
    tmp_path, monkeypatch, backend_type, found,
):
    async with _backend(tmp_path, monkeypatch) as (host, task, _config, _seen):
        root = host.task_workspace_projector.expert_session_root(task.task_id, "large-edit")
        backend = backend_type(service=host.expert_code_execution, work_root=root, read_roots=lambda: ())
        path = backend.cwd / "analysis.py"
        old, new = "old-" + "a" * 30_000, "new-" + "b" * 30_000
        assert len(old.encode()) + len(new.encode()) > 50_000
        original = f"prefix\n{old}\nsuffix\n" if found else "prefix\nunchanged\nsuffix\n"
        path.write_text(original, encoding="utf-8")
        result = await backend.aedit(str(path), old, new)
        assert isinstance(result, EditResult)
        if found:
            assert result.error is None and result.occurrences == 1
            assert result.path == str(path)
            assert path.read_text() == original.replace(old, new)
        else:
            assert result.error and "not found" in result.error.lower()
            assert path.read_text() == original


@pytest.mark.asyncio
async def test_static_image_reads_create_a_bounded_context_preview(tmp_path, monkeypatch):
    monkeypatch.setenv(FIGURE_DELIVERY_ENV, "static")
    backend = OceanSandbox(service=object(), work_root=tmp_path / "image-preview", read_roots=lambda: ())
    image = backend.outputs / "large.png"
    Image.new("RGB", (3000, 1800), "navy").save(image)

    async def local_execute(command, *, timeout=None):
        process = await asyncio.create_subprocess_exec(
            "/bin/bash", "-c", command, cwd=backend.cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return ExecuteResponse(
            output=(stdout + stderr).decode("utf-8", errors="replace"),
            exit_code=process.returncode,
        )

    monkeypatch.setattr(backend, "aexecute", local_execute)
    result = await backend.aread(str(image))

    assert result.file_data and result.file_data["encoding"] == "base64"
    previews = list((backend.temporary / "image-previews").glob("*.jpg"))
    assert len(previews) == 1
    assert previews[0].stat().st_size <= 450 * 1024
    with Image.open(previews[0]) as preview:
        assert max(preview.size) == 1024
