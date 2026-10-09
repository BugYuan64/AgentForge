"""Create and retire Git worktrees from a fixed, local Todo baseline."""

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4


class WorkspaceError(RuntimeError):
    """A workspace operation cannot be completed safely."""


class SourceDirtyError(WorkspaceError):
    """The source repository contains uncommitted changes."""


class WorkspaceDirtyError(WorkspaceError):
    """The workspace contains candidate changes that must be preserved."""


class WorkspaceState(StrEnum):
    CREATING = "creating"
    ACTIVE = "active"
    FAILED = "failed"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class WorkspaceRecord:
    id: str
    source_repository: Path
    path: Path
    baseline_commit: str
    state: WorkspaceState
    created_at: str
    removed_at: str | None = None
    error: str | None = None
    has_changes: bool | None = False

    def to_dict(self) -> dict[str, str | bool | None]:
        """Return a JSON-compatible view for CLI output and records."""
        data = asdict(self)
        data["source_repository"] = str(self.source_repository)
        data["path"] = str(self.path)
        data["state"] = self.state.value
        return data


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _git(repository: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    for name in list(environment):
        if name in {
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_COMMON_DIR",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        } or name.startswith("GIT_CONFIG_"):
            environment.pop(name)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise WorkspaceError(
            f"Git {' '.join(arguments)} failed in {repository}: {detail}"
        ) from exc
    return result.stdout.strip()


class WorkspaceManager:
    """Manage one source repository's workspaces and durable lifecycle records."""

    def __init__(
        self, source_repository: Path, workspaces_directory: Path, baseline_commit: str
    ) -> None:
        self.source_repository = source_repository.resolve()
        self.workspaces_directory = workspaces_directory.resolve()
        self.baseline_commit = baseline_commit.strip().lower()

    def _record_path(self, workspace_id: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{32}", workspace_id) is None:
            raise ValueError("workspace id must be 32 lowercase hexadecimal characters")
        return self.workspaces_directory / ".records" / f"{workspace_id}.json"

    def _write_record(self, record: WorkspaceRecord) -> None:
        path = self._record_path(record.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _validate_source(self) -> None:
        if not self.source_repository.is_dir():
            raise WorkspaceError(f"source repository is missing: {self.source_repository}")
        actual_root = Path(_git(self.source_repository, "rev-parse", "--show-toplevel")).resolve()
        if actual_root != self.source_repository:
            raise WorkspaceError(f"source is not a Git repository root: {self.source_repository}")
        if re.fullmatch(r"[0-9a-f]{40}", self.baseline_commit) is None:
            raise WorkspaceError("baseline commit must be a full 40-character SHA-1 ID")
        try:
            kind = _git(self.source_repository, "cat-file", "-t", self.baseline_commit)
        except WorkspaceError as exc:
            raise WorkspaceError(f"baseline commit is unavailable: {self.baseline_commit}") from exc
        if kind != "commit":
            raise WorkspaceError(f"baseline object is not a commit: {self.baseline_commit}")
        if self.source_repository == self.workspaces_directory or (
            self.source_repository in self.workspaces_directory.parents
        ):
            raise WorkspaceError("workspaces directory must be outside the source repository")
        if _git(self.source_repository, "status", "--porcelain=v1", "--untracked-files=all"):
            raise SourceDirtyError(
                f"source repository has uncommitted changes: {self.source_repository}"
            )

    def create(self) -> WorkspaceRecord:
        """Create a detached worktree without incorporating source edits."""
        self._validate_source()
        workspace_id = uuid4().hex
        path = self.workspaces_directory / workspace_id
        if path.exists() or path.is_symlink() or self._record_path(workspace_id).exists():
            raise WorkspaceError(f"workspace path already exists: {path}")
        record = WorkspaceRecord(
            id=workspace_id,
            source_repository=self.source_repository,
            path=path,
            baseline_commit=self.baseline_commit,
            state=WorkspaceState.CREATING,
            created_at=_now(),
        )
        self._write_record(record)
        try:
            _git(self.source_repository, "worktree", "add", "--detach", str(path),
                 self.baseline_commit)
        except WorkspaceError as exc:
            self._write_record(replace(record, state=WorkspaceState.FAILED, error=str(exc)))
            raise
        active = replace(record, state=WorkspaceState.ACTIVE)
        try:
            self._write_record(active)
        except OSError as exc:
            raise WorkspaceError(
                f"workspace created at {path}, but lifecycle record update failed; "
                "inspect it manually"
            ) from exc
        return active

    def get(self, workspace_id: str, *, inspect_changes: bool = True) -> WorkspaceRecord:
        """Validate a saved workspace; optionally inspect its current change state.

        Identity-only callers receive has_changes=None rather than a claim that
        the candidate is clean. The default retains M5's full change inspection.
        """
        path = self._record_path(workspace_id)
        if not path.is_file():
            raise KeyError(f"unknown workspace id: {workspace_id}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            record = WorkspaceRecord(
                id=data["id"],
                source_repository=Path(data["source_repository"]),
                path=Path(data["path"]),
                baseline_commit=data["baseline_commit"],
                state=WorkspaceState(data["state"]),
                created_at=data["created_at"],
                removed_at=data["removed_at"],
                error=data["error"],
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise WorkspaceError(f"invalid lifecycle record: {path}") from exc
        if record.id != workspace_id or record.path != self.workspaces_directory / workspace_id:
            raise WorkspaceError(f"lifecycle record has an unexpected workspace path: {path}")
        if record.source_repository != self.source_repository:
            raise WorkspaceError(f"lifecycle record has an unexpected source repository: {path}")
        if record.baseline_commit != self.baseline_commit:
            raise WorkspaceError(f"lifecycle record has an unexpected baseline commit: {path}")
        if record.state is not WorkspaceState.ACTIVE:
            return record
        if not record.path.is_dir():
            raise WorkspaceError(f"active workspace is missing: {record.path}")
        actual_root = Path(_git(record.path, "rev-parse", "--show-toplevel")).resolve()
        if actual_root != record.path:
            raise WorkspaceError(f"workspace Git root changed: {record.path}")
        source_common = (self.source_repository / _git(
            self.source_repository, "rev-parse", "--git-common-dir"
        )).resolve()
        candidate_common = (record.path / _git(
            record.path, "rev-parse", "--git-common-dir"
        )).resolve()
        if source_common != candidate_common:
            raise WorkspaceError(f"workspace is no longer attached to source: {record.path}")
        if not inspect_changes:
            return replace(record, has_changes=None)
        changed = bool(_git(
            record.path, "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"
        ))
        changed |= _git(record.path, "rev-parse", "HEAD") != record.baseline_commit
        return replace(record, has_changes=changed)

    def remove(self, workspace_id: str) -> WorkspaceRecord:
        """Retire only a clean workspace that still points at its baseline."""
        record = self.get(workspace_id)
        if record.state is not WorkspaceState.ACTIVE:
            raise WorkspaceError(f"workspace is not active: {workspace_id} ({record.state.value})")
        if record.has_changes:
            raise WorkspaceDirtyError(
                f"workspace has candidate changes; refusing to remove: {record.path}"
            )
        _git(self.source_repository, "worktree", "remove", str(record.path))
        removed = replace(record, state=WorkspaceState.REMOVED, removed_at=_now())
        self._write_record(removed)
        return removed
