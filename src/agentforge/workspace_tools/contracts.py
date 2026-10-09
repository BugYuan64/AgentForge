"""Shared requests, outcomes and host-controlled limits for workspace tools."""

from dataclasses import asdict, dataclass
from enum import StrEnum


class ToolStatus(StrEnum):
    COMPLETED = "completed"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ToolRequest:
    tool: str
    workspace_id: str
    path: str = "."
    query: str | None = None
    patch: str | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool: str
    workspace_id: str
    path: str
    status: ToolStatus
    output: str = ""
    truncated: bool = False
    notices: tuple[str, ...] = ()
    error: str | None = None
    details: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        data["notices"] = list(self.notices)
        if self.details is None:
            data.pop("details")
        return data


@dataclass(frozen=True, slots=True)
class ToolLimits:
    max_output_chars: int = 12_000
    max_file_bytes: int = 256 * 1024
    max_entries: int = 2_000
    max_search_bytes: int = 4 * 1024 * 1024
    max_patch_bytes: int = 256 * 1024
    max_patch_files: int = 20

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
