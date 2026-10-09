"""Strict text patches with host-defined write scope and ordinary-error rollback."""

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agentforge.workspace_management.manager import WorkspaceError, WorkspaceManager, WorkspaceState
from agentforge.workspace_tools.contracts import ToolLimits, ToolRequest, ToolResult, ToolStatus
from agentforge.workspace_tools.paths import PathRejected, checked_path, normalize_relative_path


@dataclass(frozen=True, slots=True)
class WritePolicy:
    allowed_paths: tuple[str, ...] = ("todo_app",)

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_paths, tuple) or not self.allowed_paths:
            raise ValueError("allowed_paths must be a nonempty tuple")
        object.__setattr__(
            self,
            "allowed_paths",
            tuple(normalize_relative_path(path) for path in self.allowed_paths),
        )

    def permits(self, path: str) -> bool:
        path = path.casefold() if os.name == "nt" else path
        for prefix in self.allowed_paths:
            prefix = prefix.casefold() if os.name == "nt" else prefix
            if prefix == "." or path == prefix or path.startswith(prefix + "/"):
                return True
        return False


@dataclass(frozen=True)
class _Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    before: tuple[str, ...]
    after: tuple[str, ...]


@dataclass(frozen=True)
class _Patch:
    name: str
    create: bool
    delete: bool
    hunks: tuple[_Hunk, ...]


@dataclass(frozen=True)
class _Change:
    name: str
    path: Path
    before: bytes | None
    after: bytes | None
    mode: int


def _lines(text: str) -> list[str]:
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _header(line: str, prefix: str) -> str | None:
    name = line[4:].rstrip("\r\n").split("\t", 1)[0]
    if name == "/dev/null":
        return None
    if not name.startswith(prefix + "/"):
        raise PathRejected("patch paths must use a/ and b/ prefixes or /dev/null")
    name = normalize_relative_path(name[2:])
    if name == ".":
        raise PathRejected("patch target must be a file")
    return name


def _parse(text: str, limits: ToolLimits) -> list[_Patch]:
    if not isinstance(text, str) or not text or len(text) > limits.max_patch_bytes:
        raise PathRejected("patch must be a nonempty text within the patch byte limit")
    if "\x00" in text or len(text.encode("utf-8")) > limits.max_patch_bytes:
        raise PathRejected("binary or oversized patches are not supported")
    lines = _lines(text)
    patches: list[_Patch] = []
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        modes: set[str] = set()
        metadata = False
        while index < len(lines) and not lines[index].startswith("--- "):
            line = lines[index].rstrip("\r\n")
            metadata |= bool(line)
            if (
                not line
                or line.startswith("diff --git ")
                or re.fullmatch(r"index [0-9a-f]+\.\.[0-9a-f]+(?: 100(?:644|755))?", line)
            ):
                pass
            elif line == "new file mode 100644":
                modes.add("create")
            elif line in {"deleted file mode 100644", "deleted file mode 100755"}:
                modes.add("delete")
            else:
                raise PathRejected("unsupported patch metadata or malformed file section")
            index += 1
        if index == len(lines):
            if metadata:
                raise PathRejected("patch metadata has no file content")
            break
        old = _header(lines[index], "a")
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise PathRejected("patch file header is missing +++")
        new = _header(lines[index], "b")
        index += 1
        if (old is None and new is None) or (old is not None and new is not None and old != new):
            raise PathRejected("renames and empty file targets are not supported")
        name = new or old
        key = name.casefold()
        if key in seen or len(patches) >= limits.max_patch_files:
            raise PathRejected("duplicate patch target or patch file limit exceeded")
        seen.add(key)
        if ("create" in modes and old is not None) or ("delete" in modes and new is not None):
            raise PathRejected("patch mode metadata does not match file operation")
        hunks: list[_Hunk] = []
        while index < len(lines) and lines[index].startswith("@@"):
            match = re.fullmatch(
                r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\r\n]*(?:\r?\n)?",
                lines[index],
            )
            if match is None:
                raise PathRejected("invalid unified hunk header")
            old_start, old_count, new_start, new_count = (
                int(match[1]),
                int(match[2] or 1),
                int(match[3]),
                int(match[4] or 1),
            )
            index += 1
            before: list[str] = []
            after: list[str] = []
            last_kind: str | None = None
            marked = False
            while index < len(lines):
                line = lines[index]
                if line.rstrip("\r\n") == "\\ No newline at end of file":
                    if last_kind is None or marked:
                        raise PathRejected("misplaced no-newline marker")
                    if last_kind in {" ", "-"}:
                        before[-1] = before[-1].removesuffix("\n").removesuffix("\r")
                    if last_kind in {" ", "+"}:
                        after[-1] = after[-1].removesuffix("\n").removesuffix("\r")
                    marked = True
                    index += 1
                    continue
                if len(before) == old_count and len(after) == new_count:
                    break
                if not line.endswith("\n") or line[0] not in " +-":
                    raise PathRejected("invalid hunk content or line counts")
                last_kind, marked = line[0], False
                if last_kind in {" ", "-"}:
                    before.append(line[1:])
                if last_kind in {" ", "+"}:
                    after.append(line[1:])
                if len(before) > old_count or len(after) > new_count:
                    raise PathRejected("hunk content exceeds declared counts")
                index += 1
            if len(before) != old_count or len(after) != new_count:
                raise PathRejected("incomplete hunk content")
            hunks.append(
                _Hunk(old_start, old_count, new_start, new_count, tuple(before), tuple(after))
            )
        if not hunks:
            raise PathRejected("patch file has no text hunks")
        patches.append(_Patch(name, old is None, new is None, tuple(hunks)))
    if not patches:
        raise PathRejected("patch has no text file changes")
    return patches


