"""Offline deadline/log tests; no Finch dependencies, model calls or sandbox required."""
import asyncio

import pytest

import finch_sandbox


def test_notebook_timeout_reports_deadline_and_log_tail_and_reaps_process(tmp_path, monkeypatch):
    class Output:
        sent = False

        async def read(self, size):
            if not self.sent:
                self.sent = True
                return b"Starting notebook replay\n"
            await asyncio.sleep(60)

    class Process:
        stdout = Output()
        returncode = None
        killed = False
        waited = False

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            self.waited = True
            return self.returncode

    process = Process()

    async def start(*args, **kwargs):
        return process

    monkeypatch.setattr(finch_sandbox, "notebook_command", lambda spec: ["fake-notebook"])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    log = tmp_path / "execution.log"
    with pytest.raises(TimeoutError, match="0.02 seconds") as caught:
        asyncio.run(finch_sandbox.execute_notebook({"execution_timeout": 0.02}, log))
    assert "full notebook" in str(caught.value)
    assert "execution.log" in str(caught.value)
    assert "Starting notebook replay" in str(caught.value)
    assert log.read_text() == "Starting notebook replay\n"
    assert process.killed and process.waited
