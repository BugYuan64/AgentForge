"""Exercise M8's preset patch and fixed tests on a real Docker candidate."""

import json
from pathlib import Path

from test_container_execution import _docker, _source_snapshot

from agentforge.workspace_management.manager import (
    WorkspaceManager,
    WorkspaceRecord,
    WorkspaceState,
)
from agentforge.workspace_tools.contracts import ToolRequest, ToolStatus
from agentforge.workspace_tools.service import WorkspaceTools

PROJECT_ROOT = Path(__file__).resolve().parents[2]
pytest_plugins = ("test_container_execution",)


def test_preset_patch_diff_and_container_tests_preserve_source_and_cleanup(
    workspace: tuple[WorkspaceManager, WorkspaceRecord],
) -> None:
    manager, record = workspace
    tools = WorkspaceTools(manager)
    before = _source_snapshot(manager.source_repository)
    target = record.path / "todo_app" / "main.py"
    original = target.read_bytes()
    test_file = record.path / "tests" / "test_todos.py"
    original_tests = test_file.read_bytes()
    patch = (PROJECT_ROOT / "examples" / "todo_fix.patch").read_bytes().decode("utf-8")
    try:
        baseline = tools.execute(ToolRequest("run_tests", record.id))
        assert baseline.status is ToolStatus.COMPLETED
        assert baseline.details["exit_code"] == 1
        assert "4 passed" in baseline.output and "1 failed" in baseline.output

        applied = tools.execute(ToolRequest("apply_patch", record.id, patch=patch))
        assert applied.status is ToolStatus.COMPLETED, applied.error
        assert applied.details["changed_paths"] == ["todo_app/main.py"]
        status = tools.execute(ToolRequest("status", record.id))
        assert status.status is ToolStatus.COMPLETED
        assert "todo_app/main.py" in status.output
        diff = tools.execute(ToolRequest("diff", record.id))
        assert diff.status is ToolStatus.COMPLETED
        assert "+            raise HTTPException(status_code=404" in diff.output
        candidate = tools.execute(ToolRequest("run_tests", record.id))
        assert candidate.status is ToolStatus.COMPLETED
        assert candidate.details["exit_code"] == 0
        assert "5 passed" in candidate.output
        assert candidate.details["image_id"] == baseline.details["image_id"]
        assert Path(candidate.details["log_path"]).is_file()
        assert _source_snapshot(manager.source_repository) == before
        assert test_file.read_bytes() == original_tests
        containers = _docker("ps", "--all", "--format", "{{.Names}}")
        assert containers.returncode == 0, containers.stderr
        assert f"agentforge-m6-{candidate.details['run_id']}" not in containers.stdout.splitlines()
    finally:
        target.write_bytes(original)
        manager.remove(record.id)
    assert not record.path.exists()
    assert manager.get(record.id).state is WorkspaceState.REMOVED
    json.dumps(candidate.to_dict())
