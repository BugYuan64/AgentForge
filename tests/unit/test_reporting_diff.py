"""Snapshot diffs account for every changed byte without consulting Git."""

import hashlib
import json

import pytest


@pytest.mark.parametrize(("before", "after", "change", "expected"), [
    (None, b"hello\n", "added",
     b"--- /dev/null\n+++ b/todo_app/main.py\n@@ -0,0 +1 @@\n+hello\n"),
    (b"hello\n", None, "deleted",
     b"--- a/todo_app/main.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-hello\n"),
    (b"before\n", b"after\n", "modified",
     b"--- a/todo_app/main.py\n+++ b/todo_app/main.py\n@@ -1 +1 @@\n-before\n+after\n"),
])
def test_changed_text_has_exact_hunk_and_metadata(
    before: bytes | None, after: bytes | None, change: str, expected: bytes,
) -> None:
    from agentforge.reporting.diff import build_diff

    path = "todo_app/main.py"
    fixed = {} if before is None else {path: before}
    candidate = {} if after is None else {path: after}

    changed, patch, unverified = build_diff(fixed, candidate)

    assert changed == [{
        "path": path,
        "change": change,
        "before_sha256": None if before is None else hashlib.sha256(before).hexdigest(),
        "after_sha256": None if after is None else hashlib.sha256(after).hexdigest(),
        "before_bytes": None if before is None else len(before),
        "after_bytes": None if after is None else len(after),
        "diff_kind": "text",
    }]
    assert patch == expected
    assert unverified == []


@pytest.mark.parametrize(("before", "after", "hunk"), [
    (b"old", b"new", b"-old\n\\ No newline at end of file\n"
     b"+new\n\\ No newline at end of file\n"),
    (b"same\n", b"same", b"-same\n+same\n\\ No newline at end of file\n"),
    (b"same", b"same\n", b"-same\n\\ No newline at end of file\n+same\n"),
    (b"a\r\n", b"a\n", b"-a\r\n+a\n"),
    (b"a\vold\n", b"a\vnew\n", b"-a\vold\n+a\vnew\n"),
    ("a\u2028old\n".encode(), "a\u2028new\n".encode(),
     "-a\u2028old\n+a\u2028new\n".encode()),
])
def test_lf_lines_preserve_other_separators_and_final_newline(
    before: bytes, after: bytes, hunk: bytes,
) -> None:
    from agentforge.reporting.diff import build_diff

    changed, patch, unverified = build_diff({"file": before}, {"file": after})

    assert patch == b"--- a/file\n+++ b/file\n@@ -1 +1 @@\n" + hunk
    assert changed[0]["diff_kind"] == "text"
    assert unverified == []


def test_unchanged_context_without_final_newline_has_one_marker() -> None:
    from agentforge.reporting.diff import build_diff

    _, patch, _ = build_diff({"file": b"first\nold\ntail"}, {"file": b"first\nnew\ntail"})

    assert patch == (b"--- a/file\n+++ b/file\n@@ -1,3 +1,3 @@\n"
                     b" first\n-old\n+new\n tail\n\\ No newline at end of file\n")


@pytest.mark.parametrize(("before", "after", "expected"), [
    (None, b"", b"--- /dev/null\n+++ b/empty\n"),
    (b"", None, b"--- a/empty\n+++ /dev/null\n"),
    (None, b"value", b"--- /dev/null\n+++ b/empty\n@@ -0,0 +1 @@\n"
     b"+value\n\\ No newline at end of file\n"),
    (b"value", None, b"--- a/empty\n+++ /dev/null\n@@ -1 +0,0 @@\n"
     b"-value\n\\ No newline at end of file\n"),
])
def test_absent_empty_and_unterminated_files_are_represented(
    before: bytes | None, after: bytes | None, expected: bytes,
) -> None:
    from agentforge.reporting.diff import build_diff

    fixed = {} if before is None else {"empty": before}
    candidate = {} if after is None else {"empty": after}

    changed, patch, unverified = build_diff(fixed, candidate)

    assert len(changed) == 1
    assert changed[0]["change"] == ("added" if before is None else "deleted")
    assert changed[0]["before_bytes"] == (None if before is None else len(before))
    assert changed[0]["after_bytes"] == (None if after is None else len(after))
    assert patch == expected
    assert unverified == []


