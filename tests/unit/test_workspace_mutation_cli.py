"""M8 CLI routes safe patches, Git views and predetermined tests."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from scripts.create_todo_baseline import create_baseline

from agentforge.workspace_management.manager import WorkspaceManager, WorkspaceRecord

FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "todo_fixture"
PATCH = (
    "diff --git a/todo_app/main.py b/todo_app/main.py\n"
    "--- a/todo_app/main.py\n"
    "+++ b/todo_app/main.py\n"
    "@@ -1,4 +1,4 @@\n"
    '-"""In-memory Todo HTTP API for the fixed M4 baseline."""\n'
    '+"""Candidate Todo HTTP API."""\n'
    " \n"
    " from fastapi import FastAPI\n"
    " from pydantic import BaseModel\n"
)


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[tuple[list[str], WorkspaceManager, WorkspaceRecord]]:
    source = tmp_path / "source"
    root = tmp_path / "workspaces"
    commit_file = tmp_path / "baseline.commit"
    commit = create_baseline(FIXTURE, source)
    commit_file.write_text(commit + "\n", encoding="utf-8")
    manager = WorkspaceManager(source, root, commit)
    record = manager.create()
    main_file = record.path / "todo_app" / "main.py"
    original = main_file.read_bytes()
    options = ["--source", str(source), "--root", str(root), "--commit-file", str(commit_file)]
    try:
        yield options, manager, record
    finally:
        main_file.write_bytes(original)
        manager.remove(record.id)


def test_cli_applies_patch_and_reports_status_and_diff(
    workspace: tuple[list[str], WorkspaceManager, WorkspaceRecord],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agentforge.workspace_tools.cli import main

    options, manager, record = workspace
    patch_file = tmp_path / "candidate.patch"
    original = (record.path / "todo_app" / "main.py").read_bytes()
    newline = "\r\n" if b"\r\n" in original else "\n"
    patch_file.write_bytes(PATCH.replace("\n", newline).encode("utf-8"))
    assert main([*options, "apply-patch", record.id, str(patch_file)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["tool"] == "apply_patch"
    assert result["status"] == "completed"
    assert manager.get(record.id).has_changes
    assert (manager.source_repository / "todo_app" / "main.py").read_bytes() == (
        FIXTURE / "todo_app" / "main.py"
    ).read_bytes()

    assert main([*options, "status", record.id]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["tool"] == "status"
    assert "todo_app/main.py" in status["output"]

    assert main([*options, "diff", record.id]) == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["tool"] == "diff"
    assert '+"""Candidate Todo HTTP API."""' in diff["output"]


def test_cli_rejects_patch_outside_default_write_policy(
    workspace: tuple[list[str], WorkspaceManager, WorkspaceRecord],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agentforge.workspace_tools.cli import main

    options, manager, record = workspace
    patch_file = tmp_path / "forbidden.patch"
    patch_file.write_text(
        "--- a/tests/test_todos.py\n+++ b/tests/test_todos.py\n"
        "@@ -1,1 +1,1 @@\n-previous\n+replacement\n",
        encoding="utf-8",
    )
    assert main([*options, "apply-patch", record.id, str(patch_file)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "rejected"
    assert result["error"]
    assert not manager.get(record.id).has_changes


@pytest.mark.parametrize(
    "invalid_patch", [b"x" * (256 * 1024 + 1), b"\xff"], ids=["oversized", "invalid-utf8"]
)
def test_cli_rejects_oversized_or_invalid_utf8_patch_before_writing(
    workspace: tuple[list[str], WorkspaceManager, WorkspaceRecord],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    invalid_patch: bytes,
) -> None:
    from agentforge.workspace_tools import cli

    options, manager, record = workspace
    patch_file = tmp_path / "invalid.patch"
    patch_file.write_bytes(invalid_patch)

    def forbidden_service(manager: WorkspaceManager) -> None:
        pytest.fail("invalid patch must fail before constructing workspace tools")

    monkeypatch.setattr(cli, "WorkspaceTools", forbidden_service)
    assert cli.main([*options, "apply-patch", record.id, str(patch_file)]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "error:" in captured.err
    assert not manager.get(record.id).has_changes


@pytest.mark.parametrize(
    ("state", "exit_code", "expected_exit"),
    [
        ("completed", 0, 0),
        ("completed", 1, 1),
        ("completed", 5, 5),
        ("timed_out", None, 124),
        ("infrastructure_error", None, 2),
    ],
)
def test_cli_run_tests_preserves_test_outcome(
    workspace: tuple[list[str], WorkspaceManager, WorkspaceRecord],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state: str,
    exit_code: int | None,
    expected_exit: int,
) -> None:
    from agentforge.workspace_tools import cli
    from agentforge.workspace_tools.contracts import ToolRequest, ToolResult, ToolStatus

    options, _, record = workspace

    class FakeTestService:
        def __init__(self, manager: WorkspaceManager) -> None:
            assert manager.get(record.id).id == record.id

        def execute(self, request: ToolRequest) -> ToolResult:
            assert request.tool == "run_tests"
            assert request.workspace_id == record.id
            assert request.path == "."
            assert request.query is None
            return ToolResult(
                tool="run_tests",
                workspace_id=record.id,
                path=".",
                status=ToolStatus.COMPLETED if state == "completed" else ToolStatus.ERROR,
                details={"state": state, "exit_code": exit_code, "log_path": "test.log"},
            )

    monkeypatch.setattr(cli, "WorkspaceTools", FakeTestService)
    assert cli.main([*options, "run-tests", record.id]) == expected_exit
    result = json.loads(capsys.readouterr().out)
    assert result["details"]["state"] == state
    assert result["details"]["exit_code"] == exit_code


@pytest.mark.parametrize("command", ["status", "diff", "run-tests"])
def test_cli_new_tools_reject_unknown_workspace(
    workspace: tuple[list[str], WorkspaceManager, WorkspaceRecord],
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    from agentforge.workspace_tools.cli import main

    options, _, _ = workspace
    assert main([*options, command, "f" * 32]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] in {"rejected", "error"}
    assert result["error"]
