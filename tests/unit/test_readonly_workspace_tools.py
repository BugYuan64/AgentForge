"""Read-only workspace tools return useful code without changing either repository."""

import os
import subprocess
from pathlib import Path

import pytest
from scripts.create_todo_baseline import create_baseline

from agentforge.workspace_management.manager import WorkspaceManager, WorkspaceRecord

FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "todo_fixture"


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> tuple[WorkspaceManager, WorkspaceRecord]:
    root = tmp_path_factory.mktemp("m7-real-workspace")
    source = root / "source"
    commit = create_baseline(FIXTURE, source)
    manager = WorkspaceManager(source, root / "workspaces", commit)
    return manager, manager.create()


def api():
    try:
        from agentforge.workspace_tools.contracts import ToolRequest, ToolStatus
        from agentforge.workspace_tools.readonly import ReadOnlyWorkspaceTools
    except ModuleNotFoundError as exc:
        pytest.fail(f"M7 read-only workspace tools are missing: {exc}")
    return ToolRequest, ToolStatus, ReadOnlyWorkspaceTools


def test_lists_candidate_files_without_git_metadata_or_content_changes(workspace) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    manager, record = workspace
    main = record.path / "todo_app" / "main.py"
    before = main.read_bytes()

    result = ReadOnlyWorkspaceTools(manager).execute(
        ToolRequest("list_files", record.id, "todo_app")
    )

    assert result.status is ToolStatus.COMPLETED
    assert result.output == "todo_app/__init__.py\ntodo_app/main.py\n"
    assert not result.truncated
    assert main.read_bytes() == before
    assert not manager.get(record.id).has_changes
    source_status = subprocess.run(
        ["git", "-C", str(manager.source_repository), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert source_status.stdout == ""
    root_result = ReadOnlyWorkspaceTools(manager).execute(ToolRequest("list_files", record.id))
    assert ".git" not in root_result.output.splitlines()


def test_reads_utf8_candidate_text_with_a_uniform_json_result(workspace) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    manager, record = workspace
    (record.path / "m7-read.txt").write_bytes("你好, M7\nsecond line\n".encode())

    result = ReadOnlyWorkspaceTools(manager).execute(
        ToolRequest("read_file", record.id, "m7-read.txt")
    )

    assert result.status is ToolStatus.COMPLETED
    assert result.to_dict() == {
        "tool": "read_file",
        "workspace_id": record.id,
        "path": "m7-read.txt",
        "status": "completed",
        "output": "你好, M7\nsecond line\n",
        "truncated": False,
        "notices": [],
        "error": None,
    }


def test_searches_literal_text_and_reports_one_based_lines(workspace) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    manager, record = workspace
    directory = record.path / "m7-search"
    directory.mkdir()
    (directory / "a.py").write_text("# example\nprint('.+')\nprint('other')\n", encoding="utf-8")

    result = ReadOnlyWorkspaceTools(manager).execute(
        ToolRequest("search", record.id, "m7-search", ".+")
    )

    assert result.status is ToolStatus.COMPLETED
    assert result.output == "m7-search/a.py:2:print('.+')\n"
    assert not result.truncated


@pytest.mark.parametrize(
    "path",
    [
        "../source/README.md",
        "/etc/passwd",
        r"\Windows\win.ini",
        r"C:\Windows\win.ini",
        "C:relative.txt",
        r"\\server\share\file",
        "todo_app/../../README.md",
        ".git",
        ".GIT/config",
        ".git.",
        ".git /config",
        "file.txt:secret",
        "NUL",
        "CON.txt",
        "COM1",
        "file\x00.txt",
        "",
        "a/./b",
        "a./b",
        "COM¹",
        "NUL.txt",
        "new\nline.txt",
        "CON .txt",
        "NUL .txt",
        "COM1 .txt",
    ],
)
def test_rejects_unsafe_paths_without_returning_file_content(workspace, path: str) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    manager, record = workspace

    result = ReadOnlyWorkspaceTools(manager).execute(ToolRequest("read_file", record.id, path))

    assert result.status is ToolStatus.REJECTED
    assert result.output == ""
    assert result.error


def test_unknown_and_removed_workspaces_are_rejected(workspace) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    manager, _ = workspace
    tools = ReadOnlyWorkspaceTools(manager)
    removed = manager.create()
    manager.remove(removed.id)

    for workspace_id in ("f" * 32, removed.id):
        result = tools.execute(ToolRequest("list_files", workspace_id))
        assert result.status is ToolStatus.REJECTED
        assert result.output == ""


@pytest.mark.parametrize(
    ("tool", "query"),
    [
        ("shell", None),
        ("search", ""),
        ("search", "first\nsecond"),
        ("search", "x" * 1025),
        ("list_files", "extra"),
    ],
)
def test_invalid_tool_arguments_are_rejected(workspace, tool: str, query: str | None) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    manager, record = workspace

    result = ReadOnlyWorkspaceTools(manager).execute(ToolRequest(tool, record.id, ".", query))

    assert result.status is ToolStatus.REJECTED
    assert not result.output


def test_missing_file_has_a_uniform_error_result(workspace) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    manager, record = workspace

    result = ReadOnlyWorkspaceTools(manager).execute(
        ToolRequest("read_file", record.id, "missing.txt")
    )

    assert result.status is ToolStatus.ERROR
    assert result.error
    assert result.output == ""


def test_reading_a_directory_is_rejected(workspace) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    manager, record = workspace

    result = ReadOnlyWorkspaceTools(manager).execute(
        ToolRequest("read_file", record.id, "todo_app")
    )

    assert result.status is ToolStatus.REJECTED


@pytest.mark.parametrize("content", [b"abc\x00def", b"\xff\xfe\xff"])
def test_explicit_nontext_file_reads_are_rejected(workspace, content: bytes) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    manager, record = workspace
    (record.path / "m7-binary.bin").write_bytes(content)

    result = ReadOnlyWorkspaceTools(manager).execute(
        ToolRequest("read_file", record.id, "m7-binary.bin")
    )

    assert result.status is ToolStatus.REJECTED
    assert not result.output


def test_output_is_bounded_and_truncation_is_visible_in_json(workspace) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    from agentforge.workspace_tools.contracts import ToolLimits

    manager, record = workspace
    (record.path / "m7-long.txt").write_text("你好世界" * 10, encoding="utf-8")
    tools = ReadOnlyWorkspaceTools(manager, ToolLimits(max_output_chars=5))

    result = tools.execute(ToolRequest("read_file", record.id, "m7-long.txt"))

    assert result.status is ToolStatus.COMPLETED
    assert result.output == "你好世界你"
    assert result.to_dict()["truncated"] is True
    assert "output_limit" in result.notices


def test_oversized_explicit_read_is_rejected(workspace) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    from agentforge.workspace_tools.contracts import ToolLimits

    manager, record = workspace
    (record.path / "m7-big.txt").write_bytes(b"123456789")

    result = ReadOnlyWorkspaceTools(manager, ToolLimits(max_file_bytes=8)).execute(
        ToolRequest("read_file", record.id, "m7-big.txt")
    )

    assert result.status is ToolStatus.REJECTED
    assert not result.output


def test_listing_stops_at_entry_budget_and_records_partial_results(workspace) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    from agentforge.workspace_tools.contracts import ToolLimits

    manager, record = workspace
    directory = record.path / "m7-many"
    directory.mkdir()
    for number in range(10):
        (directory / f"{number}.txt").write_text("small", encoding="utf-8")

    result = ReadOnlyWorkspaceTools(manager, ToolLimits(max_entries=3)).execute(
        ToolRequest("list_files", record.id, "m7-many")
    )

    assert result.status is ToolStatus.COMPLETED
    assert len(result.output.splitlines()) <= 3
    assert result.truncated
    assert "entry_limit" in result.notices


def test_search_byte_budget_stops_before_reading_the_next_file(workspace) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    from agentforge.workspace_tools.contracts import ToolLimits

    manager, record = workspace
    directory = record.path / "m7-budget"
    directory.mkdir()
    (directory / "a.txt").write_bytes(b"needleA\n")
    (directory / "b.txt").write_bytes(b"needleB\n")

    result = ReadOnlyWorkspaceTools(manager, ToolLimits(max_search_bytes=10)).execute(
        ToolRequest("search", record.id, "m7-budget", "needle")
    )

    assert result.status is ToolStatus.COMPLETED
    assert result.output == "m7-budget/a.txt:1:needleA\n"
    assert result.truncated
    assert "search_byte_limit" in result.notices


def test_search_records_skipped_large_and_nontext_files(workspace) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    from agentforge.workspace_tools.contracts import ToolLimits

    manager, record = workspace
    directory = record.path / "m7-skipped"
    directory.mkdir()
    (directory / "a.txt").write_bytes(b"needle" * 20)
    (directory / "b.bin").write_bytes(b"\x00needle")
    (directory / "c.txt").write_bytes(b"needle\n")

    result = ReadOnlyWorkspaceTools(manager, ToolLimits(max_file_bytes=10)).execute(
        ToolRequest("search", record.id, "m7-skipped", "needle")
    )

    assert result.status is ToolStatus.COMPLETED
    assert result.output == "m7-skipped/c.txt:1:needle\n"
    assert result.truncated
    assert "skipped_large_files=1" in result.notices
    assert "skipped_non_text=1" in result.notices


def test_real_directory_link_is_rejected_and_never_traversed(workspace) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    manager, record = workspace
    external = manager.source_repository.parent / "outside"
    external.mkdir()
    (external / "sentinel.txt").write_text("PRIVATE_OUTSIDE_CONTENT", encoding="utf-8")
    directory = record.path / "m7-links"
    directory.mkdir()
    link = directory / "jump"
    if os.name == "nt":
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(external)],
            capture_output=True,
            check=False,
        )
        assert created.returncode == 0, created.stderr
    else:
        link.symlink_to(external, target_is_directory=True)
    try:
        tools = ReadOnlyWorkspaceTools(manager)
        for tool, path, query in (
            ("read_file", "m7-links/jump/sentinel.txt", None),
            ("list_files", "m7-links/jump", None),
            ("search", "m7-links/jump", "PRIVATE"),
        ):
            explicit = tools.execute(ToolRequest(tool, record.id, path, query))
            assert explicit.status is ToolStatus.REJECTED
            assert not explicit.output
        for tool, query in (("list_files", None), ("search", "PRIVATE")):
            result = tools.execute(ToolRequest(tool, record.id, "m7-links", query))
            assert result.status is ToolStatus.COMPLETED
            assert result.output == ""
            assert "skipped_links=1" in result.notices
        assert (external / "sentinel.txt").read_text(encoding="utf-8") == "PRIVATE_OUTSIDE_CONTENT"
    finally:
        link.rmdir() if not link.is_symlink() else link.unlink()


