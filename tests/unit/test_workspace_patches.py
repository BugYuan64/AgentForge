"""Controlled text patches preserve scope and reject stale or unsafe edits."""

import os
import subprocess
from pathlib import Path

import pytest
from scripts.create_todo_baseline import create_baseline

from agentforge.workspace_management.manager import WorkspaceManager

FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "todo_fixture"


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    root = tmp_path_factory.mktemp("m8-patches")
    source = root / "source"
    commit = create_baseline(FIXTURE, source)
    manager = WorkspaceManager(source, root / "workspaces", commit)
    return manager, manager.create()


def api():
    try:
        from agentforge.workspace_tools.contracts import ToolRequest, ToolStatus
        from agentforge.workspace_tools.patches import ModificationTools
    except ModuleNotFoundError as exc:
        pytest.fail(f"M8 patch tools are missing: {exc}")
    return ToolRequest, ToolStatus, ModificationTools


def patch(path: str, before="old", after="new") -> str:
    return f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-{before}\n+{after}\n"


def test_patch_changes_only_allowed_candidate_content(workspace) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    manager, record = workspace
    target = record.path / "todo_app" / "m8-edit.txt"
    target.write_bytes(b"old\n")

    result = ModificationTools(manager).execute(
        ToolRequest("apply_patch", record.id, patch=patch("todo_app/m8-edit.txt"))
    )

    assert result.status is ToolStatus.COMPLETED
    assert target.read_bytes() == b"new\n"
    assert result.to_dict()["details"]["changed_paths"] == ["todo_app/m8-edit.txt"]
    assert (manager.source_repository / "todo_app" / "main.py").read_bytes() == (
        FIXTURE / "todo_app" / "main.py"
    ).read_bytes()
    assert not (manager.source_repository / "todo_app" / "m8-edit.txt").exists()


def test_patch_creates_and_deletes_text_with_checked_hunks(workspace) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    manager, record = workspace
    tools = ModificationTools(manager)
    added = "--- /dev/null\n+++ b/todo_app/m8-new/note.txt\n@@ -0,0 +1 @@\n+hello\n"
    result = tools.execute(ToolRequest("apply_patch", record.id, patch=added))
    assert result.status is ToolStatus.COMPLETED
    target = record.path / "todo_app" / "m8-new" / "note.txt"
    assert target.read_bytes() == b"hello\n"
    deleted = "--- a/todo_app/m8-new/note.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-hello\n"
    result = tools.execute(ToolRequest("apply_patch", record.id, patch=deleted))
    assert result.status is ToolStatus.COMPLETED
    assert not target.exists()


def test_all_files_are_checked_before_any_write(workspace) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    manager, record = workspace
    first = record.path / "todo_app" / "m8-first.txt"
    second = record.path / "todo_app" / "m8-second.txt"
    first.write_bytes(b"old\n")
    second.write_bytes(b"already changed\n")
    payload = patch("todo_app/m8-first.txt") + patch("todo_app/m8-second.txt")

    result = ModificationTools(manager).execute(
        ToolRequest("apply_patch", record.id, patch=payload)
    )

    assert result.status is ToolStatus.REJECTED
    assert first.read_bytes() == b"old\n"
    assert second.read_bytes() == b"already changed\n"


@pytest.mark.parametrize(
    "path",
    [
        "../source/README.md",
        "/tmp/outside",
        "C:/outside",
        "todo_app/../../outside",
        ".git/config",
        "todo_app/.git/config",
        "todo_app/NUL.txt",
        "todo_app/file:secret",
        "todo_app/CON .txt",
        "tests/test_todos.py",
        "requirements.lock",
    ],
)
def test_patch_rejects_paths_outside_the_host_write_scope(workspace, path: str) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    manager, record = workspace

    result = ModificationTools(manager).execute(
        ToolRequest("apply_patch", record.id, patch=patch(path))
    )

    assert result.status is ToolStatus.REJECTED
    assert result.error


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "random text",
        "GIT binary patch\n",
        "old mode 100644\nnew mode 100755\n",
        "rename from todo_app/a\nrename to todo_app/b\n",
        "--- a/todo_app/a\n+++ b/todo_app/b\n@@ -1 +1 @@\n-old\n+new\n",
        "--- a/todo_app/a\n+++ b/todo_app/a\n@@ -1,2 +1 @@\n-old\n+new\n",
        "--- a/todo_app/a\n+++ b/todo_app/a\n@@ -1 +1 @@\n-old\n+new\x00\n",
    ],
)
def test_unsupported_or_malformed_patch_is_rejected(workspace, payload: str) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    manager, record = workspace
    result = ModificationTools(manager).execute(
        ToolRequest("apply_patch", record.id, patch=payload)
    )
    assert result.status is ToolStatus.REJECTED


