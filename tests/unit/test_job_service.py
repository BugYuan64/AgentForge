import pytest

from agentforge.domain.job_status import JobStatus
from agentforge.job_repository import InMemoryJobRepository
from agentforge.job_service import JobService


def test_create_job_can_be_queried_in_the_same_process() -> None:
    service = JobService(InMemoryJobRepository())

    created = service.create("job-1", "修复登录失败")

    assert created.id == "job-1"
    assert created.goal == "修复登录失败"
    assert created.status is JobStatus.PENDING
    assert service.get("job-1") == created


def test_cancel_pending_job_updates_stored_state() -> None:
    service = JobService(InMemoryJobRepository())
    service.create("job-1", "修复登录失败")

    cancelled = service.cancel("job-1")

    assert cancelled.status is JobStatus.CANCELLED
    assert service.get("job-1") == cancelled


def test_cancel_terminal_job_is_rejected_without_changing_it() -> None:
    repository = InMemoryJobRepository()
    service = JobService(repository)
    service.create("job-1", "修复登录失败")
    repository.update_status("job-1", JobStatus.RUNNING)
    completed = repository.update_status("job-1", JobStatus.SUCCEEDED)

    with pytest.raises(ValueError):
        service.cancel("job-1")

    assert service.get("job-1") == completed


def test_run_fake_moves_pending_job_to_success() -> None:
    service = JobService(InMemoryJobRepository())
    service.create("job-1", "修复登录失败")

    completed = service.run_fake("job-1")

    assert completed.status is JobStatus.SUCCEEDED
    assert service.get("job-1") == completed


def test_run_fake_cannot_restart_cancelled_job() -> None:
    service = JobService(InMemoryJobRepository())
    service.create("job-1", "修复登录失败")
    cancelled = service.cancel("job-1")

    with pytest.raises(ValueError):
        service.run_fake("job-1")

    assert service.get("job-1") == cancelled
