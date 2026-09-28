"""Job lifecycle states and transition rules."""

from enum import StrEnum


class JobStatus(StrEnum):
    """The state of one Job."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 状态机转移表
_ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}),
}


def transition_status(current: JobStatus, target: JobStatus) -> JobStatus:
    """Return a legal next state, or reject an invalid transition."""
    if not isinstance(current, JobStatus) or not isinstance(target, JobStatus):
        raise TypeError("Job status transitions require JobStatus values")
    if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"Cannot transition Job status from {current} to {target}")
    return target