def test_no_newline_markers_preserve_the_file_ending(workspace) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    manager, record = workspace
    target = record.path / "todo_app" / "m8-no-newline.txt"
    target.write_bytes(b"old")
    payload = (
        "--- a/todo_app/m8-no-newline.txt\n+++ b/todo_app/m8-no-newline.txt\n"
        "@@ -1 +1 @@\n-old\n\\ No newline at end of file\n"
        "+new\n\\ No newline at end of file\n"
    )
    result = ModificationTools(manager).execute(
        ToolRequest("apply_patch", record.id, patch=payload)
    )
    assert result.status is ToolStatus.COMPLETED
    assert target.read_bytes() == b"new"


def test_multiple_hunks_use_original_line_positions(workspace) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    manager, record = workspace
    target = record.path / "todo_app" / "m8-hunks.txt"
    target.write_bytes(b"one\ntwo\nthree\nfour\n")
    payload = (
        "--- a/todo_app/m8-hunks.txt\n+++ b/todo_app/m8-hunks.txt\n"
        "@@ -1 +1,2 @@\n-one\n+ONE\n+extra\n"
        "@@ -4 +5 @@\n-four\n+FOUR\n"
    )
    result = ModificationTools(manager).execute(
        ToolRequest("apply_patch", record.id, patch=payload)
    )
    assert result.status is ToolStatus.COMPLETED
    assert target.read_bytes() == b"ONE\nextra\ntwo\nthree\nFOUR\n"


def test_write_failure_restores_previously_written_files(workspace, monkeypatch) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    manager, record = workspace
    first = record.path / "todo_app" / "m8-rollback-a.txt"
    second = record.path / "todo_app" / "m8-rollback-b.txt"
    first.write_bytes(b"old\n")
    second.write_bytes(b"old\n")
    original_replace = os.replace

    def failing_replace(source, destination):
        if Path(destination) == second:
            raise OSError("simulated disk failure")
        return original_replace(source, destination)

    monkeypatch.setattr(os, "replace", failing_replace)
    payload = patch("todo_app/m8-rollback-a.txt") + patch("todo_app/m8-rollback-b.txt")
    result = ModificationTools(manager).execute(
        ToolRequest("apply_patch", record.id, patch=payload)
    )
    assert result.status is ToolStatus.ERROR
    assert first.read_bytes() == b"old\n"
    assert second.read_bytes() == b"old\n"
    assert not list(first.parent.glob(".agentforge-patch-*"))


def test_hardlinked_target_is_rejected_without_touching_external_file(workspace) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    manager, record = workspace
    external = manager.source_repository.parent / "m8-hardlink-external.txt"
    external.write_bytes(b"old\n")
    target = record.path / "todo_app" / "m8-hardlink.txt"
    os.link(external, target)
    try:
        result = ModificationTools(manager).execute(
            ToolRequest("apply_patch", record.id, patch=patch("todo_app/m8-hardlink.txt"))
        )
        assert result.status is ToolStatus.REJECTED
        assert external.read_bytes() == b"old\n"
    finally:
        target.unlink()


def test_linked_parent_cannot_redirect_patch_writes(workspace) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    manager, record = workspace
    outside = manager.source_repository.parent / "m8-outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"old\n")
    link = record.path / "todo_app" / "m8-link"
    if os.name == "nt":
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, check=False
        )
        assert created.returncode == 0
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        result = ModificationTools(manager).execute(
            ToolRequest("apply_patch", record.id, patch=patch("todo_app/m8-link/secret.txt"))
        )
        assert result.status is ToolStatus.REJECTED
        assert (outside / "secret.txt").read_bytes() == b"old\n"
    finally:
        link.unlink() if link.is_symlink() else link.rmdir()


def test_patch_and_result_file_limits_are_enforced(workspace) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    from agentforge.workspace_tools.contracts import ToolLimits

    manager, record = workspace
    target = record.path / "todo_app" / "m8-limit.txt"
    target.write_bytes(b"old\n")
    payload = patch("todo_app/m8-limit.txt", after="a" * 30)
    for limits in (ToolLimits(max_patch_bytes=20), ToolLimits(max_file_bytes=20)):
        result = ModificationTools(manager, limits=limits).execute(
            ToolRequest("apply_patch", record.id, patch=payload)
        )
        assert result.status is ToolStatus.REJECTED
        assert target.read_bytes() == b"old\n"


