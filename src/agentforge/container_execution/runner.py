"""Run one fixed Todo test command inside a constrained Docker container."""

import math
import re
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from time import monotonic
from uuid import uuid4

from agentforge.workspace_management.manager import (
    WorkspaceError,
    WorkspaceManager,
    WorkspaceRecord,
    WorkspaceState,
)

TEST_COMMAND = (
    "python", "-m", "pytest", "-q", "-W", "error", "-p", "no:cacheprovider",
    "tests/test_todos.py",
)
CONTROL_TIMEOUT_SECONDS = 15.0


class RunState(StrEnum):
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


@dataclass(frozen=True, slots=True)
class TestRunResult:
    run_id: str
    workspace_id: str
    image_id: str | None
    state: RunState
    exit_code: int | None
    elapsed_seconds: float
    log_path: Path
    error: str | None = None

    def to_dict(self) -> dict[str, str | int | float | None]:
        """Return a JSON-compatible view for the local CLI."""
        data = asdict(self)
        data["state"] = self.state.value
        data["log_path"] = str(self.log_path)
        return data


class _DockerCommandError(RuntimeError):
    """A Docker control operation failed."""


class ContainerTestRunner:
    """Run the predetermined Todo check for one active M5 workspace."""

    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        image: str = "agentforge-todo-test:m6",
        timeout_seconds: float = 30.0,
        docker_command: Sequence[str] = ("docker",),
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        if not image or not docker_command:
            raise ValueError("Docker image and command must not be empty")
        self.workspace_manager = workspace_manager
        self.image = image
        self.timeout_seconds = timeout_seconds
        self._docker_command = tuple(docker_command)

    def _docker(self, *arguments: str, timeout: float = CONTROL_TIMEOUT_SECONDS) -> str:
        result = subprocess.run(
            [*self._docker_command, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise _DockerCommandError(
                f"docker {' '.join(arguments[:2])} failed (exit {result.returncode}): {detail}"
            )
        return result.stdout.strip()

    @staticmethod
    def _append(log_path: Path, message: str) -> None:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(message.rstrip() + "\n")

    def _collect_logs(self, container_id: str, log_path: Path) -> None:
        self._append(log_path, "\n--- container output ---")
        with log_path.open("a", encoding="utf-8") as log:
            result = subprocess.run(
                [*self._docker_command, "logs", container_id],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=CONTROL_TIMEOUT_SECONDS,
                check=False,
            )
        if result.returncode != 0:
            raise _DockerCommandError(f"docker logs failed (exit {result.returncode})")

    def _execution(self, workspace: WorkspaceRecord) -> tuple[Path, tuple[str, ...]]:
        """Select the protected execution source and fixed command."""
        return workspace.path, TEST_COMMAND

    def run(self, workspace_id: str) -> TestRunResult:
        """Run the fixed test; preserve its real exit code and a durable log."""
        workspace = self.workspace_manager.get(workspace_id, inspect_changes=False)
        if workspace.state is not WorkspaceState.ACTIVE:
            raise WorkspaceError(
                f"workspace is not active: {workspace_id} ({workspace.state.value})"
            )
        execution_path, command = self._execution(workspace)

        log_directory = self.workspace_manager.workspaces_directory / ".runs"
        source = self.workspace_manager.source_repository
        if source == log_directory or source in log_directory.parents:
            raise WorkspaceError("test logs must be outside the source repository")
        log_directory.mkdir(parents=True, exist_ok=True)
        run_id = uuid4().hex
        log_path = log_directory / f"{run_id}.log"
        container_name = f"agentforge-m6-{run_id}"
        started = monotonic()
        image_id: str | None = None
        container_id: str | None = None
        create_attempted = False
        state = RunState.INFRASTRUCTURE_ERROR
        exit_code: int | None = None
        error: str | None = None
        stage = "image inspect"
        self._append(
            log_path,
            f"run_id={run_id}\nworkspace_id={workspace_id}\ncommand={' '.join(command)}",
        )

        try:
            if "," in str(execution_path):
                raise _DockerCommandError("workspace path contains a comma unsupported by --mount")
            image_id = self._docker("image", "inspect", "--format", "{{.Id}}", self.image)
            if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
                raise _DockerCommandError(f"invalid local image ID: {image_id}")

            mount = f"type=bind,source={execution_path},target=/workspace,readonly"
            stage = "create"
            create_attempted = True
            container_id = self._docker(
                "create", "--name", container_name,
                "--user", "65534:65534", "--network", "none", "--read-only",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--cpus", "1", "--memory", "512m", "--memory-swap", "512m",
                "--pids-limit", "64", "--mount", mount,
                "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--workdir", "/workspace",
                "--env", "HOME=/tmp", "--env", "TMPDIR=/tmp",
                "--env", "PYTHONDONTWRITEBYTECODE=1",
                "--env", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                image_id, *command,
            )
            if not container_id:
                raise _DockerCommandError("docker create returned no container ID")

            stage = "start"
            self._docker("start", container_id)
            stage = "wait"
            try:
                wait_output = self._docker("wait", container_id, timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                state = RunState.TIMED_OUT
                error = f"test exceeded {self.timeout_seconds:g} seconds"
            else:
                try:
                    exit_code = int(wait_output)
                except ValueError as exc:
                    raise _DockerCommandError(
                        f"invalid docker wait exit code: {wait_output}"
                    ) from exc
                state = RunState.COMPLETED
        except (OSError, subprocess.TimeoutExpired, _DockerCommandError) as exc:
            error = f"Docker {stage}: {exc}"
        finally:
            if container_id is not None:
                if state is RunState.TIMED_OUT:
                    try:
                        self._docker("kill", container_id)
                    except (OSError, subprocess.TimeoutExpired, _DockerCommandError) as exc:
                        self._append(log_path, f"docker kill: {exc}")
                try:
                    self._collect_logs(container_id, log_path)
                except (OSError, subprocess.TimeoutExpired, _DockerCommandError) as exc:
                    state = RunState.INFRASTRUCTURE_ERROR
                    error = f"Docker logs: {exc}"
            if create_attempted:
                try:
                    self._docker("rm", "-f", container_id or container_name)
                except (OSError, subprocess.TimeoutExpired, _DockerCommandError) as exc:
                    state = RunState.INFRASTRUCTURE_ERROR
                    if container_id is None and error is not None:
                        self._append(log_path, f"docker cleanup by name: {exc}")
                    else:
                        error = f"Docker cleanup: {exc}"

        if error is not None:
            self._append(log_path, f"error={error}")
        self._append(log_path, f"state={state.value}\nexit_code={exit_code}")
        return TestRunResult(
            run_id=run_id,
            workspace_id=workspace_id,
            image_id=image_id,
            state=state,
            exit_code=exit_code,
            elapsed_seconds=round(monotonic() - started, 3),
            log_path=log_path,
            error=error,
        )
