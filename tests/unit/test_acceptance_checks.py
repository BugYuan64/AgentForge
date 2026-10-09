"""Fixed M9 checks use snapshot bytes and require complete JUnit evidence."""

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_container_runner import create_workspace, fake_docker

TEST_NAMES = (
    "test_post_creates_todo",
    "test_get_existing_todo",
    "test_new_app_starts_empty",
    "test_non_integer_id_is_rejected",
    "test_get_missing_todo_returns_404",
)
IMAGE_ID = "sha256:" + "a" * 64


def junit(*, status: str | None = None, names: tuple[str, ...] = TEST_NAMES) -> str:
    cases = []
    for name in names:
        marker = f"<{status}/>" if status and name == TEST_NAMES[-1] else ""
        cases.append(f'<testcase name="{name}" classname="tests.test_todos">{marker}</testcase>')
    failed = int(status == "failure")
    errors = int(status == "error")
    skipped = int(status == "skipped")
    suite = (
        f'<testsuite tests="{len(names)}" failures="{failed}" errors="{errors}" '
        f'skipped="{skipped}">'
    )
    return "<testsuites>" + suite + "".join(cases) + "</testsuite></testsuites>"


def acceptance_docker(tmp_path: Path, **settings: object) -> tuple[tuple[str, ...], Path]:
    """The M6 daemon double returns the fixed launcher's structured output line."""
    report = settings.pop("junit", junit())
    settings = {"test_exit": 0, "test_log": junit_log(report), **settings}
    return fake_docker(tmp_path, **settings)


def junit_log(contents: str) -> str:
    encoded = base64.b64encode(contents.encode("utf-8")).decode("ascii")
    return "pytest output\nAGENTFORGE_JUNIT_BASE64=" + encoded


def test_junit_requires_all_five_known_checks(tmp_path: Path) -> None:
    from agentforge.acceptance.checks import parse_results

    path = tmp_path / "results.xml"
    path.write_text(junit(), encoding="utf-8")

    assert parse_results(path, 0) == dict.fromkeys(TEST_NAMES, "passed")


@pytest.mark.parametrize(
    ("marker", "exit_code", "outcome"),
    [("failure", 1, "failed"), ("skipped", 0, "skipped"), ("error", 1, "error")],
)
def test_junit_preserves_failure_skip_and_error_by_identity(
    tmp_path: Path, marker: str, exit_code: int, outcome: str
) -> None:
    from agentforge.acceptance.checks import parse_results

    path = tmp_path / "results.xml"
    path.write_text(junit(status=marker), encoding="utf-8")

    assert parse_results(path, exit_code) == {
        "test_post_creates_todo": "passed",
        "test_get_existing_todo": "passed",
        "test_new_app_starts_empty": "passed",
        "test_non_integer_id_is_rejected": "passed",
        "test_get_missing_todo_returns_404": outcome,
    }


@pytest.mark.parametrize(
    ("contents", "exit_code"),
    [
        (junit(names=TEST_NAMES[:-1]), 0),
        (junit(names=(*TEST_NAMES, TEST_NAMES[0])), 0),
        (junit(names=(*TEST_NAMES[:-1], "test_fake")), 0),
        (junit(status="failure"), 0),
        (junit(), 1),
        (junit(), 2),
        ("<testsuites>", 0),
        ('<!DOCTYPE testsuites [<!ENTITY content "x">]>' + junit(), 0),
        (junit() + " " * (1024 * 1024), 0),
        (junit().replace("<testsuites>", "<report>").replace("</testsuites>", "</report>"), 0),
        (junit(status="failure").replace("<failure/>", "<failure/><skipped/>"), 1),
        (junit().replace('classname="tests.test_todos"', 'classname="other.module"'), 0),
        (junit().replace('tests="5"', 'tests="6"'), 0),
        (junit().replace('failures="0"', 'failures="1"'), 0),
        (junit().replace('errors="0"', 'errors="1"'), 0),
        (junit().replace('skipped="0"', 'skipped="1"'), 0),
        (junit().replace(' tests="5"', ''), 0),
    ],
    ids=[
        "missing", "duplicate", "unknown", "failure-exit-zero", "pass-exit-one",
        "pytest-error", "malformed", "entities", "oversize", "wrong-root", "mixed-status",
        "foreign-module", "wrong-test-count", "wrong-failure-count", "wrong-error-count",
        "wrong-skip-count", "missing-statistics",
    ],
)
def test_invalid_junit_cannot_attest_any_pass(
    tmp_path: Path, contents: str, exit_code: int
) -> None:
    from agentforge.acceptance.checks import parse_results

    path = tmp_path / "results.xml"
    path.write_text(contents, encoding="utf-8")

    assert parse_results(path, exit_code) == dict.fromkeys(TEST_NAMES, "error")


