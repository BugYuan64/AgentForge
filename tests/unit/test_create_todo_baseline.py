"""The fixture generator must not touch the AgentForge repository."""

import subprocess
from pathlib import Path

import pytest

FIXTURE_TEMPLATE = Path(__file__).resolve().parents[2] / "examples" / "todo_fixture"


def git_output(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_create_baseline_is_reproducible_and_independent(tmp_path: Path) -> None:
    from scripts.create_todo_baseline import create_baseline

    first = tmp_path / "first"
    second = tmp_path / "second"

    first_commit = create_baseline(FIXTURE_TEMPLATE, first)
    second_commit = create_baseline(FIXTURE_TEMPLATE, second)

    assert not (FIXTURE_TEMPLATE / ".git").exists()
    assert len(first_commit) == 40
    assert first_commit == second_commit
    for repository in (first, second):
        assert Path(git_output(repository, "rev-parse", "--show-toplevel")).resolve() == repository
        assert git_output(repository, "rev-parse", "HEAD") == first_commit
        assert git_output(repository, "status", "--porcelain") == ""
        assert (repository / "requirements.lock").is_file()


def test_create_baseline_refuses_existing_destination(tmp_path: Path) -> None:
    from scripts.create_todo_baseline import create_baseline

    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("user content", encoding="utf-8")

    with pytest.raises(FileExistsError):
        create_baseline(FIXTURE_TEMPLATE, destination)

    assert marker.read_text(encoding="utf-8") == "user content"


def test_create_baseline_ignores_inherited_git_hook_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.create_todo_baseline import create_baseline

    expected = create_baseline(FIXTURE_TEMPLATE, tmp_path / "reference")
    hooks = tmp_path / "external-hooks"
    hooks.mkdir()
    hook = hooks / "prepare-commit-msg"
    hook.write_text("#!/bin/sh\nexit 73\n", encoding="utf-8")
    hook.chmod(0o755)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(hooks))

    actual = create_baseline(FIXTURE_TEMPLATE, tmp_path / "with-inherited-config")

    assert actual == expected
