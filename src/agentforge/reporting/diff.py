"""Build complete, deterministic diffs from already bounded snapshot bytes."""

import difflib
import hashlib
import io
import json
from collections.abc import Iterator

# SequenceMatcher can be quadratic. This budget covers the complete report;
# larger comparisons use a valid full-replacement hunk without losing bytes.
_MATCH_BUDGET = 1_000_000


def _quoted_path(path: str) -> str:
    """Use unambiguous ASCII JSON quoting for unsafe or non-ASCII names."""
    if all(33 <= ord(character) < 127 and character not in {'"', "\\"} for character in path):
        return path
    return json.dumps(path, ensure_ascii=True)


def _text_lines(data: bytes | None) -> list[str] | None:
    if data is None:
        return []
    if b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    # splitlines also splits CR, VT and Unicode separators, changing the
    # represented file. Only LF is a line boundary in these byte diffs.
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _range(length: int) -> str:
    if length == 0:
        return "0,0"
    return "1" if length == 1 else f"1,{length}"


def _replacement(
    before: list[str], after: list[str], before_name: str, after_name: str,
) -> Iterator[str]:
    yield f"--- {before_name}\n"
    yield f"+++ {after_name}\n"
    yield f"@@ -{_range(len(before))} +{_range(len(after))} @@\n"
    for line in before:
        yield "-" + line
    for line in after:
        yield "+" + line


def build_diff(
    fixed: dict[str, bytes], candidate: dict[str, bytes],
) -> tuple[list[dict], bytes, list[str]]:
    """Return changed-file metadata, UTF-8 diff bytes and verification gaps.

    File byte fields are lengths; missing sides are None. Invalid UTF-8 or NUL
    content is binary and gets an explicit summary and verification gap. Paths
    needing quoting use ASCII JSON strings in the display diff. Text hunks are
    complete, although very large comparisons can use a non-minimal full-file
    replacement. The dictionaries are not mutated and Git is never consulted.
    """
    changed: list[dict] = []
    unverified: list[str] = []
    output = io.StringIO()
    remaining_budget = _MATCH_BUDGET
    for path in sorted(fixed.keys() | candidate.keys()):
        before = fixed.get(path)
        after = candidate.get(path)
        if before == after:
            continue
        before_lines = _text_lines(before)
        after_lines = _text_lines(after)
        binary = before_lines is None or after_lines is None
        change = "added" if before is None else "deleted" if after is None else "modified"
        before_hash = None if before is None else hashlib.sha256(before).hexdigest()
        after_hash = None if after is None else hashlib.sha256(after).hexdigest()
        before_size = None if before is None else len(before)
        after_size = None if after is None else len(after)
        changed.append({
            "path": path,
            "change": change,
            "before_sha256": before_hash,
            "after_sha256": after_hash,
            "before_bytes": before_size,
            "after_bytes": after_size,
            "diff_kind": "binary" if binary else "text",
        })
        before_name = "/dev/null" if before is None else _quoted_path("a/" + path)
        after_name = "/dev/null" if after is None else _quoted_path("b/" + path)
        if binary:
            output.write(
                f"Binary files {before_name} and {after_name} differ "
                f"(before: bytes={before_size}, sha256={before_hash}; "
                f"after: bytes={after_size}, sha256={after_hash})\n"
            )
            unverified.append(
                f"{_quoted_path(path)}: textual diff unavailable for binary content; "
                "exact byte lengths and SHA-256 hashes are recorded."
            )
            continue
        assert before_lines is not None and after_lines is not None
        if not before_lines and not after_lines:
            # Empty-file creation/deletion still changes snapshot membership.
            output.write(f"--- {before_name}\n+++ {after_name}\n")
            continue
        work = len(before_lines) * len(after_lines)
        if work > remaining_budget:
            lines = _replacement(before_lines, after_lines, before_name, after_name)
        else:
            remaining_budget -= work
            lines = difflib.unified_diff(
                before_lines, after_lines, fromfile=before_name, tofile=after_name,
            )
        for line in lines:
            output.write(line)
            if not line.endswith("\n"):
                output.write("\n\\ No newline at end of file\n")
    return changed, output.getvalue().encode("utf-8"), unverified
