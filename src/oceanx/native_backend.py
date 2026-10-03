"""DeepAgents' native filesystem/shell API on OceanX's existing OS sandbox.

BaseSandbox supplies ls/glob/grep/read/write/edit/delete; no OceanX tool schemas.
All paths are real absolute paths, shared with the persistent Python kernel.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import shlex
import tempfile
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    GrepResult,
    ReadResult,
)
from deepagents.backends.sandbox import (
    BaseSandbox,
    _build_edit_tmpfile_cmd,
    _get_backend_read_file_type,
    _map_edit_error,
    _parse_read_output,
)

from oceanx import native_text
from oceanx.sandbox import SandboxExecutionPolicy, run_sandboxed_command
from oceanx.sandbox.execution import POSIX_SHELL, shell_runtime_roots

_RASTER_IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
)
STATIC_IMAGE_PREVIEW_MAX_EDGE = 1024


def _preview_error(file_path, output: str) -> str:
    """What the model is told when no preview could be made: the exception, not its stack frames."""
    lines = [line for line in output.strip().splitlines() if line.strip()]
    detail = lines[-1] if lines else "no output"
    if detail.startswith("FileNotFoundError"):
        return f"File '{file_path}': file_not_found"  # the wording a missing text file gets
    return f"File '{file_path}': could not create the image preview ({detail[:300]})"


class OceanSandbox(BaseSandbox):
    def __init__(self, *, service, work_root: Path, read_roots, record_command=None):
        self.service = service
        self.work_root = work_root.resolve()
        self.cwd = self.work_root / "scratch"
        self.outputs = self.work_root / "outputs"
        runtime_root = self.work_root / ".runtime"
        self.temporary = runtime_root / "temporary"
        self.logs = runtime_root / "logs"
        for path in (self.cwd, self.outputs, self.temporary, self.logs):
            path.mkdir(parents=True, exist_ok=True)
        self.read_roots = read_roots
        self.record_command = record_command

    @property
    def id(self):
        return str(self.work_root)

    async def aexecute(self, command, *, timeout=None):
        runtime = await asyncio.to_thread(self.service.require_runtime)
        roots = self.read_roots()  # refresh shared evidence after other Experts finish
        policy = SandboxExecutionPolicy(
            read_only_roots=tuple(roots), runtime_read_roots=shell_runtime_roots(runtime.read_roots),
            writable_roots=(self.work_root,), output_root=self.outputs, temporary_root=self.temporary,
            limits=replace(self.service.limits, wall_time_seconds=min(timeout or 300,
                self.service.limits.wall_time_seconds or 300)),
            allow_child_processes=True, allow_network=True)
        # Commands never inherit the server's credentials or ambient Python.
        env = {"PATH": os.pathsep.join((str(runtime.executable.parent), "/usr/bin", "/bin")),
               "CONDA_PREFIX": str(runtime.prefix), "CONDA_DEFAULT_ENV": runtime.environment_name,
               "OCEAN_OUTPUT_DIR": str(self.outputs), "OCEAN_WORK_DIR": str(self.cwd),
               "PYTHONNOUSERSITE": "1"}
        log = self.logs / uuid4().hex
        log.mkdir()
        (log / "command.sh").write_text(command, encoding="utf-8")
        try:
            result = await run_sandboxed_command((POSIX_SHELL, "-c", command),
                policy=policy, cwd=self.cwd, environment=env)
        except BaseException as exc:
            (log / "status.json").write_text(json.dumps({"error": type(exc).__name__}), encoding="utf-8")
            raise
        (log / "stdout.txt").write_bytes(result.stdout)
        (log / "stderr.txt").write_bytes(result.stderr)
        (log / "status.json").write_text(json.dumps({"state": result.status.value,
            "exit_code": result.returncode, "seconds": result.duration_seconds}), encoding="utf-8")
        # Native middleware offloads large outputs; do not replace structured file-helper output.
        return ExecuteResponse(output=(result.stdout + result.stderr).decode("utf-8", errors="replace"),
                               exit_code=result.returncode)

    def execute(self, command, *, timeout=None):
        return asyncio.run(self.aexecute(command, timeout=timeout))

    async def _text_helper(self, **request):
        # Shipping code through the existing sandbox keeps source/shared-data
        # permissions identical to native read_file and execute.
        code = Path(native_text.__file__).read_text(encoding="utf-8")
        return await self.aexecute("python3 -c " + shlex.quote(code + "\nrun(" + repr(request) + ")"))

    def read(self, file_path, offset=0, limit=2000):
        return asyncio.run(self.aread(file_path, offset, limit))

    async def aread(self, file_path, offset=0, limit=2000):
        # Bound static benchmark figures before they enter model context. The full-resolution image
        # remains on disk as the durable result; read_file supplies a compact scientific preview.
        from oceanx.figure_delivery import static_figures
        if static_figures() and Path(file_path).suffix.lower() in _RASTER_IMAGE_SUFFIXES:
            preview_root = self.temporary / "image-previews"
            preview = preview_root / (hashlib.sha256(str(file_path).encode()).hexdigest() + ".jpg")
            code = (
                "from pathlib import Path\n"
                "from PIL import Image, ImageOps\n"
                f"source=Path({str(file_path)!r})\n"
                f"target=Path({str(preview)!r})\n"
                "target.parent.mkdir(parents=True, exist_ok=True)\n"
                "with Image.open(source) as opened:\n"
                "    image=ImageOps.exif_transpose(opened)\n"
                f"    image.thumbnail(({STATIC_IMAGE_PREVIEW_MAX_EDGE}, "
                f"{STATIC_IMAGE_PREVIEW_MAX_EDGE}))\n"
                "    if image.mode in {'RGBA', 'LA'} or (image.mode == 'P' and 'transparency' in image.info):\n"
                "        rgba=image.convert('RGBA')\n"
                "        background=Image.new('RGB', rgba.size, 'white')\n"
                "        background.paste(rgba, mask=rgba.getchannel('A'))\n"
                "        image=background\n"
                "    else:\n"
                "        image=image.convert('RGB')\n"
                "    image.save(target, format='JPEG', quality=82, optimize=True)\n"
                "    for edge, quality in ((768, 76), (512, 72)):\n"
                "        if target.stat().st_size <= 450 * 1024:\n"
                "            break\n"
                "        image.thumbnail((edge, edge))\n"
                "        image.save(target, format='JPEG', quality=quality, optimize=True)\n"
            )
            result = await self.aexecute("python3 -c " + shlex.quote(code))
            if result.exit_code != 0:
                return ReadResult(error=_preview_error(file_path, result.output))
            return await super().aread(str(preview), offset, limit)
        # Keep native PDF/media handling, not a blanket text truncation.
        if _get_backend_read_file_type(file_path) != "text":
            return await super().aread(file_path, offset, limit)
        result = await self._text_helper(operation="read", file_path=file_path, offset=offset,
                                        limit=limit, pages_root=str(self.temporary / "read-pages"))
        return _parse_read_output(result.output, file_path)

    def grep(self, pattern, path=None, glob=None, *, max_count=None):
        return asyncio.run(self.agrep(pattern, path, glob, max_count=max_count))

    async def agrep(self, pattern, path=None, glob=None, *, max_count=None):
        result = await self._text_helper(operation="grep", pattern=pattern,
                                        path=path or str(self.cwd), glob=glob, max_count=max_count)
        try:
            return GrepResult(**json.loads(result.output))
        except (ValueError, TypeError):
            return GrepResult(error=f"Search failed: {result.output[:1000]}")

    def _edit_via_upload(self, file_path, old_string, new_string, replace_all):
        return asyncio.run(self._aedit_via_upload(file_path, old_string, new_string, replace_all))

    async def _aedit_via_upload(self, file_path, old_string, new_string, replace_all):
        # BaseSandbox hardcodes /tmp for this large-payload branch. Its edit
        # algorithm is unchanged; only staging lives in this agent's sandbox.
        with tempfile.TemporaryDirectory(prefix="edit-", dir=self.temporary) as staging:
            old_tmp, new_tmp = str(Path(staging) / "old"), str(Path(staging) / "new")
            uploaded = await self.aupload_files([(old_tmp, old_string.encode()), (new_tmp, new_string.encode())])
            if len(uploaded) != 2 or any(item.error for item in uploaded):
                return EditResult(error=f"Error editing file '{file_path}': temporary upload failed: {uploaded}")
            command = _build_edit_tmpfile_cmd(file_path, old_tmp, new_tmp, replace_all=replace_all)
            result = await self.aexecute(command)
            try:
                data = json.loads(result.output)
            except ValueError:
                data = None
            if result.exit_code != 0 or not isinstance(data, dict):
                return EditResult(error=f"Error editing file '{file_path}': {result.output[:1000]}")
            if "error" in data:
                return _map_edit_error(data["error"], file_path, old_string)
            return EditResult(path=file_path, occurrences=data.get("count", 1))

    async def aupload_files(self, files):
        responses = []
        for path, content in files:
            # Stage bytes, then let the sandbox perform the actual destination write.
            with tempfile.NamedTemporaryFile(dir=self.temporary) as staged:
                staged.write(content)
                staged.flush()
                code = ("from pathlib import Path; import shutil; "
                        f"p=Path({path!r}); p.parent.mkdir(parents=True, exist_ok=True); "
                        f"shutil.copyfile({staged.name!r}, p)")
                result = await self.aexecute("python3 -c " + shlex.quote(code))
                responses.append(FileUploadResponse(path=path,
                    error=None if result.exit_code == 0 else result.output))
        return responses

    def upload_files(self, files):
        return asyncio.run(self.aupload_files(files))

    async def adownload_files(self, paths):
        responses = []
        for path in paths:
            code = f"import base64; from pathlib import Path; print(base64.b64encode(Path({path!r}).read_bytes()).decode())"
            result = await self.aexecute("python3 -c " + shlex.quote(code))
            responses.append(FileDownloadResponse(path=path,
                content=base64.b64decode(result.output) if result.exit_code == 0 else None,
                error=None if result.exit_code == 0 else result.output))
        return responses

    def download_files(self, paths):
        return asyncio.run(self.adownload_files(paths))


class ResearchSandbox(OceanSandbox):
    """Only explicit execute calls enter scientific execution provenance.

