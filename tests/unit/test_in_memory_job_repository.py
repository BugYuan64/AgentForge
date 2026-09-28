import pytest

from agentforge.domain.job import Job
from agentforge.domain.job_status import JobStatus
from agentforge.job_repository import InMemoryJobRepository, JobRepository


def test_get_unknown_job_raises_key_error() -> None:
    repository: JobRepository = InMemoryJobRepository()

    with pytest.raises(KeyError):
        repository.get("missing")


def test_create_stores_jobs_under_their_own_ids() -> None:
    repository: JobRepository = InMemoryJobRepository()
    first = Job(id="job-1", goal="修复登录失败")
    second = Job(id="job-2", goal="补充注册测试")

    repository.create(first)
    repository.create(second)

    assert repository.get("job-1") == first
    assert repository.get("job-2") == second


def test_create_rejects_duplicate_id_without_overwriting() -> None:
    repository: JobRepository = InMemoryJobRepository()
    original = Job(id="job-1", goal="原始目标")
    repository.create(original)

    with pytest.raises(ValueError):
        repository.create(Job(id="job-1", goal="错误覆盖"))

    assert repository.get("job-1") == original


def test_update_status_saves_new_job_without_mutating_original() -> None:
    repository: JobRepository = InMemoryJobRepository()
    original = Job(id="job-1", goal="修复登录失败")
    repository.create(original)

    updated = repository.update_status("job-1", JobStatus.RUNNING)

    assert updated == Job(id="job-1", goal="修复登录失败", status=JobStatus.RUNNING)
    assert repository.get("job-1") == updated
    assert original.status is JobStatus.PENDING


def test_update_status_rejects_invalid_transition_without_changing_job() -> None:
    repository: JobRepository = InMemoryJobRepository()
    original = Job(id="job-1", goal="修复登录失败")
    repository.create(original)

    with pytest.raises(ValueError):
        repository.update_status("job-1", JobStatus.SUCCEEDED)

    assert repository.get("job-1") == original


def test_update_status_of_unknown_job_raises_key_error() -> None:
    repository: JobRepository = InMemoryJobRepository()

    with pytest.raises(KeyError):
        repository.update_status("missing", JobStatus.RUNNING)
