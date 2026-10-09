"""M9 keeps complete authority and candidate provenance through real Docker checks."""

from pathlib import Path

import pytest
from test_container_execution import _docker, _source_snapshot

from agentforge.acceptance.service import AcceptanceService
from agentforge.workspace_management.manager import (
    WorkspaceManager,
    WorkspaceRecord,
    WorkspaceState,
)
from agentforge.workspace_tools.contracts import ToolRequest, ToolStatus
from agentforge.workspace_tools.service import WorkspaceTools

PROJECT_ROOT = Path(__file__).resolve().parents[2]
pytest_plugins = ("test_container_execution",)


def test_real_acceptance_preserves_authority_and_compares_the_bound_candidate(
    workspace: tuple[WorkspaceManager, WorkspaceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, record = workspace
    service = AcceptanceService(manager)
    tools = WorkspaceTools(manager)
    before = _source_snapshot(manager.source_repository)
    main_file = record.path / "todo_app" / "main.py"
    test_file = record.path / "tests" / "test_todos.py"
    original_main = main_file.read_bytes()
    original_tests = test_file.read_bytes()
    missing_test = "test_get_missing_todo_returns_404"
    run_ids: list[str] = []

    def execution(report: dict) -> dict:
        run = report["execution"]
        assert run["state"] == "completed", run["error"]
        assert run["error"] is None
        assert Path(run["log_path"]).is_file()
        assert Path(run["xml_path"]).is_file()
        assert Path(report["report_path"]).is_file()
        assert set(run["outcomes"]) == {
            "test_post_creates_todo",
            "test_get_existing_todo",
            "test_new_app_starts_empty",
            "test_non_integer_id_is_rejected",
            missing_test,
        }
        run_ids.append(run["run_id"])
        return run

    try:
        baseline = service.baseline(record.id)
        assert baseline["state"] == "recorded", baseline["error"]
        baseline_run = execution(baseline)
        assert baseline_run["exit_code"] == 1
        assert baseline_run["outcomes"][missing_test] == "failed"
        assert list(baseline_run["outcomes"].values()).count("passed") == 4
        assert baseline["existing_failures"] == [missing_test]
        assert baseline["head"] == manager.baseline_commit

        unchanged = service.verify(record.id)
        assert unchanged["state"] == "existing_failure", unchanged["error"]
        unchanged_run = execution(unchanged)
        assert unchanged_run["exit_code"] == 1
        assert unchanged["existing_failures"] == [missing_test]
        assert unchanged["new_failures"] == []
        assert unchanged["candidate_digest"] == baseline["candidate_digest"]
        assert unchanged["baseline_id"] == baseline["report_id"]
        assert unchanged_run["image_id"] == baseline_run["image_id"]

        patch = (PROJECT_ROOT / "examples" / "todo_fix.patch").read_bytes().decode("utf-8")
        applied = tools.execute(ToolRequest("apply_patch", record.id, patch=patch))
        assert applied.status is ToolStatus.COMPLETED, applied.error
        assert applied.details["changed_paths"] == ["todo_app/main.py"]
        assert test_file.read_bytes() == original_tests

        fixed = service.verify(record.id)
        assert fixed["state"] == "passed", fixed["error"]
        fixed_run = execution(fixed)
        assert fixed_run["exit_code"] == 0
        assert set(fixed_run["outcomes"].values()) == {"passed"}
        assert fixed["existing_failures"] == []
        assert fixed["new_failures"] == []
        assert fixed["fixed_failures"] == [missing_test]
        assert fixed["baseline_id"] == baseline["report_id"]
        assert fixed_run["image_id"] == baseline_run["image_id"]
        assert fixed["policy_digest"] == baseline["policy_digest"]
        assert fixed["candidate_digest"] != baseline["candidate_digest"]
        assert _source_snapshot(manager.source_repository) == before

        fixed_main = main_file.read_bytes()
        assert fixed_main.count(b"status_code=201") == 1
        main_file.write_bytes(fixed_main.replace(b"status_code=201", b"status_code=202"))
        stale = service.show(record.id)
        assert stale["state"] == "stale"
        assert stale["recorded_state"] == "passed"
        assert stale["valid_for_current_candidate"] is False
        assert stale["candidate_digest"] == fixed["candidate_digest"]
        assert stale["report_id"] == fixed["report_id"]

        regression = service.verify(record.id)
        assert regression["state"] == "new_failure", regression["error"]
        regression_run = execution(regression)
        assert regression_run["exit_code"] == 1
        assert regression["existing_failures"] == []
        assert regression["new_failures"] == ["test_post_creates_todo"]
        assert regression["fixed_failures"] == [missing_test]
        assert regression["baseline_id"] == baseline["report_id"]
        assert regression_run["image_id"] == baseline_run["image_id"]

        test_file.write_bytes(original_tests + b"\n# authority change must be rejected\n")

        def forbidden_run(*args, **kwargs):
            pytest.fail("authority changes must be rejected before Docker execution")

        monkeypatch.setattr(service.runner, "run", forbidden_run)
        rejected = service.verify(record.id)
        assert rejected["state"] == "rejected"
        assert rejected["error"]
        assert rejected["execution"] is None
        assert _source_snapshot(manager.source_repository) == before
    finally:
        main_file.write_bytes(original_main)
        test_file.write_bytes(original_tests)
        manager.remove(record.id)

    assert manager.get(record.id).state is WorkspaceState.REMOVED
    assert not record.path.exists()
    assert _source_snapshot(manager.source_repository) == before
    containers = _docker("ps", "--all", "--format", "{{.Names}}")
    assert containers.returncode == 0, containers.stderr
    remaining = containers.stdout.splitlines()
    assert all(f"agentforge-m6-{run_id}" not in remaining for run_id in run_ids)
