"""The local M5 entry point exposes persistent workspace operations."""

import json
from pathlib import Path

import pytest
from scripts.create_todo_baseline import create_baseline

FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "todo_fixture"


def test_cli_create_show_remove(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from agentforge.workspace_cli import main

    source = tmp_path / "source"
    root = tmp_path / "workspaces"
    commit_file = tmp_path / "baseline.commit"
    commit_file.write_text(create_baseline(FIXTURE, source) + "\n", encoding="utf-8")
    options = ["--source", str(source), "--root", str(root), "--commit-file", str(commit_file)]

    assert main([*options, "create"]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["state"] == "active"
    assert created["baseline_commit"] == commit_file.read_text(encoding="utf-8").strip()

    assert main([*options, "show", created["id"]]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["id"] == created["id"]
    assert not shown["has_changes"]

    assert main([*options, "remove", created["id"]]) == 0
    removed = json.loads(capsys.readouterr().out)
    assert removed["state"] == "removed"
    assert not Path(created["path"]).exists()

    assert main([*options, "show", "f" * 32]) == 2
    assert "unknown workspace id" in capsys.readouterr().err
