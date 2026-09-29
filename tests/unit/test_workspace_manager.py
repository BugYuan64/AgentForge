"""Git workspaces must preserve both source and candidate changes."""

import json
import subprocess
from pathlib import Path

import pytest
from scripts.create_todo_baseline import create_baseline

FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "todo_fixture"


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, Path, str]:
    source = tmp_path / "source"
    commit = create_baseline(FIXTURE, source)
    return source, tmp_path / "workspaces", commit


def test_create_is_detached_at_fixed_commit_and_record_survives_restart(
    setup: tuple[Path, Path, str],
) -> None:
    from agentforge.workspace_manager import WorkspaceManager, WorkspaceState

    source, root, commit = setup
    manager = WorkspaceManager(source, root, commit)
    record = manager.create()

    assert record.state is WorkspaceState.ACTIVE
    assert record.source_repository == source.resolve()
    assert record.baseline_commit == commit
    assert record.path == root.resolve() / record.id
    assert git(record.path, "rev-parse", "HEAD") == commit
    assert git(record.path, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    assert git(source, "rev-parse", "HEAD") == commit
    assert git(source, "status", "--porcelain", "--untracked-files=all") == ""

    restored = WorkspaceManager(source, root, commit).get(record.id)
    assert restored == record
    assert not restored.has_changes

    target = record.path / "todo_app" / "main.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# candidate\n", encoding="utf-8")
    assert manager.get(record.id).has_changes
    assert git(source, "status", "--porcelain", "--untracked-files=all") == ""


@pytest.mark.parametrize("kind", ["tracked", "untracked", "staged"])
def test_create_rejects_dirty_source(setup: tuple[Path, Path, str], kind: str) -> None:
    from agentforge.workspace_manager import SourceDirtyError, WorkspaceManager

    source, root, commit = setup
    if kind == "untracked":
        (source / "new.txt").write_text("user data", encoding="utf-8")
    else:
        target = source / "todo_app" / "main.py"
        target.write_text(target.read_text(encoding="utf-8") + "\n# user edit\n", encoding="utf-8")
        if kind == "staged":
            git(source, "add", "todo_app/main.py")

    with pytest.raises(SourceDirtyError, match="uncommitted"):
        WorkspaceManager(source, root, commit).create()

    assert not root.exists()


def test_create_rejects_wrong_baseline(setup: tuple[Path, Path, str]) -> None:
    from agentforge.workspace_manager import WorkspaceError, WorkspaceManager

    source, root, _ = setup
    with pytest.raises(WorkspaceError, match="baseline"):
        WorkspaceManager(source, root, "0" * 40).create()
    assert not root.exists()


def test_create_uses_fixed_commit_after_source_head_advances(
    setup: tuple[Path, Path, str],
) -> None:
    from agentforge.workspace_manager import WorkspaceManager

    source, root, commit = setup
    target = source / "todo_app" / "main.py"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n# later source commit\n", encoding="utf-8"
    )
    git(source, "add", "todo_app/main.py")
    subprocess.run(
        ["git", "-C", str(source), "-c", "user.name=Tester", "-c",
         "user.email=test@example.invalid", "commit", "-m", "later source"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert git(source, "rev-parse", "HEAD") != commit

    record = WorkspaceManager(source, root, commit).create()
    assert git(record.path, "rev-parse", "HEAD") == commit
    assert "later source commit" not in (record.path / "todo_app" / "main.py").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("kind", ["tracked", "untracked", "ignored", "staged", "commit"])
def test_remove_preserves_candidate_changes(setup: tuple[Path, Path, str], kind: str) -> None:
    from agentforge.workspace_manager import WorkspaceDirtyError, WorkspaceManager

    source, root, commit = setup
    manager = WorkspaceManager(source, root, commit)
    record = manager.create()
    if kind == "untracked":
        (record.path / "new.txt").write_text("candidate", encoding="utf-8")
    elif kind == "ignored":
        ignored = record.path / ".venv"
        ignored.mkdir()
        (ignored / "keep.txt").write_text("candidate", encoding="utf-8")
    else:
        target = record.path / "todo_app" / "main.py"
        target.write_text(target.read_text(encoding="utf-8") + "\n# candidate\n", encoding="utf-8")
        if kind in ("staged", "commit"):
            git(record.path, "add", "todo_app/main.py")
        if kind == "commit":
            subprocess.run(
                ["git", "-C", str(record.path), "-c", "user.name=Tester", "-c",
                 "user.email=test@example.invalid", "commit", "-m", "candidate"],
                check=True,
                capture_output=True,
                text=True,
            )

    with pytest.raises(WorkspaceDirtyError, match="changes"):
        manager.remove(record.id)
    assert record.path.is_dir()
    assert manager.get(record.id).has_changes


def test_clean_remove_keeps_lifecycle_record(setup: tuple[Path, Path, str]) -> None:
    from agentforge.workspace_manager import WorkspaceManager, WorkspaceState

    source, root, commit = setup
    manager = WorkspaceManager(source, root, commit)
    record = manager.create()
    removed = manager.remove(record.id)

    assert removed.state is WorkspaceState.REMOVED
    assert removed.removed_at is not None
    assert not record.path.exists()
    assert WorkspaceManager(source, root, commit).get(record.id) == removed
    assert git(source, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_get_reports_missing_workspace_and_unknown_id(setup: tuple[Path, Path, str]) -> None:
    from agentforge.workspace_manager import WorkspaceError, WorkspaceManager

    source, root, commit = setup
    manager = WorkspaceManager(source, root, commit)
    record = manager.create()
    with pytest.raises(KeyError):
        manager.get("f" * 32)
    with pytest.raises(ValueError):
        manager.get("../escape")

    git(source, "worktree", "remove", str(record.path))
    with pytest.raises(WorkspaceError, match="missing"):
        manager.get(record.id)


def test_remove_rejects_record_with_changed_baseline(setup: tuple[Path, Path, str]) -> None:
    from agentforge.workspace_manager import WorkspaceError, WorkspaceManager

    source, root, commit = setup
    manager = WorkspaceManager(source, root, commit)
    record = manager.create()
    metadata = root / ".records" / f"{record.id}.json"
    data = json.loads(metadata.read_text(encoding="utf-8"))
    data["baseline_commit"] = "0" * 40
    metadata.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(WorkspaceError, match="baseline"):
        manager.remove(record.id)
    assert record.path.is_dir()