Native filesystem helpers use an identical sandbox without treating ls/read as
scientific analysis or snapshotting all existing outputs on every file read.
"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.files = OceanSandbox(**{**kwargs, "record_command": None})

    async def aexecute(self, command, *, timeout=None):
        if self.record_command is None:
            return await super().aexecute(command, timeout=timeout)
        result = await self.record_command(command, timeout)
        output = result.stdout + result.stderr
        if result.state == "timed_out":  # otherwise the model sees only "exit code -15"
            output += (f"\n[Stopped at the time limit after {result.duration_seconds:.0f} s; a larger "
                       "timeout does not extend it. Process less data per run or save partial results.]")
        return ExecuteResponse(output=output, exit_code=result.returncode)

    async def als(self, path):
        return await self.files.als(path)

    async def aread(self, file_path, offset=0, limit=2000):
        return await self.files.aread(file_path, offset, limit)

    async def aglob(self, pattern, path=None):
        return await self.files.aglob(pattern, path or str(self.cwd))

    async def agrep(self, pattern, path=None, glob=None, *, max_count=None):
        return await self.files.agrep(pattern, path or str(self.cwd), glob, max_count=max_count)

    async def awrite(self, file_path, content):
        return await self.files.awrite(file_path, content)

    async def aedit(self, file_path, old_string, new_string, replace_all=False):
        return await self.files.aedit(file_path, old_string, new_string, replace_all)

    async def adelete(self, file_path):
        return await self.files.adelete(file_path)

    async def aupload_files(self, files):
        return await self.files.aupload_files(files)

    async def adownload_files(self, paths):
        return await self.files.adownload_files(paths)

    def ls(self, path):
        return self.files.ls(path)

    def read(self, file_path, offset=0, limit=2000):
        return self.files.read(file_path, offset, limit)

    def glob(self, pattern, path=None):
        return self.files.glob(pattern, path or str(self.cwd))

    def grep(self, pattern, path=None, glob=None, *, max_count=None):
        return self.files.grep(pattern, path or str(self.cwd), glob, max_count=max_count)

    def write(self, file_path, content):
        return self.files.write(file_path, content)

    def edit(self, file_path, old_string, new_string, replace_all=False):
        return self.files.edit(file_path, old_string, new_string, replace_all)

    def delete(self, file_path):
        return self.files.delete(file_path)


