from agentforge.domain.job import Job
from agentforge.domain.job_status import JobStatus


def test_new_job_keeps_identity_goal_and_starts_pending() -> None:
    job = Job(id="job-1", goal="修复登录失败")

    assert job.id == "job-1"
    assert job.goal == "修复登录失败"
    assert job.status is JobStatus.PENDING