def test_absent_or_non_utf8_junit_cannot_attest_any_pass(tmp_path: Path) -> None:
    from agentforge.acceptance.checks import parse_results

    path = tmp_path / "results.xml"
    assert parse_results(path, 0) == dict.fromkeys(TEST_NAMES, "error")
    path.write_bytes(junit().encode("utf-16"))
    assert parse_results(path, 0) == dict.fromkeys(TEST_NAMES, "error")


def test_runner_mounts_only_snapshot_and_recovers_junit_from_log(tmp_path: Path) -> None:
    from agentforge.acceptance.checks import AcceptanceRunner

    manager, workspace = create_workspace(tmp_path)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    command, state_path = acceptance_docker(tmp_path)

    result = AcceptanceRunner(manager, docker_command=command).run(workspace.id, snapshot)

    assert result["state"] == "completed"
    assert result["exit_code"] == 0
    assert result["error"] is None
    assert result["outcomes"] == dict.fromkeys(TEST_NAMES, "passed")
    assert result["image_id"] == IMAGE_ID
    assert Path(result["xml_path"]).read_text(encoding="utf-8") == junit()
    assert "command=python -I -c" in Path(result["log_path"]).read_text(encoding="utf-8")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    create = next(call for call in state["calls"] if call[0] == "create")
    mount = create[create.index("--mount") + 1]
    assert mount == f"type=bind,source={snapshot},target=/workspace,readonly"
    assert str(workspace.path) not in " ".join(create)
    assert str(manager.source_repository) not in " ".join(create)
    assert create[create.index("--user") + 1] == "65534:65534"
    assert create[create.index("--network") + 1] == "none"
    assert create[create.index("--memory") + 1] == "512m"
    assert create[create.index("--security-opt") + 1] == "no-new-privileges"
    assert create[-5] == IMAGE_ID
    assert create[-4:-1] == ["python", "-I", "-c"]
    assert [call[0] for call in state["calls"]][-2:] == ["logs", "rm"]
    assert not any(call[0] == "cp" for call in state["calls"])
    assert not state["exists"]
    environment = result["environment"]
    assert environment["image_id"] == IMAGE_ID
    assert environment["command"] == create[-4:]
    assert environment["policy_version"] == "todo-m9-v1"
    json.dumps(result)


def test_runner_uses_requested_image_id_for_reproducible_candidate(tmp_path: Path) -> None:
    from agentforge.acceptance.checks import AcceptanceRunner

    manager, workspace = create_workspace(tmp_path)
    command, state_path = acceptance_docker(tmp_path)

    result = AcceptanceRunner(manager, docker_command=command).run(
        workspace.id, workspace.path, image_id=IMAGE_ID
    )

    assert result["error"] is None
    calls = json.loads(state_path.read_text(encoding="utf-8"))["calls"]
    assert calls[0] == ["image", "inspect", "--format", "{{.Id}}", IMAGE_ID]


@pytest.mark.parametrize(
    "settings",
    [
        {"image_error": True},
        {"wait_sleep": 1},
        {"test_log": "5 passed; no structured results"},
        {"test_log": junit_log(junit()) + "\n" + junit_log(junit())},
        {"test_log": "AGENTFORGE_JUNIT_BASE64=not-valid!"},
        {"test_log": "AGENTFORGE_JUNIT_BASE64=" + "A" * (1400000)},
        {"test_exit": 2},
        {"junit": junit(names=TEST_NAMES[:-1])},
        {"junit": junit(status="skipped")},
        {"junit": junit(status="error"), "test_exit": 1},
    ],
    ids=[
        "daemon", "timeout", "missing-marker", "duplicate-marker", "invalid-marker",
        "oversize-marker", "pytest-internal", "incomplete", "skip", "test-error",
    ],
)
def test_runner_reports_explicit_error_instead_of_false_pass(
    tmp_path: Path, settings: dict[str, object]
) -> None:
    from agentforge.acceptance.checks import AcceptanceRunner

    manager, workspace = create_workspace(tmp_path)
    command, state_path = acceptance_docker(tmp_path, **settings)

    result = AcceptanceRunner(manager, timeout_seconds=0.1, docker_command=command).run(
        workspace.id, workspace.path
    )

    assert result["error"]
    assert set(result["outcomes"].values()) != {"passed"}
    assert not json.loads(state_path.read_text(encoding="utf-8"))["exists"]


