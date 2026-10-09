"""Run host-selected Todo checks against a snapshot and validate complete JUnit evidence."""

import base64
import binascii
import re
from collections.abc import Sequence
from pathlib import Path
from xml.etree import ElementTree

from agentforge.container_execution.runner import ContainerTestRunner, RunState
from agentforge.workspace_management.manager import WorkspaceManager, WorkspaceRecord

POLICY_VERSION = "todo-m9-v1"
EXPECTED_TESTS = (
    "test_post_creates_todo",
    "test_get_existing_todo",
    "test_new_app_starts_empty",
    "test_non_integer_id_is_rejected",
    "test_get_missing_todo_returns_404",
)
ACCEPTANCE_TEST = "test_get_missing_todo_returns_404"
CHECK_COMMAND = (
    "python",
    "-I",
    "-c",
    "import pytest\nimport sys\nimport base64\nfrom pathlib import Path\n"
    "sys.path.insert(0, '/workspace')\n"
    "code = pytest.main(['-q', '-W', 'error', '-p', 'no:cacheprovider', "
    "'--noconftest', '-c', '/dev/null', '--rootdir=/workspace', "
    "'--junitxml=/tmp/agentforge-results.xml', 'tests/test_todos.py'])\n"
    "try:\n"
    "    report = Path('/tmp/agentforge-results.xml').read_bytes()\n"
    "    print('\\nAGENTFORGE_JUNIT_BASE64=' + base64.b64encode(report).decode('ascii'))\n"
    "except OSError as exc:\n"
    "    print('\\nAGENTFORGE_JUNIT_ERROR=' + str(exc))\n"
    "sys.exit(code)",
)
MAX_XML_BYTES = 1024 * 1024
MAX_LOG_BYTES = 8 * MAX_XML_BYTES
JUNIT_MARKER = b"AGENTFORGE_JUNIT_BASE64="


