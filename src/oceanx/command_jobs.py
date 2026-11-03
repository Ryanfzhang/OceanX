"""Commands of the single agent and its helpers that go on after the agent stops waiting.

An agent's command runs until it ends (expert_execution.py), and the single agent's time rules act
between its model calls (research/routing.py). On 2026-11-03 a command that ran for an hour by accident
held the agent past them with nothing to see. So for the single agent and its helpers, execute waits at
most JOB_WAIT_SECONDS: a command still running then goes on as a job, and the agent gets what it printed
so far. check_job waits for a job again, as long at most, and shows what it printed since; stop_job stops
it. Nothing stops a job for its age: it ends by itself, by stop_job, by the researcher's stop
(research/graphs.py) or when the backend closes. The team's commands wait until they end.
"""
from __future__ import annotations

import asyncio
import codecs
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

JOB_WAIT_SECONDS = 600
# What is kept of the output its agent has not seen; the run's logs keep all of it.
JOB_OUTPUT_CHARS = 12_000


@dataclass(eq=False)
class CommandJob:
    """One command of a task; ``run`` is its execution (ExpertCodeExecutionService.run_shell)."""

    task_id: str
    command: str
    job_id: str = field(default_factory=lambda: uuid4().hex[:6])
    started: float = field(default_factory=time.monotonic)
    ended: float | None = None
    run: asyncio.Future[Any] | None = None
    unread: str = ""
    dropped: int = 0
    decoders: dict[str, codecs.IncrementalDecoder] = field(default_factory=dict)

    def add_output(self, stream: str, chunk: bytes) -> None:
        if stream not in self.decoders:  # a character may be split between two pieces
            self.decoders[stream] = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.unread += self.decoders[stream].decode(chunk)
        if len(self.unread) > JOB_OUTPUT_CHARS:
            self.dropped += len(self.unread) - JOB_OUTPUT_CHARS
            self.unread = self.unread[-JOB_OUTPUT_CHARS:]

    def take_output(self) -> str:
        """What the command printed since its agent last looked."""
        if self.run is not None and self.run.done():
            for decoder in self.decoders.values():
                self.unread += decoder.decode(b"", final=True)
        text = (f"[{self.dropped} earlier characters left out]\n" if self.dropped else "") + self.unread
        self.unread, self.dropped = "", 0
        return text

    @property
    def minutes(self) -> int:
        return int(((self.ended or time.monotonic()) - self.started) / 60)


def command_notes(result: Any, budget_note: Callable[[str | None], str | None]) -> str:
    """What ends a command's output: the checks of the PDF figures it saved and the research budget's stop."""
    notes = ""
    if result.figure_notes:  # what keeps a saved PDF figure from being edited in Illustrator
        notes += "\n[Figure check] " + "\n[Figure check] ".join(result.figure_notes) + "\n"
    if note := budget_note(result.limit_trigger):
        notes += f"\n[{note}]\n"
    return notes


def job_started(job: CommandJob) -> str:
    """The end of execute's reply when its command goes on as ``job``."""
    return (f"\n[Still running after {job.minutes} minutes, so the command goes on as job {job.job_id}; the "
            "files it writes appear as it writes them. Do not start it again while it runs. check_job waits "
            f"for it, up to {JOB_WAIT_SECONDS // 60} minutes at a time, and shows what it printed since; "
            "stop_job stops it. Meanwhile you can do work that does not need its results.]")


class CommandJobs:
    """The jobs of one backend, by id. A job's end is shown to its task's agents once."""

    def __init__(self) -> None:
        self.jobs: dict[str, CommandJob] = {}

    async def run(self, job: CommandJob, execution: Awaitable[Any], wait: float) -> Any | None:
        """The result of ``execution`` if it ends within ``wait`` seconds; otherwise None, and it goes
        on as ``job``. A stop of the request while it waits stops it."""
        job.run = asyncio.ensure_future(execution)
        try:
            await asyncio.wait({job.run}, timeout=wait)
        except asyncio.CancelledError:
            job.run.cancel()
            await asyncio.gather(job.run, return_exceptions=True)
            raise
        if job.run.done():
            return job.run.result()
        job.run.add_done_callback(lambda _run: setattr(job, "ended", time.monotonic()))
        self.jobs[job.job_id] = job
        return None

    def get(self, task_id: str, job_id: str) -> CommandJob | None:
        job = self.jobs.get(job_id.strip())
        return job if job is not None and job.task_id == task_id else None

    async def wait(self, job: CommandJob, seconds: float) -> None:
        """Wait for ``job`` to end, at most ``seconds``; waiting never stops it."""
        if seconds > 0 and job.run is not None and not job.run.done():
            await asyncio.wait({job.run}, timeout=seconds)

    async def stop(self, job: CommandJob) -> None:
        """Stop ``job``'s command and every process it started."""
        if job.run is not None and not job.run.done():
            job.run.cancel()
            await asyncio.gather(job.run, return_exceptions=True)

    async def stop_task(self, task_id: str) -> None:
        for job in [job for job in self.jobs.values() if job.task_id == task_id]:
            await self.stop(job)

    async def stop_all(self) -> None:
        for job in list(self.jobs.values()):
            await self.stop(job)

    def report(self, job: CommandJob, budget_note: Callable[[str | None], str | None]) -> str:
        """What ``job`` printed since its agent last looked, and whether it has ended."""
        assert job.run is not None
        if not job.run.done():
            return f"{job.take_output()}\n[Job {job.job_id} is still running after {job.minutes} minutes.]"
        self.jobs.pop(job.job_id, None)
        output = job.take_output()
        if job.run.cancelled():
            return f"{output}\n[Job {job.job_id} was stopped after {job.minutes} minutes.]"
        if (error := job.run.exception()) is not None:
            return f"{output}\n[Job {job.job_id} could not run to its end: {error}]"
        result = job.run.result()
        status = "succeeded" if result.returncode == 0 else "failed"
        return (output + command_notes(result, budget_note) + f"\n[Job {job.job_id}: the command {status} "
                f"with exit code {result.returncode} after {job.minutes} minutes.]")

    def listing(self, task_id: str) -> str:
        jobs = [job for job in self.jobs.values() if job.task_id == task_id]
        if not jobs:
            return "No command of this task is running as a job, and no job has ended unchecked."
        lines = [f"- {job.job_id}, " + ("ended, not checked yet" if job.run is not None and job.run.done()
                                        else f"running for {job.minutes} minutes")
                 + ": " + (job.command.strip().splitlines() or [""])[0][:120] for job in jobs]
        return "Jobs of this task:\n" + "\n".join(lines)


__all__ = ["JOB_OUTPUT_CHARS", "JOB_WAIT_SECONDS", "CommandJob", "CommandJobs", "command_notes", "job_started"]
