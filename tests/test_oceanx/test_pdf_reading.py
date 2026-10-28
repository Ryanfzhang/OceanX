"""Attached PDF pages reach a model as paired text and images, via read_file."""
import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.permissions import FilesystemPermission
from langchain_core.messages import AIMessage, ToolMessage

from oceanx.pdf_reading import PdfFilesystemMiddleware
from oceanx.pdf_text import MAX_IMAGE_BYTES, page_jpeg, pdf_text
from oceanx.model_config import OceanChatDeepSeek
from tests.test_oceanx.test_pdf_text import _write_pdf, _paths


def reader(tmp_path, **kwargs):
    pdf = _write_pdf(tmp_path / 'paper.pdf', ['First page', 'Methods and equations', 'Third page'])
    text = pdf_text(pdf, _paths(tmp_path))
    backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=False)
    middleware = PdfFilesystemMiddleware(backend=backend, tools=['read_file'],
        pdf_documents={str(pdf): str(text), str(text): str(text)}, **kwargs)
    tool = next(tool for tool in middleware.tools if tool.name == 'read_file')
    return pdf, text, tool


@pytest.mark.asyncio
async def test_page_selection_delivers_text_and_image_together(tmp_path):
    pdf, text, tool = reader(tmp_path)
    result = await tool.coroutine(file_path=str(pdf), pages='2', runtime=SimpleNamespace(tool_call_id='read'))
    assert result.status == 'success'
    assert result.additional_kwargs['pdf_pages'] == [2]
    assert [b['type'] for b in result.content] == ['text', 'image', 'text']
    assert 'Methods and equations' in result.content[0]['text']
    assert 'First page' not in result.content[0]['text']
    assert base64.b64decode(result.content[1]['base64']) == (text.with_suffix('.figures') / 'page-02.jpg').read_bytes()
    assert 'starting at 3' in result.content[-1]['text']
    assert 'pages' in tool.args_schema.model_fields


@pytest.mark.asyncio
async def test_existing_text_read_also_pairs_pages_and_paginates(tmp_path):
    _, text, tool = reader(tmp_path)
    runtime = SimpleNamespace(tool_call_id='read')
    first = await tool.coroutine(file_path=str(text), runtime=runtime)
    assert first.additional_kwargs['pdf_pages'] == [1, 2]
    assert [b['type'] for b in first.content] == ['text', 'image', 'text', 'image', 'text']
    lines = text.read_text().splitlines()
    offset = next(i for i, line in enumerate(lines) if line.startswith('=== Page 3'))
    last = await tool.coroutine(file_path=str(text), runtime=runtime, offset=offset)
    assert last.additional_kwargs['pdf_pages'] == [3]
    assert [b['type'] for b in last.content] == ['text', 'image']
    invalid = await tool.coroutine(file_path=str(text), runtime=runtime, pages='1-99')
    assert invalid.status == 'error'
    normal = tmp_path / 'ordinary.txt'
    normal.write_text('one\ntwo\nthree')
    result = await tool.coroutine(file_path=str(normal), runtime=runtime, offset=1, limit=1)
    assert isinstance(result.content, str) and 'two' in result.content and 'three' not in result.content


@pytest.mark.asyncio
async def test_pdf_read_honors_native_permissions(tmp_path):
    _, text, tool = reader(tmp_path, _permissions=[FilesystemPermission(operations=['read'], paths=['/**'], mode='deny')])
    result = await tool.coroutine(file_path=str(text), runtime=SimpleNamespace(tool_call_id='read'), pages='2')
    assert result.status == 'error'
    assert 'permission denied' in result.content


def test_dense_image_stays_below_native_binary_limit_without_changing_source():
    image = Image.effect_noise((1600, 1600), 100).convert('RGB')
    source = image.tobytes()
    encoded = page_jpeg(image)
    assert len(encoded) <= MAX_IMAGE_BYTES < 500 * 1024
    assert image.tobytes() == source
    with Image.open(io.BytesIO(encoded)) as decoded:
        assert decoded.format == 'JPEG'
        assert decoded.width >= 900


@pytest.mark.asyncio
async def test_deepseek_payload_contains_page_text_and_image_not_base64_as_prose(tmp_path):
    pdf, _, tool = reader(tmp_path)
    result = await tool.coroutine(file_path=str(pdf), pages='1-2', runtime=SimpleNamespace(tool_call_id='read'))
    model = OceanChatDeepSeek(model='deepseek-flash', api_key='test', base_url='https://api.deepseek.com')
    payload = model._get_request_payload([
        AIMessage(content='', tool_calls=[{'name': 'read_file', 'args': {'file_path': str(pdf), 'pages': '1-2'}, 'id': 'read'}]),
        result,
    ])
    images = payload['messages'][-1]
    assert images['role'] == 'user'
    blocks = images['content']
    image_indices = [i for i, b in enumerate(blocks) if b.get('type') == 'image_url']
    assert len(image_indices) == 2
    assert 'First page' in blocks[image_indices[0]-1]['text']
    assert 'Methods and equations' in blocks[image_indices[1]-1]['text']
    assert 'data:image/jpeg;base64,' in blocks[image_indices[0]]['image_url']['url']


@pytest.mark.asyncio
async def test_native_graph_exposes_pages_and_returns_images_to_next_model_call(tmp_path):
    from deepagents import create_deep_agent
    from oceanx.deep_runtime import _configure_native_harness
    from tests.test_oceanx.test_deep_agent_runtime import _BoundFakeModel
    pdf = _write_pdf(tmp_path / 'paper.pdf', ['A finding', 'An equation'])
    text = pdf_text(pdf, _paths(tmp_path))
    backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=False)
    model = _BoundFakeModel(responses=[
        AIMessage(content='', tool_calls=[{'name': 'read_file', 'args': {'file_path': str(pdf), 'pages': '2'}, 'id': 'p2'}]),
        AIMessage(content='Read page two.'),
    ], profile={'image_inputs': True, 'image_tool_message': True})
    _configure_native_harness(type(model).__name__.lower())
    graph = create_deep_agent(model=model, backend=backend, subagents=[], middleware=[
        PdfFilesystemMiddleware(backend=backend, tools=['read_file'], pdf_documents={str(pdf): str(text)})])
    state = await graph.ainvoke({'messages': [{'role': 'user', 'content': 'Read the methods.'}]})
    receipts = [m for m in state['messages'] if isinstance(m, ToolMessage)]
    assert len(receipts) == 1
    assert receipts[0].status == 'success', receipts[0].content
    assert any(b['type'] == 'image' for b in receipts[0].content)
    seen = [m for m in model.seen_messages[-1] if isinstance(m, ToolMessage)]
    assert any(b['type'] == 'image' for b in seen[0].content_blocks)
    assert 'An equation' in seen[0].text
