"""The M7 CLI exposes bounded read-only operations on an M5 workspace."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from scripts.create_todo_baseline import create_baseline

from agentforge.workspace_management.manager import WorkspaceManager, WorkspaceRecord

FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "todo_fixture"


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[tuple[list[str], WorkspaceManager, WorkspaceRecord]]:
    source = tmp_path / "source"
    root = tmp_path / "workspaces"
    commit_file = tmp_path / "baseline.commit"
    commit = create_baseline(FIXTURE, source)
    commit_file.write_text(commit + "\n", encoding="utf-8")
    manager = WorkspaceManager(source, root, commit)
    record = manager.create()
    options = ["--source", str(source), "--root", str(root), "--commit-file", str(commit_file)]
    yield options, manager, record
    manager.remove(record.id)


@pytest.mark.parametrize(
    ("arguments", "tool", "path", "expected"),
    [
        (["list-files"], "list_files", ".", "todo_app/main.py"),
        (["read-file", "todo_app/main.py"], "read_file", "todo_app/main.py", "FastAPI"),
        (["search", "FastAPI", "todo_app"], "search", "todo_app", "todo_app/main.py"),
    ],
)
def test_cli_returns_json_for_each_read_operation(
    workspace: tuple[list[str], WorkspaceManager, WorkspaceRecord],
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    tool: str,
    path: str,
    expected: str,
) -> None:
    from agentforge.workspace_tools.cli import main

    options, manager, record = workspace
    command, *operands = arguments
    assert main([*options, command, record.id, *operands]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["tool"] == tool
    assert result["workspace_id"] == record.id
    assert result["path"] == path
    assert result["status"] == "completed"
    assert expected in result["output"]
    assert not captured.err
    assert not manager.get(record.id).has_changes


def test_cli_rejected_path_returns_json_and_exit_two(
    workspace: tuple[list[str], WorkspaceManager, WorkspaceRecord],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agentforge.workspace_tools.cli import main

    options, _, record = workspace
    assert main([*options, "read-file", record.id, "../outside.txt"]) == 2
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "rejected"
    assert result["error"]
    assert result["output"] == ""
    assert not captured.err


def test_cli_unknown_workspace_returns_error_result(
    workspace: tuple[list[str], WorkspaceManager, WorkspaceRecord],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agentforge.workspace_tools.cli import main

    options, _, _ = workspace
    assert main([*options, "list-files", "f" * 32]) == 2
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] in {"rejected", "error"}
    assert result["error"]
    assert not captured.err


def test_cli_missing_commit_file_reports_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from agentforge.workspace_tools.cli import main

    assert main(["--commit-file", str(tmp_path / "missing"), "list-files", "f" * 32]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "error:" in captured.err


def test_cli_default_paths_use_the_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from agentforge.workspace_tools import cli

    source = tmp_path / ".local" / "todo_baseline"
    root = tmp_path / ".local" / "workspaces"
    commit_file = tmp_path / "examples" / "todo_baseline.commit"
    commit_file.parent.mkdir()
    commit = create_baseline(FIXTURE, source)
    commit_file.write_text(commit + "\n", encoding="utf-8")
    manager = WorkspaceManager(source, root, commit)
    record = manager.create()
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    try:
        assert cli.main(["search", record.id, "FastAPI"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["path"] == "."
        assert "todo_app/main.py" in result["output"]
    finally:
        manager.remove(record.id)