@pytest.mark.parametrize("field", ["tool", "workspace_id", "path", "query"])
def test_malformed_request_fields_return_rejection(workspace, field: str) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    manager, record = workspace
    arguments = {"tool": "search", "workspace_id": record.id, "path": ".", "query": "Todo"}
    arguments[field] = ["invalid"]

    result = ReadOnlyWorkspaceTools(manager).execute(ToolRequest(**arguments))

    assert result.status is ToolStatus.REJECTED
    assert not result.output


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_invalid_host_limits_are_rejected(value) -> None:
    from agentforge.workspace_tools.contracts import ToolLimits

    with pytest.raises(ValueError, match="positive integer"):
        ToolLimits(max_output_chars=value)


def test_readonly_inspection_does_not_scan_candidate_change_status(
    workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    import agentforge.workspace_management.manager as manager_module

    manager, record = workspace
    original_git = manager_module._git

    def git_without_status(repository, *arguments):
        if arguments[0] == "status":
            raise manager_module.WorkspaceError("candidate status scan exceeds resource budget")
        return original_git(repository, *arguments)

    monkeypatch.setattr(manager_module, "_git", git_without_status)
    result = ReadOnlyWorkspaceTools(manager).execute(
        ToolRequest("read_file", record.id, "todo_app/__init__.py")
    )

    assert result.status is ToolStatus.COMPLETED


def test_identity_only_workspace_validation_does_not_claim_candidate_is_clean(workspace) -> None:
    manager, record = workspace
    (record.path / "m7-dirty.txt").write_text("candidate", encoding="utf-8")

    identity = manager.get(record.id, inspect_changes=False)

    assert identity.state.value == "active"
    assert identity.has_changes is None
    assert manager.get(record.id).has_changes is True


def test_long_workspace_diagnostics_are_bounded(workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    ToolRequest, ToolStatus, ReadOnlyWorkspaceTools = api()
    from agentforge.workspace_management.manager import WorkspaceError
    from agentforge.workspace_tools.contracts import ToolLimits

    manager, record = workspace

    def failed_get(*args, **kwargs):
        raise WorkspaceError("long diagnostic " * 100)

    monkeypatch.setattr(manager, "get", failed_get)
    result = ReadOnlyWorkspaceTools(manager, ToolLimits(max_output_chars=16)).execute(
        ToolRequest("list_files", record.id)
    )

    assert result.status is ToolStatus.REJECTED
    assert len(result.error) <= 16
    assert result.truncated
    assert "error_limit" in result.notices
