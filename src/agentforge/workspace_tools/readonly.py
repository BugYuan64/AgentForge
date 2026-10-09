"""Bounded file reads within a stable, trusted M5 workspace."""

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from agentforge.workspace_management.manager import WorkspaceError, WorkspaceManager, WorkspaceState
from agentforge.workspace_tools.contracts import ToolLimits, ToolRequest, ToolResult, ToolStatus
from agentforge.workspace_tools.paths import (
    PathRejected as _Rejected,
)
from agentforge.workspace_tools.paths import (
    checked_path as _checked_path,
)
from agentforge.workspace_tools.paths import (
    is_link as _is_link,
)
from agentforge.workspace_tools.paths import (
    normalize_relative_path as _relative_path,
)


class _LargeFile(_Rejected):
    pass


class _SearchBudgetReached(Exception):
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


@dataclass
class _Files:
    paths: list[Path] = field(default_factory=list)
    notices: dict[str, int] = field(default_factory=dict)
    truncated: bool = False

    def note(self, name: str) -> None:
        self.notices[name] = self.notices.get(name, 0) + 1


class ReadOnlyWorkspaceTools:
    def __init__(
        self, workspace_manager: WorkspaceManager, limits: ToolLimits | None = None
    ) -> None:
        self.workspace_manager = workspace_manager
        self.limits = limits or ToolLimits()

    def _discover(self, root: Path, base: Path) -> _Files:
        files = _Files()
        if stat.S_ISREG(base.lstat().st_mode):
            files.paths.append(base)
            return files
        if not base.is_dir():
            raise _Rejected("path must identify a regular file or directory")
        pending = [base]
        seen = 0
        while pending:
            directory = pending.pop()
            directory = _checked_path(root, directory.relative_to(root).as_posix())
            children: list[Path] = []
            # Do not materialize or sort a potentially unbounded directory.
            with os.scandir(directory) as entries:
                for entry in entries:
                    seen += 1
                    if seen > self.limits.max_entries:
                        files.truncated = True
                        files.note("entry_limit")
                        break
                    if entry.name.casefold() == ".git":
                        continue
                    child = Path(entry.path)
                    if _is_link(child.lstat()):
                        files.note("skipped_links")
                        continue
                    try:
                        _relative_path(child.relative_to(root).as_posix())
                    except _Rejected:
                        files.note("skipped_special")
                        continue
                    info = child.lstat()
                    if stat.S_ISREG(info.st_mode):
                        files.paths.append(child)
                    elif stat.S_ISDIR(info.st_mode):
                        children.append(child)
                    else:
                        files.note("skipped_special")
            if files.truncated:
                break
            pending.extend(sorted(children, reverse=True))
        files.paths.sort()
        return files

    def _read_bytes(self, root: Path, path: Path, budget: int | None = None) -> bytes:
        path = _checked_path(root, path.relative_to(root).as_posix())
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise _Rejected("only regular files can be read")
        if info.st_size > self.limits.max_file_bytes:
            raise _LargeFile("file exceeds the configured byte limit")
        if budget is not None and info.st_size > budget:
            raise _SearchBudgetReached
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise _Rejected("only regular files can be read")
            if opened.st_size > self.limits.max_file_bytes:
                raise _LargeFile("file exceeds the configured byte limit")
            if budget is not None and opened.st_size > budget:
                raise _SearchBudgetReached
            cap = self.limits.max_file_bytes + 1
            data = stream.read(cap if budget is None else min(cap, budget))
        if len(data) > self.limits.max_file_bytes:
            raise _LargeFile("file exceeds the configured byte limit")
        return data

    @staticmethod
    def _text(data: bytes) -> str:
        if b"\x00" in data:
            raise _Rejected("file is not UTF-8 text")
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise _Rejected("file is not UTF-8 text") from exc

    def _run(
        self, request: ToolRequest, root: Path, path: Path
    ) -> tuple[str, bool, tuple[str, ...]]:
        output = _Output(self.limits.max_output_chars)
        if request.tool == "read_file":
            output.append(self._text(self._read_bytes(root, path)))
            return (
                "".join(output.parts),
                output.truncated,
                (("output_limit",) if output.truncated else ()),
            )
        if request.tool == "list_files" and not path.is_dir():
            raise _Rejected("list_files requires a directory")
        files = self._discover(root, path)
        read_bytes = 0
        for file in files.paths:
            relative = file.relative_to(root).as_posix()
            if request.tool == "list_files":
                output.append(relative + "\n")
            else:
                try:
                    data = self._read_bytes(root, file, self.limits.max_search_bytes - read_bytes)
                except _LargeFile:
                    files.note("skipped_large_files")
                    files.truncated = True
                    continue
                except _SearchBudgetReached:
                    files.note("search_byte_limit")
                    files.truncated = True
                    break
                read_bytes += len(data)
                try:
                    text = self._text(data)
                except _Rejected:
                    files.note("skipped_non_text")
                    continue
                for number, line in enumerate(text.splitlines(), 1):
                    if request.query in line:
                        output.append(f"{relative}:{number}:{line}\n")
                        if output.truncated:
                            break
            if output.truncated:
                files.note("output_limit")
                break
        notices = tuple(
            name if name.endswith("_limit") else f"{name}={count}"
            for name, count in sorted(files.notices.items())
        )
        return "".join(output.parts), files.truncated or output.truncated, notices

    def execute(self, request: ToolRequest) -> ToolResult:
        """Read a validated active workspace and return one uniform, bounded result."""
        path = request.path[:1024] if isinstance(request.path, str) else ""
        tool = request.tool[:64] if isinstance(request.tool, str) else ""
        workspace_id = request.workspace_id[:64] if isinstance(request.workspace_id, str) else ""

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
                "list_files",
                "read_file",
                "search",
            }:
                raise _Rejected("unknown read-only tool")
            path = _relative_path(request.path)
            if request.patch is not None:
                raise _Rejected("patch is only accepted for apply_patch")
            if not isinstance(request.workspace_id, str) or not re.fullmatch(
                r"[0-9a-f]{32}", request.workspace_id
            ):
                raise _Rejected("workspace id must be 32 lowercase hexadecimal characters")
            if request.tool == "search":
                if not isinstance(request.query, str) or not 1 <= len(request.query) <= 1024:
                    raise _Rejected("search query must contain 1 to 1024 characters")
                if any(c in request.query for c in "\r\n\x00\v\f\x1c\x1d\x1e\x85\u2028\u2029"):
                    raise _Rejected("search query must be a single-line literal")
            elif request.query is not None:
                raise _Rejected("query is only accepted for search")
            record = self.workspace_manager.get(request.workspace_id, inspect_changes=False)
            if record.state is not WorkspaceState.ACTIVE:
                raise _Rejected("workspace is not active")
            checked = _checked_path(record.path, path)
            output, truncated, notices = self._run(request, record.path, checked)
            return ToolResult(
                tool, workspace_id, path, ToolStatus.COMPLETED, output, truncated, notices
            )
        except (_Rejected, WorkspaceError, KeyError, ValueError) as exc:
            return failure(ToolStatus.REJECTED, str(exc))
        except OSError as exc:
            return failure(
                ToolStatus.ERROR, f"file operation failed: {exc.strerror or type(exc).__name__}"
            )
