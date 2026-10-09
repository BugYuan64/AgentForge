"""M10 report commands expose persisted summaries with honest outcome exit codes."""

import importlib
import json
from pathlib import Path

import pytest

from agentforge.workspace_management.manager import WorkspaceError, WorkspaceManager


def load_cli():
    try:
        return importlib.import_module("agentforge.reporting.cli")
    except ModuleNotFoundError as exc:
        pytest.fail(f"M10 report CLI is missing: {exc}")


@pytest.fixture
def configuration(tmp_path: Path) -> tuple[list[str], Path, Path]:
    source = tmp_path / "source"
    root = tmp_path / "workspaces"
    commit_file = tmp_path / "baseline.commit"
    commit_file.write_text("a" * 40 + "\n", encoding="utf-8")
    options = ["--source", str(source), "--root", str(root), "--commit-file", str(commit_file)]
    return options, source, root


@pytest.mark.parametrize(
    ("command", "state", "expected_exit"),
    [
        ("build", "passed", 0),
        ("show", "passed", 0),
        ("build", "existing_failure", 1),
        ("show", "new_failure", 1),
        ("build", "environment_error", 2),
        ("show", "rejected", 2),
        ("build", "stale", 2),
        ("show", "recorded", 2),
        ("build", "unknown", 2),
    ],
)
def test_commands_forward_configuration_and_report_json_with_outcome_exit(
    configuration,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    state: str,
    expected_exit: int,
) -> None:
    cli = load_cli()
    options, source, root = configuration
    workspace_id = "b" * 32

    class FakeService:
        def __init__(self, manager: WorkspaceManager) -> None:
            assert manager.source_repository == source
            assert manager.workspaces_directory == root
            assert manager.baseline_commit == "a" * 40

        def result(self, operation: str, requested_id: str) -> dict[str, object]:
            assert operation == command
            assert requested_id == workspace_id
            return {"workspace_id": requested_id, "state": state, "summary": "检查结果"}

        def build(self, requested_id: str) -> dict[str, object]:
            return self.result("build", requested_id)

        def show(self, requested_id: str) -> dict[str, object]:
            return self.result("show", requested_id)

    monkeypatch.setattr(cli, "ReportingService", FakeService)

    assert cli.main([*options, command, workspace_id]) == expected_exit
    captured = capsys.readouterr()
    assert not captured.err
    assert "检查结果" in captured.out
    assert json.loads(captured.out) == {
        "workspace_id": workspace_id,
        "state": state,
        "summary": "检查结果",
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
            assert manager.source_repository == tmp_path / ".local" / "todo_baseline"
            assert manager.workspaces_directory == tmp_path / ".local" / "workspaces"
            assert manager.baseline_commit == "c" * 40

        def show(self, requested_id: str) -> dict[str, object]:
            return {"workspace_id": requested_id, "state": "passed"}

    monkeypatch.setattr(cli, "ReportingService", FakeService)

    assert cli.main(["show", "d" * 32]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out) == {"workspace_id": "d" * 32, "state": "passed"}


@pytest.mark.parametrize("option", ["--image", "--check", "--runtime"])
def test_commands_reject_execution_overrides(
    configuration,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    option: str,
) -> None:
    cli = load_cli()
    options, _, _ = configuration

    def forbidden_service(*args, **kwargs):
        pytest.fail("execution overrides must be rejected before creating the report service")

    monkeypatch.setattr(cli, "ReportingService", forbidden_service)

    with pytest.raises(SystemExit) as exc:
        cli.main([*options, "build", "e" * 32, option, "agent-selected"])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "unrecognized arguments" in captured.err


@pytest.mark.parametrize(
    "error",
    [
        WorkspaceError("workspace invalid"),
        KeyError("unknown workspace"),
        ValueError("invalid record"),
        OSError("record unavailable"),
    ],
)
def test_service_errors_return_exit_two_without_a_json_payload(
    configuration,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    cli = load_cli()
    options, _, _ = configuration

    class FakeService:
        def __init__(self, manager: WorkspaceManager) -> None:
            pass

        def build(self, requested_id: str) -> dict[str, object]:
            raise error

    monkeypatch.setattr(cli, "ReportingService", FakeService)

    assert cli.main([*options, "build", "f" * 32]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "error:" in captured.err
    assert str(error) in captured.err


def test_missing_commit_file_reports_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = load_cli()
    missing = tmp_path / "missing.commit"

    assert cli.main(["--commit-file", str(missing), "show", "f" * 32]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "error:" in captured.err
    assert "missing.commit" in captured.err