def _extract_junit(log_path: Path, xml_path: Path) -> None:
    """Recover exactly one bounded report emitted before the container's tmpfs disappears."""
    max_encoded_bytes = 4 * ((MAX_XML_BYTES + 2) // 3)
    max_line_bytes = len(JUNIT_MARKER) + max_encoded_bytes + 2
    report: bytes | None = None
    total_bytes = 0
    with log_path.open("rb") as source:
        while line := source.readline(max_line_bytes + 1):
            total_bytes += len(line)
            if total_bytes > MAX_LOG_BYTES or len(line) > max_line_bytes:
                raise ValueError("JUnit log exceeds the bounded extraction limits")
            if not line.startswith(JUNIT_MARKER):
                continue
            if report is not None:
                raise ValueError("JUnit log contains duplicate structured reports")
            try:
                report = base64.b64decode(line[len(JUNIT_MARKER):].rstrip(b"\r\n"), validate=True)
            except binascii.Error as exc:
                raise ValueError("JUnit log contains invalid Base64") from exc
            if len(report) > MAX_XML_BYTES:
                raise ValueError("JUnit XML exceeds the 1 MiB limit")
    if report is None:
        raise ValueError("JUnit log is missing the structured report marker")
    xml_path.write_bytes(report)


def _parse_results(xml_path: Path, exit_code: int | None) -> dict[str, str]:
    """Raise a diagnostic error when the report cannot attest the fixed suite."""
    if type(exit_code) is not int or exit_code not in (0, 1):
        raise ValueError(f"pytest did not complete test execution (exit {exit_code})")
    with xml_path.open("rb") as source:
        contents = source.read(MAX_XML_BYTES + 1)
    if len(contents) > MAX_XML_BYTES:
        raise ValueError("JUnit XML exceeds the 1 MiB limit")
    decoded = contents.decode("utf-8-sig")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", decoded, flags=re.IGNORECASE):
        raise ValueError("JUnit XML must not contain a DTD or entity declaration")
    root = ElementTree.fromstring(decoded)
    if root.tag not in ("testsuites", "testsuite"):
        raise ValueError("JUnit XML has an unsupported root element")

    suites = [root] if root.tag == "testsuite" else list(root)
    if not suites or any(suite.tag != "testsuite" for suite in suites):
        raise ValueError("JUnit XML must contain test suites")
    direct_cases = [case for suite in suites for case in suite if case.tag == "testcase"]
    if len(direct_cases) != len(list(root.iter("testcase"))):
        raise ValueError("JUnit XML contains test cases outside a test suite")
    outcomes: dict[str, str] = {}
    statuses = {"failure": "failed", "skipped": "skipped", "error": "error"}
    for case in direct_cases:
        name = case.get("name")
        if name not in EXPECTED_TESTS:
            raise ValueError(f"JUnit XML contains an unknown check: {name}")
        if name in outcomes:
            raise ValueError(f"JUnit XML contains a duplicate check: {name}")
        if case.get("classname") != "tests.test_todos":
            raise ValueError(f"JUnit XML contains a check from an unexpected module: {name}")
        markers = [child.tag for child in case if child.tag in statuses]
        if len(markers) > 1:
            raise ValueError(f"JUnit XML contains conflicting outcomes: {name}")
        outcomes[name] = statuses[markers[0]] if markers else "passed"
    for suite in suites:
        cases = [case for case in suite if case.tag == "testcase"]
        counts = {
            "tests": len(cases),
            "failures": sum(outcomes[case.get("name")] == "failed" for case in cases),
            "errors": sum(outcomes[case.get("name")] == "error" for case in cases),
            "skipped": sum(outcomes[case.get("name")] == "skipped" for case in cases),
        }
        for statistic, expected in counts.items():
            recorded = suite.get(statistic, "")
            if re.fullmatch(r"[0-9]+", recorded) is None or int(recorded) != expected:
                raise ValueError(f"JUnit XML has inconsistent {statistic} statistics")
    if set(outcomes) != set(EXPECTED_TESTS):
        missing = ", ".join(name for name in EXPECTED_TESTS if name not in outcomes)
        raise ValueError(f"JUnit XML is missing required checks: {missing}")
    failed = any(outcome in ("failed", "error") for outcome in outcomes.values())
    if exit_code != int(failed):
        raise ValueError(f"JUnit outcomes are inconsistent with pytest exit {exit_code}")
    return {name: outcomes[name] for name in EXPECTED_TESTS}


def parse_results(xml_path: Path, exit_code: int | None) -> dict[str, str]:
    """Return five named outcomes, failing closed when structured evidence is invalid."""
    try:
        return _parse_results(xml_path, exit_code)
    except (OSError, ValueError, ElementTree.ParseError):
        return dict.fromkeys(EXPECTED_TESTS, "error")


class _SnapshotRunner(ContainerTestRunner):
    """Reuse M6 lifecycle and isolation while selecting immutable input and structured output."""

    def __init__(
        self,
        manager: WorkspaceManager,
        snapshot: Path,
        image: str,
        timeout_seconds: float,
        docker_command: Sequence[str],
    ) -> None:
        super().__init__(manager, image, timeout_seconds, docker_command)
        self._snapshot = snapshot

    def _execution(self, workspace: WorkspaceRecord) -> tuple[Path, tuple[str, ...]]:
        return self._snapshot, CHECK_COMMAND

class AcceptanceRunner(ContainerTestRunner):
    """Expose the host-controlled M9 suite without any candidate command overrides."""

    def __init__(
        self,
        manager: WorkspaceManager,
        image: str = "agentforge-todo-test:m6",
        timeout_seconds: float = 30.0,
        docker_command: Sequence[str] = ("docker",),
    ) -> None:
        super().__init__(manager, image, timeout_seconds, docker_command)

    def run(
        self, workspace_id: str, snapshot: Path, image_id: str | None = None
    ) -> dict[str, object]:
        """Return durable structured check evidence and a host-selected environment summary."""
        if image_id is not None and re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
            raise ValueError("acceptance image ID must be a complete sha256 ID")
        runner = _SnapshotRunner(
            self.workspace_manager,
            snapshot,
            image_id or self.image,
            self.timeout_seconds,
            self._docker_command,
        )
        result = runner.run(workspace_id)
        xml_path = result.log_path.with_suffix(".xml")
        error = result.error
        outcomes = dict.fromkeys(EXPECTED_TESTS, "error")
        if result.state is not RunState.COMPLETED:
            error = error or f"acceptance execution did not complete: {result.state.value}"
        elif image_id is not None and result.image_id != image_id:
            error = "Docker resolved a different image ID than the acceptance baseline"
        else:
            try:
                _extract_junit(result.log_path, xml_path)
                outcomes = _parse_results(xml_path, result.exit_code)
            except (OSError, ValueError, ElementTree.ParseError) as exc:
                error = f"JUnit results: {exc}"
            else:
                incomplete = [
                    name for name, outcome in outcomes.items() if outcome in ("skipped", "error")
                ]
                if incomplete:
                    error = "acceptance checks skipped or errored: " + ", ".join(incomplete)
        if error is not None and error != result.error:
            self._append(result.log_path, f"acceptance_error={error}")
        return {
            "run_id": result.run_id,
            "image_id": result.image_id,
            "state": result.state.value,
            "exit_code": result.exit_code,
            "elapsed_seconds": result.elapsed_seconds,
            "log_path": str(result.log_path),
            "xml_path": str(xml_path),
            "outcomes": outcomes,
            "error": error,
            "environment": {
                "policy_version": POLICY_VERSION,
                "image_id": result.image_id,
                "command": list(CHECK_COMMAND),
                "timeout_seconds": self.timeout_seconds,
                "isolation": {
                    "user": "65534:65534",
                    "network": "none",
                    "read_only": True,
                    "cap_drop": "ALL",
                    "security_opt": "no-new-privileges",
                    "cpus": 1,
                    "memory": "512m",
                    "memory_swap": "512m",
                    "pids_limit": 64,
                    "workspace_mount": "/workspace:readonly",
                    "tmpfs": "/tmp:rw,nosuid,nodev,size=64m",
                    "environment": {
                        "HOME": "/tmp",
                        "TMPDIR": "/tmp",
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                    },
                },
            },
        }