def _apply(original: bytes, patch: _Patch) -> bytes:
    if b"\x00" in original:
        raise PathRejected("patch targets must be UTF-8 text")
    try:
        source = _lines(original.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise PathRejected("patch targets must be UTF-8 text") from exc
    result: list[str] = []
    cursor = 0
    for hunk in patch.hunks:
        start = hunk.old_start if hunk.old_count == 0 else hunk.old_start - 1
        if start < cursor or start > len(source):
            raise PathRejected("hunk positions overlap or exceed the original file")
        if tuple(source[start : start + hunk.old_count]) != hunk.before:
            raise PathRejected(f"patch context does not match: {patch.name}")
        result.extend(source[cursor:start])
        new_start = hunk.new_start if hunk.new_count == 0 else hunk.new_start - 1
        if new_start != len(result):
            raise PathRejected("new hunk position does not match accumulated changes")
        result.extend(hunk.after)
        cursor = start + hunk.old_count
    result.extend(source[cursor:])
    if any(not line.endswith("\n") for line in result[:-1]):
        raise PathRejected("no-newline marker must identify the final file line")
    content = "".join(result).encode("utf-8")
    if patch.delete and content:
        raise PathRejected("file deletion must remove all original content")
    return content


class ModificationTools:
    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        limits: ToolLimits | None = None,
        policy: WritePolicy | None = None,
    ) -> None:
        self.workspace_manager = workspace_manager
        self.limits = limits or ToolLimits()
        self.policy = policy or WritePolicy()

    def _snapshot(self, root: Path, name: str) -> tuple[Path, bytes | None, int]:
        path = checked_path(root, name, allow_missing=True)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return path, None, 0o644
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PathRejected("patch target must be a regular file without hard links")
        if info.st_size > self.limits.max_file_bytes:
            raise PathRejected("patch target exceeds the file byte limit")
        with path.open("rb") as stream:
            content = stream.read(self.limits.max_file_bytes + 1)
        if len(content) > self.limits.max_file_bytes:
            raise PathRejected("patch target exceeds the file byte limit")
        return path, content, stat.S_IMODE(info.st_mode)

    @staticmethod
    def _replace(path: Path, content: bytes, mode: int) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".agentforge-patch-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _commit(self, root: Path, changes: list[_Change]) -> dict[str, object]:
        applied: list[_Change] = []
        created_directories: list[Path] = []
        try:
            for change in changes:
                _, current, _ = self._snapshot(root, change.name)
                if current != change.before:
                    raise PathRejected("candidate content changed after patch validation")
                for parent in reversed(change.path.parent.parents):
                    if parent != root and not parent.is_relative_to(root):
                        continue
                    checked_path(root, parent.relative_to(root).as_posix(), allow_missing=True)
                    if not parent.exists():
                        parent.mkdir()
                        created_directories.append(parent)
                parent = change.path.parent
                checked_path(root, parent.relative_to(root).as_posix(), allow_missing=True)
                if not parent.exists():
                    parent.mkdir()
                    created_directories.append(parent)
                if change.after is None:
                    change.path.unlink()
                else:
                    self._replace(change.path, change.after, change.mode)
                applied.append(change)
        except (OSError, PathRejected) as exc:
            failed: list[str] = []
            for change in reversed(applied):
                try:
                    checked_path(root, change.name, allow_missing=True)
                    if change.before is None:
                        change.path.unlink(missing_ok=True)
                    else:
                        self._replace(change.path, change.before, change.mode)
                except (OSError, PathRejected):
                    failed.append(change.name)
            for directory in reversed(created_directories):
                try:
                    directory.rmdir()
                except OSError:
                    failed.append(directory.relative_to(root).as_posix())
            detail = "rollback incomplete: " + ", ".join(failed) if failed else "rollback complete"
            raise OSError(f"patch write failed ({exc}); {detail}") from exc
        return {"changed_paths": [change.name for change in changes]}

    def execute(self, request: ToolRequest) -> ToolResult:
        workspace_id = request.workspace_id[:64] if isinstance(request.workspace_id, str) else ""
        try:
            if not isinstance(request.workspace_id, str) or not re.fullmatch(
                r"[0-9a-f]{32}", request.workspace_id
            ):
                raise PathRejected("workspace id must be 32 lowercase hexadecimal characters")
            if request.tool != "apply_patch" or request.path != "." or request.query is not None:
                raise PathRejected("apply_patch accepts only workspace id and patch text")
            parsed = _parse(request.patch, self.limits)
            for patch in parsed:
                if not self.policy.permits(patch.name):
                    raise PathRejected(
                        f"patch target is outside the host write scope: {patch.name}"
                    )
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
            checked_path(record.path, ".")
            changes: list[_Change] = []
            for patch in parsed:
                path, original, mode = self._snapshot(record.path, patch.name)
                if patch.create != (original is None):
                    raise PathRejected("create target exists or edit/delete target is missing")
                proposed = _apply(original or b"", patch)
                if len(proposed) > self.limits.max_file_bytes:
                    raise PathRejected("patched content exceeds the file byte limit")
                changes.append(
                    _Change(patch.name, path, original, None if patch.delete else proposed, mode)
                )
            details = self._commit(record.path, changes)
            output = f"applied {len(changes)} file(s)"
            truncated = len(output) > self.limits.max_output_chars
            return ToolResult(
                "apply_patch",
                workspace_id,
                ".",
                ToolStatus.COMPLETED,
                output=output[: self.limits.max_output_chars],
                truncated=truncated,
                notices=("output_limit",) if truncated else (),
                details=details,
            )
        except (ValueError, KeyError, WorkspaceError) as exc:
            status, error = ToolStatus.REJECTED, str(exc)
        except OSError as exc:
            status, error = ToolStatus.ERROR, str(exc)
        truncated = len(error) > self.limits.max_output_chars
        return ToolResult(
            "apply_patch",
            workspace_id,
            ".",
            status,
            truncated=truncated,
            notices=("error_limit",) if truncated else (),
            error=error[: self.limits.max_output_chars],
        )
