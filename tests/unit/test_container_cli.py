"""The M6 CLI reports Docker test outcomes without hiding pytest failures."""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.create_todo_baseline import create_baseline

from agentforge.workspace_management.manager import WorkspaceManager

FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "todo_fixture"


@pytest.fixture
def local_workspace(tmp_path: Path) -> tuple[Path, str]:
    project_root = tmp_path / "project"
    source = project_root / ".local" / "todo_baseline"
    commit = create_baseline(FIXTURE, source)
    commit_file = project_root / "examples" / "todo_baseline.commit"
    commit_file.parent.mkdir(parents=True)
    commit_file.write_text(commit + "\n", encoding="utf-8")
    manager = WorkspaceManager(source, project_root / ".local" / "workspaces", commit)
    workspace = manager.create()
    return project_root, workspace.id


@pytest.mark.parametrize(
    ("state_name", "test_exit_code", "expected_status"),
    [
        ("COMPLETED", 1, 1),
        ("TIMED_OUT", None, 124),
        ("INFRASTRUCTURE_ERROR", None, 2),
    ],
)
def test_cli_reports_runner_result_and_exit_status(
    local_workspace: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state_name: str,
    test_exit_code: int | None,
    expected_status: int,
) -> None:
    try:
        cli = importlib.import_module("agentforge.container_execution.cli")
        runner_module = importlib.import_module("agentforge.container_execution.runner")
    except ModuleNotFoundError as exc:
        pytest.fail(f"M6 container CLI is missing: {exc}")

    project_root, workspace_id = local_workspace
    monkeypatch.setattr(cli, "PROJECT_ROOT", project_root)
    state = getattr(runner_module.RunState, state_name)

    class FakeRunner:
        def __init__(self, manager: WorkspaceManager) -> None:
            assert manager.source_repository == project_root / ".local" / "todo_baseline"
            assert manager.workspaces_directory == project_root / ".local" / "workspaces"
            assert manager.baseline_commit == (
                project_root / "examples" / "todo_baseline.commit"
            ).read_text(encoding="utf-8").strip()

        def run(self, requested_id: str) -> SimpleNamespace:
            assert requested_id == workspace_id
            payload = {
                "workspace_id": requested_id,
                "state": state.value,
                "exit_code": test_exit_code,
            }
            return SimpleNamespace(
                state=state,
                exit_code=test_exit_code,
                to_dict=lambda: payload,
            )

    monkeypatch.setattr(cli, "ContainerTestRunner", FakeRunner)

    assert cli.main(["test", workspace_id]) == expected_status
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {
        "workspace_id": workspace_id,
        "state": state.value,
        "exit_code": test_exit_code,
    }


def test_cli_reports_missing_commit_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    try:
        cli = importlib.import_module("agentforge.container_execution.cli")
    except ModuleNotFoundError as exc:
        pytest.fail(f"M6 container CLI is missing: {exc}")

    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    assert cli.main(["test", "f" * 32]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "todo_baseline.commit" in output.err