def test_runner_keeps_expected_failure_as_completed_evidence(tmp_path: Path) -> None:
    from agentforge.acceptance.checks import AcceptanceRunner

    manager, workspace = create_workspace(tmp_path)
    command, _ = acceptance_docker(tmp_path, junit=junit(status="failure"), test_exit=1)

    result = AcceptanceRunner(manager, docker_command=command).run(workspace.id, workspace.path)

    assert result["state"] == "completed"
    assert result["exit_code"] == 1
    assert result["error"] is None
    assert result["outcomes"]["test_get_missing_todo_returns_404"] == "failed"


def test_timeout_retains_classification_if_no_partial_junit_exists(tmp_path: Path) -> None:
    from agentforge.acceptance.checks import AcceptanceRunner

    manager, workspace = create_workspace(tmp_path)
    command, state_path = acceptance_docker(
        tmp_path, wait_sleep=1, test_log="partial pytest output"
    )

    result = AcceptanceRunner(manager, timeout_seconds=0.1, docker_command=command).run(
        workspace.id, workspace.path
    )

    assert result["state"] == "timed_out"
    assert "exceeded" in result["error"]
    assert result["outcomes"] == dict.fromkeys(TEST_NAMES, "error")
    assert "partial pytest output" in Path(result["log_path"]).read_text(encoding="utf-8")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert not state["exists"]
    assert not state["running"]


@pytest.mark.parametrize(
    ("pytest_exit", "report_error"), [(0, False), (1, False), (1, True)],
)
def test_trusted_command_cannot_load_candidate_pytest_or_conftest(
    pytest_exit: int, report_error: bool
) -> None:
    """Executing the launcher must select trusted pytest before exposing snapshot imports."""
    from agentforge.acceptance.checks import CHECK_COMMAND

    # A trusted launcher executes pytest from the image while the candidate is absent from sys.path.
    command = CHECK_COMMAND[-1]
    events = []

    class TrustedPytest:
        @staticmethod
        def main(arguments):
            events.append((list(fake_sys.path), arguments))
            return pytest_exit

    class FakeSys:
        def __init__(self):
            self.path = ["/trusted/image"]

        @staticmethod
        def exit(code):
            events.append(code)

    class ReportPath:
        def __init__(self, path):
            assert path == "/tmp/agentforge-results.xml"

        def read_bytes(self):
            if report_error:
                raise FileNotFoundError("missing JUnit")
            return b"<xml/>"

    fake_sys = FakeSys()

    def trusted_import(name, *args, **kwargs):
        assert fake_sys.path == ["/trusted/image"]
        if name == "pytest":
            return TrustedPytest
        if name == "sys":
            return fake_sys
        if name == "base64":
            return base64
        if name == "pathlib":
            return SimpleNamespace(Path=ReportPath)
        raise AssertionError(f"unexpected import: {name}")

    exec(
        command,
        {"__builtins__": {
            "__import__": trusted_import, "print": events.append, "OSError": OSError, "str": str,
        }},
    )

    assert CHECK_COMMAND[:3] == ("python", "-I", "-c")
    assert events == [
        (
            ["/workspace", "/trusted/image"],
            [
                "-q", "-W", "error", "-p", "no:cacheprovider", "--noconftest", "-c",
                "/dev/null", "--rootdir=/workspace", "--junitxml=/tmp/agentforge-results.xml",
                "tests/test_todos.py",
            ],
        ),
        "\nAGENTFORGE_JUNIT_ERROR=missing JUnit"
        if report_error else "\nAGENTFORGE_JUNIT_BASE64=PHhtbC8+",
        pytest_exit,
    ]
