"""Application use cases for Jobs."""

from agentforge.job_management.model import Job
from agentforge.job_management.repository import JobRepository
from agentforge.job_management.status import JobStatus


class JobService:
    """Coordinate Job operations through a repository."""

    def __init__(self, repository: JobRepository) -> None:
        self._repository = repository

    def create(self, job_id: str, goal: str) -> Job:
        job = Job(id=job_id, goal=goal)
        self._repository.create(job)
        return job

    def get(self, job_id: str) -> Job:
        return self._repository.get(job_id)

    def cancel(self, job_id: str) -> Job:
        return self._repository.update_status(job_id, JobStatus.CANCELLED)

    def run_fake(self, job_id: str) -> Job:
        """Simulate a successful execution without running external work."""
        self._repository.update_status(job_id, JobStatus.RUNNING)
        return self._repository.update_status(job_id, JobStatus.SUCCEEDED)