def test_duplicate_file_sections_and_excess_file_count_are_rejected(workspace) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    from agentforge.workspace_tools.contracts import ToolLimits

    manager, record = workspace
    for payload, limits in (
        (patch("todo_app/a") * 2, ToolLimits()),
        (patch("todo_app/a") + patch("todo_app/b"), ToolLimits(max_patch_files=1)),
    ):
        result = ModificationTools(manager, limits=limits).execute(
            ToolRequest("apply_patch", record.id, patch=payload)
        )
        assert result.status is ToolStatus.REJECTED


def test_dangling_git_header_does_not_hide_an_incomplete_file_section(workspace) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    manager, record = workspace
    target = record.path / "todo_app" / "m8-dangling.txt"
    target.write_bytes(b"old\n")
    payload = patch("todo_app/m8-dangling.txt") + "diff --git a/todo_app/b b/todo_app/b\n"

    result = ModificationTools(manager).execute(
        ToolRequest("apply_patch", record.id, patch=payload)
    )

    assert result.status is ToolStatus.REJECTED
    assert target.read_bytes() == b"old\n"


def test_patch_success_response_respects_small_output_limit(workspace) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    from agentforge.workspace_tools.contracts import ToolLimits

    manager, record = workspace
    target = record.path / "todo_app" / "m8-small-output.txt"
    target.write_bytes(b"old\n")

    result = ModificationTools(manager, ToolLimits(max_output_chars=5)).execute(
        ToolRequest("apply_patch", record.id, patch=patch("todo_app/m8-small-output.txt"))
    )

    assert result.status is ToolStatus.COMPLETED
    assert len(result.output) <= 5
    assert result.truncated
    assert "output_limit" in result.notices


def test_malformed_workspace_id_is_rejected(workspace) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    manager, _ = workspace

    result = ModificationTools(manager).execute(
        ToolRequest("apply_patch", ["invalid"], patch=patch("todo_app/main.py"))
    )

    assert result.status is ToolStatus.REJECTED


def test_root_junction_is_rejected_before_workspace_git_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "workspaces"
    root.mkdir()
    workspace_id = "a" * 32
    junction = root / workspace_id
    linked = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        check=False,
    )
    assert linked.returncode == 0, linked.stderr
    manager = WorkspaceManager(tmp_path / "source", root, "b" * 40)

    def unexpected_get(*args, **kwargs):
        pytest.fail("root junction must be rejected before Git identity inspection")

    monkeypatch.setattr(manager, "get", unexpected_get)
    result = ModificationTools(manager).execute(
        ToolRequest("apply_patch", workspace_id, patch=patch("todo_app/main.py"))
    )

    assert result.status is ToolStatus.REJECTED


@pytest.mark.parametrize("first_operation", ["create", "delete", "edit"])
def test_failed_patch_rolls_back_creation_deletion_and_reports_incomplete_rollback(
    workspace,
    monkeypatch,
    first_operation,
) -> None:
    ToolRequest, ToolStatus, ModificationTools = api()
    manager, record = workspace
    name = f"todo_app/m8-transaction-{first_operation}/first.txt"
    first = record.path / name
    second = record.path / f"todo_app/m8-transaction-{first_operation}-second.txt"
    second.write_bytes(b"old\n")
    if first_operation != "create":
        first.parent.mkdir()
        first.write_bytes(b"old\n")
    if first_operation == "create":
        payload = f"--- /dev/null\n+++ b/{name}\n@@ -0,0 +1 @@\n+new\n"
    elif first_operation == "delete":
        payload = f"--- a/{name}\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n"
    else:
        payload = patch(name)
    payload += patch(second.relative_to(record.path).as_posix())
    original_replace = os.replace

    def fail_second_and_maybe_rollback(source, destination):
        target = Path(destination)
        if target == second or (
            first_operation == "edit" and target == first and first.read_bytes() == b"new\n"
        ):
            raise OSError("simulated failure")
        return original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_and_maybe_rollback)
    result = ModificationTools(manager).execute(
        ToolRequest("apply_patch", record.id, patch=payload)
    )

    assert result.status is ToolStatus.ERROR
    assert second.read_bytes() == b"old\n"
    if first_operation == "create":
        assert not first.parent.exists()
        assert "rollback complete" in result.error
    elif first_operation == "delete":
        assert first.read_bytes() == b"old\n"
        assert "rollback complete" in result.error
    else:
        assert first.read_bytes() == b"new\n"
        assert "rollback incomplete" in result.error
