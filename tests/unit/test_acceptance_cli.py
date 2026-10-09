"""M9 CLI keeps host-selected checks fixed and reports acceptance outcomes honestly."""

import importlib
import json
from pathlib import Path

import pytest

from agentforge.workspace_management.manager import WorkspaceError, WorkspaceManager


def load_cli():
    try:
        return importlib.import_module("agentforge.acceptance.cli")
    except ModuleNotFoundError as exc:
        pytest.fail(f"M9 acceptance CLI is missing: {exc}")


@pytest.fixture
def configuration(tmp_path: Path) -> tuple[list[str], Path, Path, Path]:
    source = tmp_path / "source"
    root = tmp_path / "workspaces"
    commit_file = tmp_path / "baseline.commit"
    commit_file.write_text("a" * 40 + "\n", encoding="utf-8")
    options = ["--source", str(source), "--root", str(root), "--commit-file", str(commit_file)]
    return options, source, root, commit_file


@pytest.mark.parametrize("command", ["baseline", "verify", "show"])
@pytest.mark.parametrize(
    ("state", "expected_exit"),
    [
        ("recorded", 0),
        ("passed", 0),
        ("existing_failure", 1),
        ("new_failure", 1),
        ("environment_error", 2),
        ("rejected", 2),
        ("stale", 2),
        ("unknown", 2),
    ],
)
def test_each_command_returns_json_with_its_outcome_exit_code(
    configuration,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    state: str,
    expected_exit: int,
) -> None:
    cli = load_cli()
    options, source, root, _ = configuration
    workspace_id = "b" * 32

    class FakeService:
        def __init__(self, manager: WorkspaceManager) -> None:
            self.manager = manager

        def result(self, operation: str, requested_id: str) -> dict[str, object]:
            return {
                "operation": operation,
                "workspace_id": requested_id,
                "state": state,
                "error": "检查故障" if state == "environment_error" else None,
                "source": str(self.manager.source_repository),
                "root": str(self.manager.workspaces_directory),
                "baseline_commit": self.manager.baseline_commit,
            }

        def baseline(self, requested_id: str) -> dict[str, object]:
            return self.result("baseline", requested_id)

        def verify(self, requested_id: str) -> dict[str, object]:
            return self.result("verify", requested_id)

        def show(self, requested_id: str) -> dict[str, object]:
            return self.result("show", requested_id)

    monkeypatch.setattr(cli, "AcceptanceService", FakeService)

    assert cli.main([*options, command, workspace_id]) == expected_exit
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out) == {
        "operation": command,
        "workspace_id": workspace_id,
        "state": state,
        "error": "检查故障" if state == "environment_error" else None,
        "source": str(source),
        "root": str(root),
        "baseline_commit": "a" * 40,
    }


def test_default_configuration_uses_the_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = load_cli()
    commit_file = tmp_path / "examples" / "todo_baseline.commit"
    commit_file.parent.mkdir()
    commit_file.write_text("c" * 40 + "\n", encoding="utf-8")
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)

    class FakeService:
        def __init__(self, manager: WorkspaceManager) -> None:
            self.manager = manager

        def baseline(self, requested_id: str) -> dict[str, object]:
            return {
                "workspace_id": requested_id,
                "state": "recorded",
                "source": str(self.manager.source_repository),
                "root": str(self.manager.workspaces_directory),
                "baseline_commit": self.manager.baseline_commit,
            }

    monkeypatch.setattr(cli, "AcceptanceService", FakeService)
    assert cli.main(["baseline", "d" * 32]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out) == {
        "workspace_id": "d" * 32,
        "state": "recorded",
        "source": str(tmp_path / ".local" / "todo_baseline"),
        "root": str(tmp_path / ".local" / "workspaces"),
        "baseline_commit": "c" * 40,
    }


@pytest.mark.parametrize("command", ["baseline", "verify", "show"])
@pytest.mark.parametrize(
    "option", ["--image", "--command", "--timeout", "--test", "--timeout-seconds"]
)
def test_commands_reject_agent_selected_execution_options(
    configuration,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    option: str,
) -> None:
    cli = load_cli()
    options, _, _, _ = configuration

    def forbidden_service(*args, **kwargs):
        pytest.fail("invalid execution options must be rejected before the service is created")

    monkeypatch.setattr(cli, "AcceptanceService", forbidden_service)
    with pytest.raises(SystemExit) as exc:
        cli.main([*options, command, "e" * 32, option, "agent-selected"])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "unrecognized arguments" in captured.err


def test_missing_commit_file_reports_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = load_cli()
    missing = tmp_path / "missing.commit"
    assert cli.main(["--commit-file", str(missing), "verify", "f" * 32]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "error:" in captured.err
    assert "missing.commit" in captured.err


@pytest.mark.parametrize("command", ["baseline", "verify", "show"])
@pytest.mark.parametrize(
    "error", [WorkspaceError("workspace invalid"), KeyError("unknown workspace"),
              ValueError("invalid record"), OSError("record unavailable")]
)
def test_service_errors_return_exit_two_without_a_success_payload(
    configuration,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    error: Exception,
) -> None:
    cli = load_cli()
    options, _, _, _ = configuration

    class FakeService:
        def __init__(self, manager: WorkspaceManager) -> None:
            pass

        def fail(self, requested_id: str) -> dict[str, object]:
            raise error

        baseline = fail
        verify = fail
        show = fail

    monkeypatch.setattr(cli, "AcceptanceService", FakeService)
    assert cli.main([*options, command, "f" * 32]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "error:" in captured.err
    assert str(error) in captured.err
