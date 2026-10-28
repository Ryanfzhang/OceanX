"""Page-wise text and images through the existing native read_file tool.

Only PDF caches supplied by the task's disclosure-filtered source context are
registered. All content reads still use the native permission-checked tool.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from pydantic import Field, create_model


class PdfFilesystemMiddleware(FilesystemMiddleware):
    def __init__(self, *, pdf_documents=None, **kwargs):
        self.pdf_documents = pdf_documents or {}
        super().__init__(**kwargs)

    def _create_read_file_tool(self):
        native = super()._create_read_file_tool()
        if not self.pdf_documents:
            return native

        schema = create_model("ReadFileWithPdfPages", __base__=native.args_schema,
            pages=(str | None, Field(default=None,
                description="PDF pages, 1-based, e.g. '3' or '3-4'; at most two pages per read. "
                            "PDF reads return each page's text and image together. "
                            "Omit to read from the line offset; the result gives the next offset.")))

        async def read(file_path: str, runtime: ToolRuntime, offset: int = 0, limit: int = 100,
                       pages: str | None = None):
            text_path = self.pdf_documents.get(file_path)
            if text_path is None:
                if pages is not None:
                    return ToolMessage(content="Error: pages is available only for a task's attached PDF.",
                        tool_call_id=runtime.tool_call_id, name="read_file", status="error")
                return await native.coroutine(file_path=file_path, runtime=runtime, offset=offset, limit=limit)
            # Check access before using the cache to locate page boundaries.
            access = await native.coroutine(file_path=str(text_path), runtime=runtime, offset=0, limit=1)
            if access.status == "error":
                return access
            lines = (await asyncio.to_thread(Path(text_path).read_text, encoding="utf-8")).splitlines()
            starts = [i for i, line in enumerate(lines) if re.fullmatch(r"=== Page \d+ of \d+ ===", line)]
            ends = [*starts[1:], len(lines)]
            if pages is not None:
                match = re.fullmatch(r"(\d+)(?:-(\d+))?", pages.strip())
                first, last = (int(match[1]), int(match[2] or match[1])) if match else (0, 0)
                if not (1 <= first <= last <= len(starts) and last - first < 2):
                    return ToolMessage(content=f"Error: select one or two pages within 1-{len(starts)}.",
                        tool_call_id=runtime.tool_call_id, name="read_file", status="error")
                selected = list(range(first - 1, last))
            else:
                selected = [i for i, (start, end) in enumerate(zip(starts, ends))
                            if limit > 0 and end > max(0, offset) and start < max(0, offset) + limit][:2]
            blocks = []
            status = "success"
            for i in selected:
                page = await native.coroutine(file_path=str(text_path), runtime=runtime,
                                              offset=starts[i], limit=ends[i] - starts[i])
                blocks.append({"type": "text", "text": str(page.content)})
                if page.status == "error":
                    status = "error"
                    break
                image_path = next((line[len("[Page image: "):-1] for line in lines[starts[i]:ends[i]]
                                   if line.startswith("[Page image: ") and line.endswith("]")), None)
                if image_path is None:
                    blocks.append({"type": "text", "text": f"Page {i + 1}: page image unavailable."})
                    status = "error"
                    continue
                image = await native.coroutine(file_path=image_path, runtime=runtime)
                blocks.extend(image.content if isinstance(image.content, list) else
                              [{"type": "text", "text": str(image.content)}])
                if image.status == "error":
                    status = "error"
            if selected and ends[selected[-1]] < len(lines):
                blocks.append({"type": "text", "text":
                    f"More PDF pages: read_file(file_path={file_path!r}, offset={ends[selected[-1]]}) "
                    f"or select pages starting at {selected[-1] + 2}."})
            return ToolMessage(content=blocks or "No PDF pages in the requested window.",
                tool_call_id=runtime.tool_call_id, name="read_file", status=status,
                additional_kwargs={"read_file_path": file_path,
                                   "pdf_pages": [i + 1 for i in selected]})

        def sync_read(file_path: str, runtime: ToolRuntime, offset: int = 0, limit: int = 100,
                      pages: str | None = None):
            return asyncio.run(read(file_path, runtime, offset, limit, pages))

        description = native.description.replace("For images and PDFs, pagination", "For images, pagination")
        return native.model_copy(update={"args_schema": schema, "func": sync_read, "coroutine": read,
            "description": description + "\nFor attached PDFs and their extracted text, use pages "
                "to select one or two pages. Each read returns page text and page images together."})
