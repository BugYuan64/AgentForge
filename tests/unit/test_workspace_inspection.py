"""M8 inspection reports candidate state without changing the source repository."""

import os
import subprocess
from pathlib import Path
from time import monotonic

import pytest

from agentforge.workspace_management.manager import WorkspaceManager, WorkspaceRecord
from agentforge.workspace_tools.contracts import ToolLimits, ToolRequest, ToolStatus


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[WorkspaceManager, WorkspaceRecord]:
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init")
    git(source, "config", "core.autocrlf", "false")
    (source / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    git(source, "add", "tracked.txt")
    git(
        source,
        "-c",
        "user.name=Tester",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "baseline",
    )
    manager = WorkspaceManager(source, tmp_path / "workspaces", git(source, "rev-parse", "HEAD"))
    return manager, manager.create()


def tools(manager: WorkspaceManager, limits: ToolLimits | None = None, **kwargs):
    try:
        from agentforge.workspace_tools.inspection import InspectionTools
    except ModuleNotFoundError as exc:
        pytest.fail(f"M8 inspection tools are missing: {exc}")
    return InspectionTools(manager, limits, **kwargs)


def test_status_reports_tracked_and_untracked_candidate_changes(workspace) -> None:
    manager, record = workspace
    (record.path / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (record.path / "new.txt").write_text("new candidate\n", encoding="utf-8")

    result = tools(manager).execute(ToolRequest("status", record.id))

    assert result.status is ToolStatus.COMPLETED
    assert " M tracked.txt" in result.output
    assert "?? new.txt" in result.output
    assert not result.truncated
    assert git(manager.source_repository, "status", "--porcelain") == ""
    assert (record.path / "tracked.txt").read_text(encoding="utf-8") == "candidate\n"


@pytest.mark.parametrize("kind", ["tracked", "staged", "committed"])
def test_diff_compares_all_candidate_changes_to_fixed_baseline(workspace, kind: str) -> None:
    manager, record = workspace
    (record.path / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    if kind in {"staged", "committed"}:
        git(record.path, "add", "tracked.txt")
    if kind == "committed":
        git(
            record.path,
            "-c",
            "user.name=Tester",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "candidate",
        )

    result = tools(manager).execute(ToolRequest("diff", record.id))

    assert result.status is ToolStatus.COMPLETED
    assert "-baseline" in result.output
    assert "+candidate" in result.output
    assert git(manager.source_repository, "rev-parse", "HEAD").strip() == manager.baseline_commit


def test_diff_includes_untracked_utf8_additions(workspace) -> None:
    manager, record = workspace
    (record.path / "new.txt").write_text("你好\nnew candidate\n", encoding="utf-8")

    result = tools(manager).execute(ToolRequest("diff", record.id))

    assert result.status is ToolStatus.COMPLETED
    assert "+++ b/new.txt" in result.output
    assert "+你好" in result.output
    assert "+new candidate" in result.output
    assert not result.truncated


@pytest.mark.parametrize("tool", ["status", "diff"])
def test_inspection_output_is_bounded(workspace, tool: str) -> None:
    manager, record = workspace
    (record.path / "tracked.txt").write_text("candidate\n" * 1000, encoding="utf-8")
    (record.path / "new-long-file-name.txt").write_text("new candidate\n", encoding="utf-8")

    result = tools(manager, ToolLimits(max_output_chars=15)).execute(ToolRequest(tool, record.id))

    assert result.status is ToolStatus.COMPLETED
    assert len(result.output) == 15
    assert result.truncated
    assert "output_limit" in result.notices


@pytest.mark.parametrize("tool", ["status", "diff", "run_tests"])
@pytest.mark.parametrize("arguments", [{"path": "tracked.txt"}, {"query": "extra"}])
def test_inspection_rejects_non_root_or_extra_query_arguments(workspace, tool, arguments) -> None:
    manager, record = workspace

    result = tools(manager).execute(ToolRequest(tool, record.id, **arguments))

    assert result.status is ToolStatus.REJECTED
    assert result.output == ""


def test_unknown_and_removed_workspaces_are_rejected(workspace) -> None:
    manager, record = workspace
    manager.remove(record.id)

    for workspace_id in (record.id, "f" * 32):
        result = tools(manager).execute(ToolRequest("status", workspace_id))
        assert result.status is ToolStatus.REJECTED
        assert result.output == ""


def test_diff_does_not_run_external_diff_commands(workspace, tmp_path: Path) -> None:
    manager, record = workspace
    marker = tmp_path / "external-ran.txt"
    driver = tmp_path / "external.cmd"
    driver.write_text(f'@echo external>"{marker}"\n', encoding="utf-8")
    git(record.path, "config", "diff.external", str(driver))
    (record.path / "tracked.txt").write_text("candidate\n", encoding="utf-8")

    result = tools(manager).execute(ToolRequest("diff", record.id))

    assert result.status is ToolStatus.COMPLETED
    assert "+candidate" in result.output
    assert not marker.exists()


def test_tree_preflight_rejects_workspaces_exceeding_entry_budget(workspace) -> None:
    manager, record = workspace
    for number in range(4):
        (record.path / f"new-{number}.txt").write_text("candidate", encoding="utf-8")

    result = tools(manager, ToolLimits(max_entries=2)).execute(ToolRequest("diff", record.id))

    assert result.status is ToolStatus.REJECTED
    assert "entry" in result.error
    assert result.output == ""


def test_untracked_diff_reports_non_text_and_large_files_without_reading_them(workspace) -> None:
    manager, record = workspace
    (record.path / "binary.bin").write_bytes(b"secret\x00binary")
    (record.path / "large.txt").write_bytes(b"x" * 40)
    (record.path / "text.txt").write_text("new\n", encoding="utf-8")

    result = tools(manager, ToolLimits(max_file_bytes=16)).execute(ToolRequest("diff", record.id))

    assert result.status is ToolStatus.COMPLETED
    assert "+new" in result.output
    assert "secret" not in result.output
    assert "skipped_non_text=1" in result.notices
    assert "skipped_large_files=1" in result.notices
    assert result.truncated


def test_non_string_tool_is_rejected_with_a_uniform_result(workspace) -> None:
    manager, record = workspace

    result = tools(manager).execute(ToolRequest([], record.id))

    assert result.status is ToolStatus.REJECTED
    assert result.output == ""


def test_nested_git_metadata_is_rejected_before_git_reads_it(workspace) -> None:
    manager, record = workspace
    nested = record.path / "nested"
    nested.mkdir()
    (nested / ".git").write_text("gitdir: /outside/private\n", encoding="utf-8")

    result = tools(manager).execute(ToolRequest("status", record.id))

    assert result.status is ToolStatus.REJECTED
    assert result.output == ""


def test_git_timeout_returns_a_bounded_error(workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    import agentforge.workspace_tools.inspection as inspection

    manager, record = workspace
    monkeypatch.setattr(inspection, "GIT_TIMEOUT_SECONDS", 0.001)
    started = monotonic()

    result = tools(manager).execute(ToolRequest("status", record.id))

    assert result.status is ToolStatus.ERROR
    assert "time limit" in result.error
    assert monotonic() - started < 2


@pytest.mark.parametrize("tool", ["status", "diff", "run_tests"])
def test_directory_links_are_rejected_without_outside_content(
    workspace,
    tmp_path: Path,
    tool,
) -> None:
    manager, record = workspace
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("private secret", encoding="utf-8")
    junction = record.path / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        pytest.skip("directory junction creation is unavailable")

    result = tools(manager).execute(ToolRequest(tool, record.id))

    assert result.status is ToolStatus.REJECTED
    assert "private secret" not in result.output
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "private secret"


@pytest.mark.parametrize(
    ("settings", "expected_status", "expected_state", "expected_exit"),
    [
        ({"test_exit": 1}, ToolStatus.COMPLETED, "completed", 1),
        ({"image_error": True}, ToolStatus.ERROR, "infrastructure_error", None),
        ({"wait_sleep": 2}, ToolStatus.ERROR, "timed_out", None),
    ],
)
def test_run_tests_preserves_real_m6_outcomes(
    workspace,
    tmp_path,
    settings,
    expected_status,
    expected_state,
    expected_exit,
) -> None:
    from test_container_runner import fake_docker

    from agentforge.container_execution.runner import ContainerTestRunner

    manager, record = workspace
    docker_command, _ = fake_docker(tmp_path, **settings)
    runner = ContainerTestRunner(
        manager,
        timeout_seconds=0.5 if "wait_sleep" in settings else 5,
        docker_command=docker_command,
    )

    result = tools(manager, test_runner=runner).execute(ToolRequest("run_tests", record.id))

    assert result.status is expected_status
    assert result.details["state"] == expected_state
    assert result.details["exit_code"] == expected_exit
    assert result.details["run_id"]
    assert Path(result.details["log_path"]).is_file()
    assert result.details["elapsed_seconds"] >= 0
    if expected_status is ToolStatus.ERROR:
        assert result.error
    else:
        assert "4 passed, 1 failed" in result.output


def test_run_tests_caps_output_but_preserves_the_durable_complete_log(workspace, tmp_path) -> None:
    from test_container_runner import fake_docker

    from agentforge.container_execution.runner import ContainerTestRunner

    manager, record = workspace
    docker_command, _ = fake_docker(tmp_path, test_log="x" * 1000)
    runner = ContainerTestRunner(manager, docker_command=docker_command)

    result = tools(manager, ToolLimits(max_output_chars=80), test_runner=runner).execute(
        ToolRequest("run_tests", record.id)
    )

    assert result.status is ToolStatus.COMPLETED
    assert len(result.output) == 80
    assert result.truncated
    assert "output_limit" in result.notices
    assert "x" * 1000 in Path(result.details["log_path"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("tool", ["status", "diff", "run_tests"])
def test_inspection_rejects_patch_arguments(workspace, tool) -> None:
    manager, record = workspace

    result = tools(manager).execute(ToolRequest(tool, record.id, patch="unexpected patch"))

    assert result.status is ToolStatus.REJECTED
    assert result.output == ""


def test_diff_rejects_hardlinked_content(workspace, tmp_path) -> None:
    manager, record = workspace
    outside = tmp_path / "private.txt"
    outside.write_text("outside secret", encoding="utf-8")
    os.link(outside, record.path / "linked.txt")

    result = tools(manager).execute(ToolRequest("diff", record.id))

    assert result.status is ToolStatus.REJECTED
    assert "outside secret" not in result.output


def test_untracked_diff_preserves_bom_and_marks_missing_final_newline(workspace) -> None:
    manager, record = workspace
    content = "\ufeffcandidate\u2028literal separator"
    (record.path / "new.txt").write_bytes(content.encode("utf-8"))

    result = tools(manager).execute(ToolRequest("diff", record.id))

    assert result.status is ToolStatus.COMPLETED
    assert f"+{content}\n\\ No newline at end of file\n" in result.output
