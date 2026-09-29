"""The minimal data carried by a Job."""

from dataclasses import dataclass

from agentforge.job_management.status import JobStatus


@dataclass(frozen=True, slots=True)
class Job:
    """A task request and its current lifecycle state."""

    id: str
    goal: str
    status: JobStatus = JobStatus.PENDING
