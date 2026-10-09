"""M9 binds checked file bytes, including files Git would ignore."""

import subprocess
from pathlib import Path

import pytest
from test_container_runner import create_workspace


def test_clean_snapshot_and_candidate_bytes_are_bound(tmp_path: Path) -> None:
    from agentforge.acceptance.snapshot import capture, fixed_files

    manager, record = create_workspace(tmp_path)
    fixed = fixed_files(manager)
    original = capture(manager, record.id, fixed, baseline=True)
    assert original.head == manager.baseline_commit
    assert original.files == fixed
    target = record.path / "todo_app/main.py"
    target.write_bytes(target.read_bytes() + b"\n# candidate\n")
    candidate = capture(manager, record.id, fixed)
    assert candidate.digest != original.digest
    assert candidate.head == original.head
    destination = tmp_path / "snapshot"
    candidate.write_to(destination)
    target.write_bytes(b"changed after capture")
    assert (destination / "todo_app/main.py").read_bytes() == candidate.files["todo_app/main.py"]
    assert not (destination / ".git").exists()


@pytest.mark.parametrize("relative", [
    "tests/test_todos.py", "requirements.lock", "pytest.ini", "conftest.py", "pytest.py",
    "sitecustomize.py", ".gitignore", "ignored-control.py",
])
def test_protected_or_new_root_files_are_rejected(tmp_path: Path, relative: str) -> None:
    from agentforge.acceptance.snapshot import capture, fixed_files

    manager, record = create_workspace(tmp_path)
    fixed = fixed_files(manager)
    (record.path / relative).write_bytes(b"# changed authority\n")
    with pytest.raises(ValueError, match="protected"):
        capture(manager, record.id, fixed)


def test_baseline_requires_exact_files_and_head(tmp_path: Path) -> None:
    from agentforge.acceptance.snapshot import capture, fixed_files

    manager, record = create_workspace(tmp_path)
    fixed = fixed_files(manager)
    target = record.path / "todo_app/main.py"
    target.write_bytes(target.read_bytes() + b"\n# edited\n")
    with pytest.raises(ValueError, match=r"before.*modification"):
        capture(manager, record.id, fixed, baseline=True)
    target.write_bytes(fixed["todo_app/main.py"])
    subprocess.run(
        ["git", "-C", str(record.path), "-c", "user.name=Test", "-c",
         "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "new head"],
        check=True, capture_output=True,
    )
    with pytest.raises(ValueError, match="HEAD"):
        capture(manager, record.id, fixed, baseline=True)


def test_ignored_and_deleted_app_files_change_digest(tmp_path: Path) -> None:
    from agentforge.acceptance.snapshot import capture, fixed_files

    manager, record = create_workspace(tmp_path)
    fixed = fixed_files(manager)
    before = capture(manager, record.id, fixed)
    exclude = manager.source_repository / ".git/info/exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("todo_app/ignored.py\n", encoding="utf-8")
    (record.path / "todo_app/ignored.py").write_bytes(b"# ignored but bound\n")
    added = capture(manager, record.id, fixed)
    assert added.digest != before.digest
    assert added.files["todo_app/ignored.py"] == b"# ignored but bound\n"
    (record.path / "todo_app/__init__.py").unlink()
    deleted = capture(manager, record.id, fixed)
    assert deleted.digest != added.digest
    assert "todo_app/__init__.py" not in deleted.files


def test_hardlinks_and_resource_overflow_are_rejected(tmp_path: Path) -> None:
    import os

    from agentforge.acceptance.snapshot import capture, fixed_files

    manager, record = create_workspace(tmp_path)
    fixed = fixed_files(manager)
    target = record.path / "todo_app/new.py"
    os.link(record.path / "todo_app/main.py", target)
    with pytest.raises(ValueError, match="hardlink"):
        capture(manager, record.id, fixed)
    target.unlink()
    target.write_bytes(b"x" * (256 * 1024 + 1))
    with pytest.raises(ValueError, match="limit"):
        capture(manager, record.id, fixed)


def test_deleted_authority_is_rejected(tmp_path: Path) -> None:
    from agentforge.acceptance.snapshot import capture, fixed_files

    manager, record = create_workspace(tmp_path)
    fixed = fixed_files(manager)
    (record.path / "tests/test_todos.py").unlink()
    with pytest.raises(ValueError, match="protected"):
        capture(manager, record.id, fixed)