def task_backend(host, config, *, run, library):
    """Same filesystem capabilities for every role, no startup Python inspection."""
    from oceanx.datasets import resolve_dataset_source
    from oceanx.native_skills import skill_backend

    c = config["configurable"]
    service = host.expert_code_execution
    task_root = host.task_workspace_projector.ensure_task_root(c["task_id"])
    work_root = (host.task_workspace_projector.expert_session_root(c["task_id"], run.thread_id)
                 if run else task_root / "agents" / "coordinator")
    from oceanx.figure_delivery import static_figures
    work_root.mkdir(parents=True, exist_ok=True)
    runtime_root = work_root / ".runtime"
    runtime_root.mkdir(exist_ok=True)
    if static_figures():
        # A static-delivery run describes no plotting interface, not even in a file.
        (runtime_root / "result-api.md").unlink(missing_ok=True)
    else:
        from oceanx.figure_reference import figure_api_reference

        (runtime_root / "result-api.md").write_text(
            figure_api_reference(),
            encoding="utf-8",
        )
    def read_roots():
        roots = [library, service.task_results_root(c["task_id"])]
        roots.extend(service.shared_result_directories(workspace_id=c["workspace_id"],
            task_id=c["task_id"], agent_thread_id=run.thread_id if run else None))
        for record in host.store.list_task_artifacts(task_id=c["task_id"]):
            if "source" not in record.relations:
                continue
            artifact = record.artifact
            if artifact.artifact_type == "dataset":
                roots.append(resolve_dataset_source(store=host.store, paths=host.paths,
                    workspace_id=c["workspace_id"], ref=artifact.ref).path)
            elif (
                artifact.artifact_type == "project_context"
                and artifact.schema_version == "ocean-local-source/v1"
            ):
                from oceanx.local_sources import resolve_local_source
                roots.append(resolve_local_source(
                    store=host.store, workspace_id=c["workspace_id"], ref=artifact.ref
                ).path)
            else:
                roots.extend(host.paths.resolve_uri(f.uri) for f in artifact.files)
        return tuple(path for path in roots if path.exists())
    from oceanx.expert_execution import STANDARD_MODE_CODE_SECONDS
    from oceanx.research.graphs import research_mode
    research = research_mode(config)

    async def record_command(command, timeout):
        if not research:
            timeout = min(timeout or STANDARD_MODE_CODE_SECONDS, STANDARD_MODE_CODE_SECONDS)
        return await service.run_shell(workspace_id=c["workspace_id"], task_id=c["task_id"],
            agent_thread_id=run.thread_id, server_run_id=run.server_run_id,
            origin_request_id=c.get("request_id"), command=command, timeout=timeout)
    sandbox = ResearchSandbox(service=service, work_root=work_root, read_roots=read_roots,
                              record_command=record_command if run else None)
    return skill_backend(
        library,
        default=sandbox,
        artifacts_root=str(runtime_root / "context"),
    ), sandbox.cwd
