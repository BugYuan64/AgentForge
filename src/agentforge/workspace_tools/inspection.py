"""Bounded candidate status, baseline diffs and fixed container tests."""

import codecs
import difflib
import os
import re
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Thread
from time import monotonic

from agentforge.container_execution.runner import ContainerTestRunner, RunState
from agentforge.workspace_management.manager import WorkspaceError, WorkspaceManager, WorkspaceState
from agentforge.workspace_tools.contracts import ToolLimits, ToolRequest, ToolResult, ToolStatus
from agentforge.workspace_tools.paths import (
    PathRejected,
    checked_path,
    is_link,
    normalize_relative_path,
)

GIT_TIMEOUT_SECONDS = 15.0


class _GitError(RuntimeError):
    pass


@dataclass
class _Output:
    limit: int
    parts: list[str] = field(default_factory=list)
    length: int = 0
    truncated: bool = False

    def append(self, text: str) -> None:
        remaining = self.limit - self.length
        self.parts.append(text[:remaining])
        self.length += min(len(text), remaining)
        self.truncated |= len(text) > remaining

    @property
    def text(self) -> str:
        return "".join(self.parts)


def _git(root: Path, *arguments: str, limit: int) -> tuple[str, bool]:
    """Drain stdout incrementally, stopping Git on the time or output budget."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
        GIT_PAGER="cat",
    )
    command = [
        "git",
        "-C",
        str(root),
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "core.quotePath=false",
        *arguments,
    ]
    output = _Output(limit)
    overflow = Event()
    reader_errors: list[OSError] = []
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
    ) as process:

        def read_output() -> None:
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            try:
                while chunk := process.stdout.read1(4096):
                    if not output.truncated:
                        output.append(decoder.decode(chunk))
                        if output.truncated:
                            overflow.set()
                if not output.truncated:
                    output.append(decoder.decode(b"", final=True))
                    if output.truncated:
                        overflow.set()
            except OSError as exc:
                reader_errors.append(exc)

        reader = Thread(target=read_output, daemon=True)
        reader.start()
        deadline = monotonic() + GIT_TIMEOUT_SECONDS
        timed_out = False
        while process.poll() is None:
            remaining = deadline - monotonic()
            if overflow.is_set() or remaining <= 0:
                timed_out = remaining <= 0 and not overflow.is_set()
                process.kill()
                break
            overflow.wait(min(0.01, remaining))
        process.wait()
        reader.join(timeout=1)
        if reader.is_alive():
            raise _GitError("Git output reader did not finish")
        if timed_out:
            raise _GitError("Git operation exceeded the time limit")
        if reader_errors:
            raise reader_errors[0]
        if process.returncode != 0 and not output.truncated:
            raise _GitError(
                output.text.strip() or f"Git operation failed (exit {process.returncode})"
            )
    return output.text, output.truncated


class InspectionTools:
    def __init__(
        self,
        manager: WorkspaceManager,
        limits: ToolLimits | None = None,
        test_runner: ContainerTestRunner | None = None,
    ) -> None:
        self.workspace_manager = manager
        self.limits = limits or ToolLimits()
        self.test_runner = test_runner or ContainerTestRunner(manager)

    def _preflight(self, root: Path) -> None:
        """Check every candidate entry before letting Git inspect its working tree."""
        pending = [checked_path(root, ".")]
        seen = 0
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name.casefold() == ".git":
                        if directory == root:
                            continue
                        raise PathRejected("nested Git metadata is not accessible")
                    seen += 1
                    if seen > self.limits.max_entries:
                        raise PathRejected("workspace exceeds the safe entry inspection limit")
                    child = Path(entry.path)
                    relative = normalize_relative_path(child.relative_to(root).as_posix())
                    checked_path(root, relative)
                    info = child.lstat()
                    if is_link(info):
                        raise PathRejected("workspace contains links or reparse points")
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(child)
                    elif not stat.S_ISREG(info.st_mode):
                        raise PathRejected("workspace contains a non-regular file")
                    elif info.st_nlink != 1:
                        raise PathRejected("workspace contains hardlinked files")

    def _diff(self, root: Path) -> tuple[str, bool, tuple[str, ...]]:
        output = _Output(self.limits.max_output_chars)
        tracked, truncated = _git(
            root,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--ignore-submodules=all",
            self.workspace_manager.baseline_commit,
            "--",
            limit=self.limits.max_output_chars,
        )
        output.append(tracked)
        output.truncated |= truncated
        notices: dict[str, int] = {}
        if not output.truncated:
            names, names_truncated = _git(
                root,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                limit=self.limits.max_entries * 1025,
            )
            if names_truncated:
                notices["entry_limit"] = 1
            read_bytes = 0
            for name in names.split("\x00")[:-1]:
                relative = normalize_relative_path(name)
                file = checked_path(root, relative)
                info = file.lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise PathRejected("untracked diff requires regular files")
                if info.st_size > self.limits.max_file_bytes:
                    notices["skipped_large_files"] = notices.get("skipped_large_files", 0) + 1
                    continue
                budget = self.limits.max_search_bytes - read_bytes
                if info.st_size > budget:
                    notices["search_byte_limit"] = 1
                    break
                with file.open("rb") as stream:
                    data = stream.read(min(self.limits.max_file_bytes, budget) + 1)
                if len(data) > self.limits.max_file_bytes or len(data) > budget:
                    notices["search_byte_limit"] = 1
                    break
                read_bytes += len(data)
                try:
                    if b"\x00" in data:
                        raise UnicodeError
                    text = data.decode("utf-8")
                except UnicodeError:
                    notices["skipped_non_text"] = notices.get("skipped_non_text", 0) + 1
                    continue
                output.append(f"diff --git a/{relative} b/{relative}\nnew file mode 100644\n")
                # Git counts LF-delimited lines; Unicode separators are file content.
                parts = text.split("\n")
                text_lines = [part + "\n" for part in parts[:-1]]
                if parts[-1]:
                    text_lines.append(parts[-1])
                for line in difflib.unified_diff(
                    [],
                    text_lines,
                    fromfile="/dev/null",
                    tofile=f"b/{relative}",
                ):
                    output.append(line)
                    if not line.endswith("\n"):
                        output.append("\n\\ No newline at end of file\n")
                    if output.truncated:
                        break
                if output.truncated:
                    break
        if output.truncated:
            notices["output_limit"] = 1
        labels = tuple(
            name if name.endswith("_limit") else f"{name}={count}"
            for name, count in sorted(notices.items())
        )
        return output.text, output.truncated or bool(notices), labels

    def _tests(self, request: ToolRequest) -> ToolResult:
        run = self.test_runner.run(request.workspace_id)
        with run.log_path.open("rb") as stream:
            raw = stream.read(self.limits.max_output_chars * 4 + 1)
        text = raw.decode("utf-8", errors="replace")
        output = text[: self.limits.max_output_chars]
        truncated = len(text) > self.limits.max_output_chars
        error = run.error
        status = ToolStatus.COMPLETED if run.state is RunState.COMPLETED else ToolStatus.ERROR
        if status is ToolStatus.ERROR and error is None:
            error = f"test execution ended with state {run.state.value}"
        notices = ["output_limit"] if truncated else []
        if error is not None and len(error) > self.limits.max_output_chars:
            error = error[: self.limits.max_output_chars]
            truncated = True
            notices.append("error_limit")
        return ToolResult(
            request.tool,
            request.workspace_id,
            ".",
            status,
            output,
            truncated,
            tuple(notices),
            error,
            {
                "run_id": run.run_id,
                "image_id": run.image_id,
                "state": run.state.value,
                "exit_code": run.exit_code,
                "elapsed_seconds": run.elapsed_seconds,
                "log_path": str(run.log_path),
            },
        )

    def execute(self, request: ToolRequest) -> ToolResult:
        tool = request.tool[:64] if isinstance(request.tool, str) else ""
        workspace_id = request.workspace_id[:64] if isinstance(request.workspace_id, str) else ""
        path = request.path[:1024] if isinstance(request.path, str) else ""

        def failure(status: ToolStatus, error: str) -> ToolResult:
            truncated = len(error) > self.limits.max_output_chars
            return ToolResult(
                tool,
                workspace_id,
                path,
                status,
                truncated=truncated,
                notices=("error_limit",) if truncated else (),
                error=error[: self.limits.max_output_chars],
            )

        try:
            if not isinstance(request.tool, str) or request.tool not in {
                "status",
                "diff",
                "run_tests",
            }:
                raise PathRejected("unknown inspection tool")
            if request.path != "." or request.query is not None or request.patch is not None:
                raise PathRejected("inspection tools require path '.' with no query or patch")
            if not isinstance(request.workspace_id, str) or not re.fullmatch(
                r"[0-9a-f]{32}",
                request.workspace_id,
            ):
                raise PathRejected("workspace id must be 32 lowercase hexadecimal characters")
            expected_root = self.workspace_manager.workspaces_directory / request.workspace_id
            try:
                expected_root.lstat()
            except FileNotFoundError:
                pass
            else:
                checked_path(expected_root, ".")
            record = self.workspace_manager.get(request.workspace_id, inspect_changes=False)
            if record.state is not WorkspaceState.ACTIVE:
                raise PathRejected("workspace is not active")
            root = checked_path(record.path, ".")
            self._preflight(root)
            if request.tool == "run_tests":
                return self._tests(request)
            if request.tool == "status":
                output, truncated = _git(
                    root,
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                    limit=self.limits.max_output_chars,
                )
                notices = ("output_limit",) if truncated else ()
            else:
                output, truncated, notices = self._diff(root)
            return ToolResult(
                tool,
                workspace_id,
                ".",
                ToolStatus.COMPLETED,
                output,
                truncated,
                notices,
            )
        except (PathRejected, WorkspaceError, KeyError, ValueError) as exc:
            return failure(ToolStatus.REJECTED, str(exc))
        except (OSError, _GitError) as exc:
            return failure(ToolStatus.ERROR, str(exc))
