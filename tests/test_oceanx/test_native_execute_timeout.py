"""The native execute tool tells the model when a command was stopped at the time limit."""
import asyncio
from types import SimpleNamespace

from oceanx.native_backend import ResearchSandbox


def _sandbox(tmp_path, state):
    async def record_command(command, timeout):
        del command, timeout
        return SimpleNamespace(stdout="partial\n", stderr="", returncode=-15, state=state,
                               duration_seconds=300.4)
    return ResearchSandbox(service=SimpleNamespace(), work_root=tmp_path, read_roots=lambda: (),
                           record_command=record_command)


def test_timed_out_command_says_why_it_stopped(tmp_path):
    response = asyncio.run(_sandbox(tmp_path, "timed_out").aexecute("python slow.py", timeout=1800))
    assert response.output.startswith("partial\n")
    assert "Stopped at the time limit after 300 s" in response.output
    assert response.exit_code == -15


def test_other_failures_keep_their_output_unchanged(tmp_path):
    response = asyncio.run(_sandbox(tmp_path, "failed").aexecute("false"))
    assert response.output == "partial\n"
