import pytest

from agentforge.domain.job_status import JobStatus, transition_status


def test_job_status_uses_stable_string_values() -> None:
    assert {status.value for status in JobStatus} == {
        "pending",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    }
    assert all(isinstance(status, str) for status in JobStatus)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("pending", "running"),
        ("pending", "cancelled"),
        ("running", "succeeded"),
        ("running", "failed"),
        ("running", "cancelled"),
    ],
)
def test_transition_status_accepts_legal_changes(current: str, target: str) -> None:
    next_status = JobStatus(target)
    assert transition_status(JobStatus(current), next_status) is next_status


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("pending", "pending"),
        ("pending", "succeeded"),
        ("pending", "failed"),
        ("running", "pending"),
        ("running", "running"),
        ("succeeded", "pending"),
        ("succeeded", "running"),
        ("succeeded", "succeeded"),
        ("succeeded", "failed"),
        ("succeeded", "cancelled"),
        ("failed", "pending"),
        ("failed", "running"),
        ("failed", "succeeded"),
        ("failed", "failed"),
        ("failed", "cancelled"),
        ("cancelled", "pending"),
        ("cancelled", "running"),
        ("cancelled", "succeeded"),
        ("cancelled", "failed"),
        ("cancelled", "cancelled"),
    ],
)
def test_transition_status_rejects_all_other_changes(current: str, target: str) -> None:
    with pytest.raises(ValueError):
        transition_status(JobStatus(current), JobStatus(target))


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("pending", JobStatus.RUNNING),
        (JobStatus.PENDING, "running"),
    ],
)
def test_transition_status_requires_job_status_values(current: object, target: object) -> None:
    with pytest.raises(TypeError):
        transition_status(current, target)
