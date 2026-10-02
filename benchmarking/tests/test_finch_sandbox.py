"""Fixed-code Linux isolation tests. No model calls and no scientific datasets."""
import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import finch_sandbox
import pytest
from finch_sandbox import cpu_ids, execute_notebook, kernel_check, sandbox_command

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not all(shutil.which(p) for p in ("bwrap", "prlimit", "taskset")),
    reason="Real Finch namespace tests require Linux and Bubblewrap",
)


@pytest.fixture
def native_spec(tmp_path):
    workspace, data = tmp_path / "workspace", tmp_path / "data"
    for directory in (workspace, data, workspace / "outputs", workspace / "scratch"):
        directory.mkdir()
    (data / "values.txt").write_text("42")
    return {"workspace": str(workspace), "mounts": [
        {"source": str(data), "target": "/inputs/0/data", "read_only": True}],
        "kernel": {"executable": sys.executable, "runtime_roots": sorted({sys.prefix, sys.base_prefix})},
        "bwrap": shutil.which("bwrap"), "prlimit": shutil.which("prlimit"),
        "taskset": shutil.which("taskset"), "memory_bytes": 8 * 1024**3,
        "cpus": 1, "cpu_ids": cpu_ids(), "execution_timeout": 30}


def save_notebook(spec, code):
    import nbformat
    notebook = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(code)])
    nbformat.write(notebook, Path(spec["workspace"]) / "notebook.ipynb")


def test_native_notebook_reads_only_declared_inputs_and_saves_outputs(native_spec, tmp_path, monkeypatch):
    pytest.importorskip("nbconvert")
    import nbformat
    secret = tmp_path / "unbound.txt"
    secret.write_text("not visible")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-must-not-reach-kernel")
    save_notebook(native_spec, f'''
from pathlib import Path
import os, socket, sys
assert sys.executable == {native_spec['kernel']['executable']!r}
assert not Path({str(secret)!r}).exists()
assert "OPENAI_API_KEY" not in os.environ
data = Path("/inputs/0/data/values.txt")
assert int(data.read_text()) == 42
try:
    data.write_text("wrong")
    raise AssertionError("original input was writable")
except OSError:
    pass
s = socket.socket()
s.settimeout(1)
try:
    s.connect(("1.1.1.1", 53))
    raise AssertionError("external network reachable")
except OSError:
    pass
finally:
    s.close()
Path("outputs/result.txt").write_text("42")
print(42)
''')
    code, tail = asyncio.run(execute_notebook(native_spec, tmp_path / "execution.log"))
    assert code == 0, tail
    notebook = nbformat.read(Path(native_spec["workspace"]) / "notebook.ipynb", as_version=4)
    assert not any(output.output_type == "error" for cell in notebook.cells for output in cell.outputs)
    assert (Path(native_spec["workspace"]) / "outputs/result.txt").read_text() == "42"
    assert (tmp_path / "data/values.txt").read_text() == "42" and secret.read_text() == "not visible"


def test_native_filesystem_and_network_boundary(native_spec, tmp_path, monkeypatch):
    secret = tmp_path / "unbound.txt"
    secret.write_text("not visible")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    code = f'''
from pathlib import Path
import os, socket
assert not Path({str(secret)!r}).exists()
assert "OPENAI_API_KEY" not in os.environ
p = Path("/inputs/0/data/values.txt")
assert p.read_text() == "42"
try:
    p.write_text("bad")
    raise AssertionError("input was writable")
except OSError:
    pass
s = socket.socket()
s.settimeout(1)
try:
    s.connect(("1.1.1.1", 53))
    raise AssertionError("external network reachable")
except OSError:
    pass
finally:
    s.close()
Path("outputs/result.txt").write_text("42")
'''
    done = subprocess.run(sandbox_command(native_spec, [sys.executable, "-c", code]),
                          capture_output=True, text=True, timeout=15, check=False)
    assert done.returncode == 0, done.stderr
    assert (Path(native_spec["workspace"]) / "outputs/result.txt").read_text() == "42"
    assert (tmp_path / "data/values.txt").read_text() == "42"


def test_native_timeout_removes_detached_descendants(native_spec, tmp_path, monkeypatch):
    native_spec["execution_timeout"] = 1
    descendant = ('import os, time; from pathlib import Path; os.setsid(); '
                  'Path("outputs/child-started").write_text("yes"); '
                  'time.sleep(2); Path("outputs/escaped.txt").write_text("wrong")')
    code = f'''
import subprocess, sys, time
subprocess.Popen([sys.executable, "-c", {descendant!r}])
time.sleep(60)
'''
    monkeypatch.setattr(finch_sandbox, "notebook_command", lambda spec: sandbox_command(
        spec, [sys.executable, "-c", code]))
    with pytest.raises(TimeoutError):
        asyncio.run(execute_notebook(native_spec, tmp_path / "timeout.log"))
    workspace = Path(native_spec["workspace"])
    assert (workspace / "outputs/child-started").is_file()
    time.sleep(2.1)
    assert not (workspace / "outputs/escaped.txt").exists()


if __name__ == "__main__":
    print(json.dumps(kernel_check()))
