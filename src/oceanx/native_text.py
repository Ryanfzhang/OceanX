"""Text-only sandbox helpers behind the existing DeepAgents read/grep tools.

Executed inside the OS sandbox, not against host files in the server process.
"""
import fnmatch
import json
import os
from pathlib import Path
from uuid import uuid4

TEXT_PAGE_CHARS = 12_000
LONG_LINE_CHUNK = 1_000
BINARY_SUFFIXES = frozenset({
    '.nc', '.nc4', '.h5', '.hdf', '.hdf5', '.npy', '.npz', '.pkl', '.pickle',
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf', '.zip', '.gz', '.parquet',
    '.sqlite', '.sqlite3', '.db', '.pyc', '.so', '.dylib', '.mp4', '.mp3',
})


def is_binary(path):
    if path.suffix.lower() in BINARY_SUFFIXES:
        return True
    with path.open('rb') as stream:
        sample = stream.read(8192)
    if b'\0' in sample:
        return True
    # A trailing partial UTF-8 codepoint is not binary.
    import codecs
    try:
        codecs.getincrementaldecoder('utf-8')().decode(sample, final=False)
    except UnicodeDecodeError:
        return True
    return False


def text_grep(pattern, path, glob=None, max_count=None):
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(path)
    if root.is_file():
        targets = [root]
    else:
        def walk():
            def onerror(error):
                raise error
            for directory, dirs, files in os.walk(root, onerror=onerror):
                dirs.sort()
                for name in sorted(files):
                    yield Path(directory) / name
        targets = walk()
    matches, size = [], 0
    for file in targets:
        relative = file.relative_to(root).as_posix() if file != root else file.name
        if glob:
            if not (_path_match(relative.split('/'), glob.split('/')) if '/' in glob
                    else fnmatch.fnmatch(file.name, glob)):
                continue
        if is_binary(file):
            continue
        with file.open(encoding='utf-8') as stream:
            for number, line in enumerate(stream, 1):
                pos = line.find(pattern)
                if pos < 0:
                    continue
                text = line.rstrip('\n')
                if len(text) > 1200:
                    start = max(0, pos - 200)
                    text = '[excerpt] ' + text[start:start + 1200] + ' [read source line for full text]'
                match = {'path': str(file), 'line': number, 'text': text}
                cost = len(json.dumps(match, ensure_ascii=False))
                if (max_count is not None and len(matches) >= max_count) or size + cost > TEXT_PAGE_CHARS:
                    return {'matches': matches, 'truncated': True}
                matches.append(match)
                size += cost
    return {'matches': matches, 'truncated': False}


def _path_match(parts, pattern):
    if not pattern:
        return not parts
    if pattern[0] == '**':
        return (_path_match(parts, pattern[1:]) or
                bool(parts) and _path_match(parts[1:], pattern))
    return (bool(parts) and fnmatch.fnmatch(parts[0], pattern[0]) and
            _path_match(parts[1:], pattern[1:]))


def text_read(file_path, offset, limit, pages_root):
    offset, limit = max(0, int(offset)), max(0, int(limit))
    if not limit:
        return {'content': '', 'no_lines_requested': True}
    path = Path(file_path)
    if is_binary(path):
        return {'error': 'Binary data is not text. Use the appropriate data reader; the source is unchanged.'}
    content, used, count = [], 0, 0
    with path.open(encoding='utf-8', newline='') as stream:
        # Skip without materializing arbitrarily large lines.
        for _ in range(offset):
            while True:
                chunk = stream.readline(TEXT_PAGE_CHARS)
                if not chunk or chunk.endswith('\n'):
                    break
        while count < limit:
            line = stream.readline(TEXT_PAGE_CHARS + 1)
            if not line:
                break
            if len(line) > TEXT_PAGE_CHARS:
                if content:
                    break  # next_offset still points at the unshown long line
                # Native read_file offsets count lines, not characters. Make a
                # lossless wrapped view of this ONE line, without adding a tool.
                pages = Path(pages_root)
                pages.mkdir(parents=True, exist_ok=True)
                view = pages / (uuid4().hex + '.txt')
                with view.open('w', encoding='utf-8', newline='') as target:
                    while line:
                        ended = line.endswith('\n')
                        for start in range(0, len(line), LONG_LINE_CHUNK):
                            # JSON strings preserve whitespace/newlines exactly.
                            target.write(json.dumps(line[start:start + LONG_LINE_CHUNK], ensure_ascii=False) + '\n')
                        if ended:
                            break
                        line = stream.readline(TEXT_PAGE_CHARS + 1)
                return {'content': (
                    f'Source {file_path}, line {offset + 1}, exceeds one text page. '
                    f'Read the lossless JSON-string chunks at {view} with offset=0, limit=8; '
                    'subsequent offsets are supplied by read_file. Decode and concatenate the strings '
                    f'to recover the exact source line. After this line, resume the original file at offset={offset + 1}.')}
            if content and used + len(line) > TEXT_PAGE_CHARS:
                break
            content.append(line)
            used += len(line)
            count += 1
        more = bool(line) if count < limit else bool(stream.read(1))
    if not content:
        return {'content': ''}
    result = {'content': ''.join(content), 'start_line': offset + 1, 'end_line': offset + count}
    if more:
        result['next_offset'] = offset + count
    return result


def run(request):
    try:
        operation = request.pop('operation')
        result = text_read(**request) if operation == 'read' else text_grep(**request)
    except (OSError, UnicodeError, ValueError) as error:
        result = {'error': f'{type(error).__name__}: {error}'}
    print(json.dumps(result, ensure_ascii=False))
