"""Job storage contract and its in-memory implementation."""

from dataclasses import replace
from typing import Protocol

from agentforge.domain.job import Job
from agentforge.domain.job_status import JobStatus, transition_status


class JobRepository(Protocol):
    """Operations needed to keep and retrieve Jobs."""

    def create(self, job: Job) -> None: ...

    def get(self, job_id: str) -> Job: ...

    def update_status(self, job_id: str, target: JobStatus) -> Job: ...


class InMemoryJobRepository:
    """Keep Jobs in one process for local learning and tests."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, job: Job) -> None:
        if job.id in self._jobs:
            raise ValueError(f"Job {job.id!r} already exists")
        self._jobs[job.id] = job

    def get(self, job_id: str) -> Job:
        return self._jobs[job_id]

    def update_status(self, job_id: str, target: JobStatus) -> Job:
        current = self.get(job_id)
        updated = replace(current, status=transition_status(current.status, target))
        self._jobs[job_id] = updated
        return updated
