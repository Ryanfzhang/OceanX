import json

import pytest

from oceanx.native_text import TEXT_PAGE_CHARS, text_grep, text_read


def test_search_skips_known_and_disguised_binary_and_keeps_shared_text(tmp_path):
    (tmp_path / 'nested').mkdir()
    (tmp_path / 'nested' / 'shared.md').write_text('evidence 温度\nbox_transport = 7\n')
    (tmp_path / 'raw.nc').write_bytes(b'box_transport' * 100_000)
    (tmp_path / 'unknown').write_bytes(b'\0box_transport')
    (tmp_path / 'pickle.txt').write_bytes(b'\x80\x04box_transport')
    result = text_grep('box_transport', str(tmp_path), '**/*')
    assert not result['truncated']
    assert result['matches'] == [{'path': str(tmp_path / 'nested' / 'shared.md'),
                                 'line': 2, 'text': 'box_transport = 7'}]
    assert text_grep('box_transport', str(tmp_path), '*.md') == result
    assert text_grep('box_transport', str(tmp_path), 'nested/**/*.md') == result
    with pytest.raises(FileNotFoundError):
        text_grep('x', str(tmp_path / 'missing'))


def test_grep_caps_matches_and_long_lines_without_losing_source_pointer(tmp_path):
    path = tmp_path / 'history.md'
    path.write_text(('x' * 40_000 + ' evidence ' + 'z' * 40_000 + '\n') * 30)
    result = text_grep('evidence', str(path))
    assert result['truncated'] and len(json.dumps(result, ensure_ascii=False)) < TEXT_PAGE_CHARS + 100
    assert all('evidence' in m['text'] and m['path'] == str(path) for m in result['matches'])
    assert len(text_grep('evidence', str(path), max_count=1)['matches']) == 1
    assert text_grep('evidence', str(path), max_count=0)['truncated']


def test_normal_read_pagination_is_lossless(tmp_path):
    path = tmp_path / 'shared.md'
    original = ''.join(f'{i}: ' + '海水' * 200 + '\n' for i in range(100))
    path.write_text(original)
    offset, parts = 0, []
    while True:
        page = text_read(str(path), offset, 2000, str(tmp_path / 'pages'))
        assert len(page['content']) <= TEXT_PAGE_CHARS
        parts.append(page['content'])
        if 'next_offset' not in page:
            break
        assert page['next_offset'] > offset
        offset = page['next_offset']
    assert ''.join(parts) == original
    assert text_read(str(path), 0, 0, '')['no_lines_requested']
    assert text_read(str(path), 1000, 10, '')['content'] == ''


def test_long_line_has_recoverable_continuation_not_repeated_truncated_prefix(tmp_path):
    path = tmp_path / 'archive.md'
    long_line = '中文\\"' * 20_000 + '\n'
    path.write_text('before\n' + long_line + 'after\n')
    pages = tmp_path / 'pages'
    first = text_read(str(path), 0, 2000, str(pages))
    assert first['content'] == 'before\n' and first['next_offset'] == 1
    second = text_read(str(path), 1, 2000, str(pages))
    view = next(pages.glob('*.txt'))
    assert str(view) in second['content'] and 'offset=2' in second['content']
    assert len(second['content']) < TEXT_PAGE_CHARS
    assert ''.join(json.loads(line) for line in view.read_text().splitlines()) == long_line
    offset, parts = 0, []
    while True:
        page = text_read(str(view), offset, 8, str(pages))
        parts.extend(json.loads(line) for line in page['content'].splitlines())
        if 'next_offset' not in page:
            break
        offset = page['next_offset']
    assert ''.join(parts) == long_line
    assert text_read(str(path), 2, 10, str(pages))['content'] == 'after\n'
    assert path.read_text() == 'before\n' + long_line + 'after\n'
