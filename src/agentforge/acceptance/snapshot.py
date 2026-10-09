"""Capture bounded file bytes and enforce the fixed Todo authority boundary."""

import hashlib
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agentforge.workspace_management.manager import WorkspaceError, WorkspaceManager, WorkspaceState
from agentforge.workspace_tools.contracts import ToolLimits
from agentforge.workspace_tools.paths import checked_path, normalize_relative_path

LIMITS = ToolLimits()


def _git(root: Path, *arguments: str, input_data: bytes | None = None) -> bytes:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
        GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
    )
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "-c", "core.fsmonitor=false", *arguments],
            env=environment, capture_output=True, timeout=15, check=True, input=input_data,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkspaceError(f"fixed Git inspection failed: {exc}") from exc
    return result.stdout


def content_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        path = name.encode("utf-8")
        digest.update(len(path).to_bytes(8, "big"))
        digest.update(path)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def fixed_files(manager: WorkspaceManager) -> dict[str, bytes]:
    """Read authority from the immutable Git object, never the mutable source tree."""
    if not re.fullmatch(r"[0-9a-f]{40}", manager.baseline_commit):
        raise ValueError("baseline commit must be a full 40-character SHA-1 ID")
    tree = _git(manager.source_repository, "ls-tree", "-r", "-l", "-z", manager.baseline_commit)
    if len(tree) > LIMITS.max_entries * 2048:
        raise ValueError("fixed tree exceeds inspection limit")
    files: dict[str, bytes] = {}
    blobs: list[tuple[str, bytes, int]] = []
    aliases: set[str] = set()
    total = 0
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, object_id, raw_size = metadata.split()
        name = normalize_relative_path(raw_name.decode("utf-8"))
        if mode not in {b"100644", b"100755"} or kind != b"blob":
            raise ValueError("fixed tree must contain only regular files")
        size = int(raw_size)
        total += size
        if (len(blobs) >= LIMITS.max_entries or size > LIMITS.max_file_bytes
                or total > LIMITS.max_search_bytes):
            raise ValueError("fixed files exceed byte or entry limit")
        if name.casefold() in aliases:
            raise ValueError("fixed tree contains a filename alias")
        aliases.add(name.casefold())
        blobs.append((name, object_id, size))
    # One bounded batch avoids a subprocess per file; all sizes were checked above.
    batch = _git(
        manager.source_repository, "cat-file", "--batch",
        input_data=b"".join(object_id + b"\n" for _, object_id, _ in blobs),
    )
    offset = 0
    for name, object_id, size in blobs:
        end = batch.find(b"\n", offset)
        if end < 0 or batch[offset:end].split() != [object_id, b"blob", str(size).encode()]:
            raise WorkspaceError("fixed blob metadata changed")
        start = end + 1
        data = batch[start:start + size]
        if len(data) != size or batch[start + size:start + size + 1] != b"\n":
            raise WorkspaceError("fixed blob size changed")
        files[name] = data
        offset = start + size + 1
    if offset != len(batch):
        raise WorkspaceError("fixed blob batch contains unexpected data")
    if "tests/test_todos.py" not in files or "todo_app/main.py" not in files:
        raise ValueError("fixed Todo authority is missing")
    return files


@dataclass(frozen=True)
class Snapshot:
    head: str
    digest: str
    files: dict[str, bytes]

    def write_to(self, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=False)
        for name, data in self.files.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)


def capture(
    manager: WorkspaceManager, workspace_id: str, fixed: dict[str, bytes], *,
    baseline: bool = False,
) -> Snapshot:
    # Check the expected root before Git follows any candidate filesystem link.
    if not isinstance(workspace_id, str) or not re.fullmatch(r"[0-9a-f]{32}", workspace_id):
        raise ValueError("workspace id must be 32 lowercase hexadecimal characters")
    root = manager.workspaces_directory / workspace_id
    if root.exists() or root.is_symlink():
        checked_path(root, ".")
    record = manager.get(workspace_id, inspect_changes=False)
    if record.state is not WorkspaceState.ACTIVE:
        raise ValueError("workspace is not active")
    root = checked_path(record.path, ".")
    files: dict[str, bytes] = {}
    aliases: set[str] = set()
    pending = [root]
    count = total = 0
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if directory == root and entry.name == ".git":
                    continue
                count += 1
                if count > LIMITS.max_entries:
                    raise ValueError("candidate exceeds entry limit")
                relative = normalize_relative_path(Path(entry.path).relative_to(root).as_posix())
                if relative.casefold() in aliases:
                    raise ValueError("candidate contains a filename alias")
                aliases.add(relative.casefold())
                path = checked_path(root, relative)
                info = path.lstat()
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("candidate contains a non-regular file")
                if info.st_nlink != 1:
                    raise ValueError("candidate contains a hardlink")
                if info.st_size > LIMITS.max_file_bytes:
                    raise ValueError("candidate exceeds file byte limit")
                with path.open("rb") as stream:
                    data = stream.read(LIMITS.max_file_bytes + 1)
                total += len(data)
                if len(data) > LIMITS.max_file_bytes or total > LIMITS.max_search_bytes:
                    raise ValueError("candidate exceeds byte limit")
                files[relative] = data
    for name in files.keys() | fixed.keys():
        if not name.startswith("todo_app/") and files.get(name) != fixed.get(name):
            raise ValueError(f"protected authority changed: {name}")
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    if baseline:
        if head != manager.baseline_commit:
            raise ValueError("baseline HEAD must equal the fixed commit")
        if files != fixed:
            raise ValueError("baseline must run before any candidate modification")
    return Snapshot(head, content_digest(files), files)
