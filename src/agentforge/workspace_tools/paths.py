"""Common relative-path and filesystem-link checks for stable workspaces."""

import os
import re
import stat
from pathlib import Path


class PathRejected(ValueError):
    pass


def normalize_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise PathRejected("path must be a nonempty relative string of at most 1024 characters")
    value = value.replace("\\", "/")
    if value == ".":
        return value
    if value.startswith("/") or any(c in ':<>"|?*\x85\u2028\u2029' or ord(c) < 32 for c in value):
        raise PathRejected("absolute, drive, UNC and special paths are not allowed")
    for part in value.split("/"):
        if part in {"", ".", ".."} or part.endswith((".", " ")):
            raise PathRejected("path contains a traversal or Windows filename alias")
        if part.casefold() == ".git":
            raise PathRejected("Git metadata is not accessible through workspace tools")
        device = part.partition(".")[0].rstrip(" ")
        if re.fullmatch(
            r"con|prn|aux|nul|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³]", device, re.IGNORECASE
        ):
            raise PathRejected("Windows device names are not allowed")
    return value


def is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def checked_path(root: Path, relative: str, *, allow_missing: bool = False) -> Path:
    relative = normalize_relative_path(relative)
    path = root
    if is_link(root.lstat()):
        raise PathRejected("workspace root must not be a link or reparse point")
    parts = [] if relative == "." else relative.split("/")
    for index, part in enumerate(parts):
        path = path / part
        try:
            info = path.lstat()
        except FileNotFoundError:
            if not allow_missing:
                raise
            path = path.joinpath(*parts[index + 1 :])
            break
        if is_link(info):
            raise PathRejected("links and reparse points are not accessible")
    resolved = path.resolve(strict=not allow_missing)
    if not resolved.is_relative_to(root):
        raise PathRejected("path escapes the workspace")
    return resolved