def test_unicode_content_remains_utf8_and_headers_quote_unsafe_paths() -> None:
    from agentforge.reporting.diff import build_diff

    path = 'todo_app/任务\t"name\n\u202e.py'
    before = "原内容\n".encode()
    after = "新内容\n".encode()

    changed, patch, unverified = build_diff({path: before}, {path: after})

    lines = patch.decode("utf-8").split("\n")
    assert lines[0].startswith('--- "')
    assert lines[1].startswith('+++ "')
    assert all(32 <= ord(character) < 127 for line in lines[:2] for character in line)
    assert json.loads(lines[0][4:]) == "a/" + path
    assert json.loads(lines[1][4:]) == "b/" + path
    assert "-原内容\n+新内容\n".encode() in patch
    assert changed[0]["path"] == path
    assert unverified == []


@pytest.mark.parametrize(("before", "after"), [
    (None, b"\xff\xfe"),
    (b"\xff\xfe", None),
    (b"old\x00", b"new\x00"),
    (b"\xff", b"new text\n"),
    (b"old text\n", b"\xff"),
])
def test_binary_changes_record_exact_identity_and_explicit_unverified_reason(
    before: bytes | None, after: bytes | None,
) -> None:
    from agentforge.reporting.diff import build_diff

    path = "todo_app/image.bin"
    fixed = {} if before is None else {path: before}
    candidate = {} if after is None else {path: after}

    changed, patch, unverified = build_diff(fixed, candidate)

    assert len(changed) == 1
    assert changed[0]["diff_kind"] == "binary"
    assert changed[0]["before_sha256"] == (
        None if before is None else hashlib.sha256(before).hexdigest()
    )
    assert changed[0]["after_sha256"] == (
        None if after is None else hashlib.sha256(after).hexdigest()
    )
    assert changed[0]["before_bytes"] == (None if before is None else len(before))
    assert changed[0]["after_bytes"] == (None if after is None else len(after))
    summary = patch.decode("utf-8")
    assert "Binary" in summary
    assert path in summary
    for content in (before, after):
        if content is not None:
            assert hashlib.sha256(content).hexdigest() in summary
    assert len(unverified) == 1
    assert path in unverified[0]
    assert "textual diff unavailable" in unverified[0].lower()


def test_binary_summary_quotes_control_characters_in_path() -> None:
    from agentforge.reporting.diff import build_diff

    path = "todo_app/image\n\u202e.bin"

    changed, patch, unverified = build_diff({}, {path: b"\x00"})

    assert changed[0]["path"] == path
    assert patch.count(b"\n") == 1
    assert all(32 <= ord(character) < 127 for character in patch.decode().rstrip("\n"))
    assert "\\n" in unverified[0]
    assert "\u202e" not in unverified[0]


def test_changed_union_is_sorted_deterministic_and_does_not_mutate_snapshots() -> None:
    from agentforge.reporting.diff import build_diff

    fixed = {"z": b"old\n", "same": b"unchanged", "m": b"deleted\n"}
    candidate = {"z": b"new\n", "a": b"added\n", "same": b"unchanged"}
    original_fixed = fixed.copy()
    original_candidate = candidate.copy()

    result = build_diff(fixed, candidate)

    assert [(item["path"], item["change"]) for item in result[0]] == [
        ("a", "added"), ("m", "deleted"), ("z", "modified"),
    ]
    assert result[1].index(b"+++ b/a") < result[1].index(b"--- a/m")
    assert result[1].index(b"--- a/m") < result[1].index(b"--- a/z")
    assert result == build_diff(dict(reversed(fixed.items())), dict(reversed(candidate.items())))
    assert fixed == original_fixed
    assert candidate == original_candidate


@pytest.mark.parametrize("files", [{}, {"empty": b"", "binary": b"\x00\xff", "text": b"a\n"}])
def test_equal_snapshots_have_no_changes_or_unverified_items(files: dict[str, bytes]) -> None:
    from agentforge.reporting.diff import build_diff

    assert build_diff(files, files.copy()) == ([], b"", [])


def test_large_text_change_retains_every_removed_and_added_line() -> None:
    from agentforge.reporting.diff import build_diff

    before = b"".join(f"old-{number}\n".encode() for number in range(12000))
    after = b"".join(f"new-{number}\n".encode() for number in range(12000))

    changed, patch, unverified = build_diff({"large": before}, {"large": after})

    lines = patch.split(b"\n")
    removed = [line[1:] for line in lines if line.startswith(b"-") and not line.startswith(b"---")]
    added = [line[1:] for line in lines if line.startswith(b"+") and not line.startswith(b"+++")]
    assert removed == before.split(b"\n")[:-1]
    assert added == after.split(b"\n")[:-1]
    assert changed[0]["diff_kind"] == "text"
    assert changed[0]["before_bytes"] == len(before)
    assert changed[0]["after_bytes"] == len(after)
    assert unverified == []
