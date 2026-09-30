"""M6 runs one fixed test command without exposing the source repository."""

import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
from scripts.create_todo_baseline import create_baseline

FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "todo_fixture"


def fake_docker(tmp_path: Path, **settings: object) -> tuple[tuple[str, ...], Path]:
    """Run a small process in place of the unavailable external Docker daemon."""
    state_path = tmp_path / "docker-state.json"
    state_path.write_text(json.dumps({"calls": [], "exists": False, **settings}), encoding="utf-8")
    script = tmp_path / "fake_docker.py"
    script.write_text(
        dedent("""\
            import json
            import sys
            import time
            from pathlib import Path

            path = Path(sys.argv[1])
            args = sys.argv[2:]
            state = json.loads(path.read_text(encoding="utf-8"))
            state["calls"].append(args)

            def save():
                path.write_text(json.dumps(state), encoding="utf-8")

            if args[:2] == ["image", "inspect"]:
                if state.get("image_error"):
                    print("image or daemon unavailable", file=sys.stderr)
                    save()
                    sys.exit(1)
                print("sha256:" + "a" * 64)
            elif args[0] == "create":
                state["exists"] = True
                if state.get("create_error_after_create"):
                    print("daemon connection lost after create", file=sys.stderr)
                    save()
                    sys.exit(1)
                print("container-123")
            elif args[0] == "start":
                state["running"] = True
                print("container-123")
            elif args[0] == "wait":
                save()
                time.sleep(state.get("wait_sleep", 0))
                state["running"] = False
                print(state.get("test_exit", 1))
            elif args[0] == "logs":
                print(state.get("test_log", "4 passed, 1 failed"))
            elif args[0] == "kill":
                state["running"] = False
            elif args[:2] == ["rm", "-f"]:
                state["running"] = False
                state["exists"] = False
            else:
                print("unexpected docker command", args, file=sys.stderr)
                save()
                sys.exit(2)
            save()
            """),
        encoding="utf-8",
    )
    return (sys.executable, str(script), str(state_path)), state_path


def create_workspace(tmp_path: Path):
    from agentforge.workspace_management.manager import WorkspaceManager

    source = tmp_path / "source"
    commit = create_baseline(FIXTURE, source)
    manager = WorkspaceManager(source, tmp_path / "workspaces", commit)
    return manager, manager.create()


def test_fixed_todo_command_uses_only_a_constrained_candidate_mount(tmp_path: Path) -> None:
    from agentforge.container_execution.runner import ContainerTestRunner, RunState

    manager, workspace = create_workspace(tmp_path)
    docker_command, state_path = fake_docker(tmp_path)

    result = ContainerTestRunner(manager, docker_command=docker_command).run(workspace.id)

    assert result.state is RunState.COMPLETED
    assert result.exit_code == 1
    assert "4 passed, 1 failed" in result.log_path.read_text(encoding="utf-8")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert not state["exists"]
    create = next(call for call in state["calls"] if call[0] == "create")
    assert create[-9:] == [
        "python", "-m", "pytest", "-q", "-W", "error", "-p", "no:cacheprovider",
        "tests/test_todos.py",
    ]
    mount = create[create.index("--mount") + 1]
    assert f"source={workspace.path}" in mount
    assert "target=/workspace" in mount
    assert "readonly" in mount
    assert str(manager.source_repository) not in " ".join(create)
    assert "docker.sock" not in " ".join(create)
    assert manager.source_repository not in result.log_path.parents
    assert workspace.path not in result.log_path.parents
    for option in (
        "--user", "--network", "--read-only", "--cap-drop", "--cpus", "--memory",
        "--memory-swap", "--pids-limit", "--tmpfs", "--security-opt",
    ):
        assert option in create
    assert create[create.index("--user") + 1] == "65534:65534"
    assert create[create.index("--network") + 1] == "none"
    assert create[create.index("--cpus") + 1] == "1"
    assert create[create.index("--memory") + 1] == "512m"


def test_docker_unavailable_keeps_diagnostic_log(tmp_path: Path) -> None:
    from agentforge.container_execution.runner import ContainerTestRunner, RunState

    manager, workspace = create_workspace(tmp_path)
    docker_command, state_path = fake_docker(tmp_path, image_error=True)

    result = ContainerTestRunner(manager, docker_command=docker_command).run(workspace.id)

    assert result.state is RunState.INFRASTRUCTURE_ERROR
    assert result.exit_code is None
    assert "image or daemon unavailable" in result.log_path.read_text(encoding="utf-8")
    calls = json.loads(state_path.read_text(encoding="utf-8"))["calls"]
    assert len(calls) == 1
    assert calls[0][:2] == ["image", "inspect"]


def test_failed_create_cleans_container_by_its_known_name(tmp_path: Path) -> None:
    from agentforge.container_execution.runner import ContainerTestRunner, RunState

    manager, workspace = create_workspace(tmp_path)
    docker_command, state_path = fake_docker(tmp_path, create_error_after_create=True)

    result = ContainerTestRunner(manager, docker_command=docker_command).run(workspace.id)

    assert result.state is RunState.INFRASTRUCTURE_ERROR
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert not state["exists"]
    assert any(call[:2] == ["rm", "-f"] for call in state["calls"])
    assert "daemon connection lost after create" in result.log_path.read_text(encoding="utf-8")


def test_timeout_kills_and_removes_container_with_partial_log(tmp_path: Path) -> None:
    from agentforge.container_execution.runner import ContainerTestRunner, RunState

    manager, workspace = create_workspace(tmp_path)
    docker_command, state_path = fake_docker(tmp_path, wait_sleep=2)

    result = ContainerTestRunner(
        manager, timeout_seconds=0.2, docker_command=docker_command
    ).run(workspace.id)

    assert result.state is RunState.TIMED_OUT
    assert result.exit_code is None
    assert "4 passed, 1 failed" in result.log_path.read_text(encoding="utf-8")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert not state["exists"]
    assert not state["running"]
    assert [call[0] for call in state["calls"]][-3:] == ["kill", "logs", "rm"]


def test_changed_candidate_can_run_without_touching_source(tmp_path: Path) -> None:
    from agentforge.container_execution.runner import ContainerTestRunner, RunState

    manager, workspace = create_workspace(tmp_path)
    candidate_file = workspace.path / "todo_app" / "main.py"
    candidate_file.write_text(
        candidate_file.read_text(encoding="utf-8") + "\n# candidate\n", encoding="utf-8"
    )
    docker_command, _ = fake_docker(tmp_path)

    result = ContainerTestRunner(manager, docker_command=docker_command).run(workspace.id)

    assert result.state is RunState.COMPLETED
    assert manager.get(workspace.id).has_changes
    status = subprocess.run(
        ["git", "-C", str(manager.source_repository), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    )
    assert status.stdout == ""


def test_removed_workspace_is_rejected_before_docker(tmp_path: Path) -> None:
    from agentforge.container_execution.runner import ContainerTestRunner
    from agentforge.workspace_management.manager import WorkspaceError

    manager, workspace = create_workspace(tmp_path)
    manager.remove(workspace.id)
    docker_command, state_path = fake_docker(tmp_path)

    with pytest.raises(WorkspaceError, match="not active"):
        ContainerTestRunner(manager, docker_command=docker_command).run(workspace.id)

    assert json.loads(state_path.read_text(encoding="utf-8"))["calls"] == []
