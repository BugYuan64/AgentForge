"""Exercise the M6 runner against a real, locally available Docker daemon."""

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from scripts.create_todo_baseline import create_baseline

from agentforge.container_execution.runner import ContainerTestRunner, RunState
from agentforge.workspace_management.manager import WorkspaceManager, WorkspaceRecord

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TODO_FIXTURE = PROJECT_ROOT / "examples" / "todo_fixture"
IMAGE = "agentforge-todo-test:m6"
BUILD_COMMAND = (
    "docker build -t agentforge-todo-test:m6 "
    "-f containers/todo-test/Dockerfile examples/todo_fixture"
)


def _docker(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=10,
    )


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def _source_snapshot(source: Path) -> tuple[str, str]:
    return (
        _git(source, "rev-parse", "HEAD"),
        _git(source, "status", "--porcelain=v1", "--untracked-files=all"),
    )


@pytest.fixture(scope="module")
def docker_image() -> str:
    """Only an absent daemon skips; an available daemon requires the M6 image."""
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is not installed; real M6 integration requires Docker")
    try:
        daemon = _docker("info", "--format", "{{.ServerVersion}}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"Docker daemon is unavailable: {exc}")
    if daemon.returncode != 0:
        pytest.skip(f"Docker daemon is unavailable: {daemon.stderr.strip()}")

    try:
        image = _docker("image", "inspect", "--format", "{{.Id}}", IMAGE)
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"Docker image inspection timed out: {exc}", pytrace=False)
    if image.returncode != 0 or not image.stdout.strip():
        pytest.fail(
            f"Required local image {IMAGE} is missing. From {PROJECT_ROOT}, run: "
            f"{BUILD_COMMAND}",
            pytrace=False,
        )
    return IMAGE


@pytest.fixture
def workspace(
    tmp_path: Path, docker_image: str
) -> Iterator[tuple[WorkspaceManager, WorkspaceRecord]]:
    del docker_image
    source = tmp_path / "source"
    commit = create_baseline(TODO_FIXTURE, source)
    manager = WorkspaceManager(source, tmp_path / "workspaces", commit)
    record = manager.create()
    yield manager, record
    if record.path.is_dir() and not manager.get(record.id).has_changes:
        manager.remove(record.id)


def test_fixed_baseline_returns_real_failure_and_preserves_source(
    workspace: tuple[WorkspaceManager, WorkspaceRecord],
) -> None:
    manager, record = workspace
    before = _source_snapshot(manager.source_repository)

    result = ContainerTestRunner(manager).run(record.id)

    assert result.state is RunState.COMPLETED
    assert result.exit_code == 1
    assert result.error is None
    assert result.image_id is not None
    assert result.log_path.is_file()
    log = result.log_path.read_text(encoding="utf-8")
    assert "test_get_missing_todo_returns_404" in log
    assert "1 failed" in log
    assert "4 passed" in log
    assert _source_snapshot(manager.source_repository) == before
    assert _git(record.path, "rev-parse", "HEAD") == record.baseline_commit
    assert not manager.get(record.id).has_changes


def test_candidate_cannot_write_workspace_or_receive_model_key(
    workspace: tuple[WorkspaceManager, WorkspaceRecord], monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, record = workspace
    before = _source_snapshot(manager.source_repository)
    candidate_tests = record.path / "tests" / "test_todos.py"
    original = candidate_tests.read_bytes()
    candidate_tests.write_bytes(
        original + b"""

def test_m6_container_policy() -> None:
    import os
    from pathlib import Path

    import pytest

    assert os.geteuid() == 65534
    assert "OPENAI_API_KEY" not in os.environ
    with pytest.raises(OSError):
        (Path("/workspace") / ".m6-write-probe").write_text("not allowed", encoding="utf-8")
"""
    )
    monkeypatch.setenv("OPENAI_API_KEY", "m6-integration-canary")
    try:
        result = ContainerTestRunner(manager).run(record.id)
        assert result.state is RunState.COMPLETED
        assert result.exit_code == 1
        assert result.error is None
        log = result.log_path.read_text(encoding="utf-8")
        assert "1 failed" in log
        assert "5 passed" in log
        assert "test_get_missing_todo_returns_404" in log
        assert _source_snapshot(manager.source_repository) == before
    finally:
        candidate_tests.write_bytes(original)


def test_timeout_removes_container_and_preserves_source(
    workspace: tuple[WorkspaceManager, WorkspaceRecord],
) -> None:
    manager, record = workspace
    before = _source_snapshot(manager.source_repository)
    candidate_tests = record.path / "tests" / "test_todos.py"
    original = candidate_tests.read_bytes()
    candidate_tests.write_bytes(
        original + b"""

def test_m6_deliberate_timeout() -> None:
    import time

    time.sleep(15)
"""
    )
    try:
        result = ContainerTestRunner(manager, timeout_seconds=2).run(record.id)
        assert result.state is RunState.TIMED_OUT
        assert result.exit_code is None
        assert result.log_path.is_file()
        assert "state=timed_out" in result.log_path.read_text(encoding="utf-8")
        containers = _docker("ps", "--all", "--format", "{{.Names}}")
        assert containers.returncode == 0, containers.stderr
        assert f"agentforge-m6-{result.run_id}" not in containers.stdout.splitlines()
        assert _source_snapshot(manager.source_repository) == before
    finally:
        candidate_tests.write_bytes(original)
