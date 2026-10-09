"""Baseline provenance, failure comparisons and stale candidate evidence."""

import json
from pathlib import Path

import pytest
from test_container_runner import create_workspace

NAMES = (
    "test_post_creates_todo", "test_get_existing_todo", "test_new_app_starts_empty",
    "test_non_integer_id_is_rejected", "test_get_missing_todo_returns_404",
)
IMAGE = "sha256:" + "a" * 64


class FakeRunner:
    def __init__(self, manager, results=None, mutate=None):
        self.manager = manager
        self.results = results or [{NAMES[-1]: "failed"}, {}]
        self.calls = []
        self.mutate = mutate

    def run(self, workspace_id, snapshot, image_id=None):
        self.calls.append((workspace_id, snapshot, image_id))
        overrides = self.results.pop(0)
        outcomes = {name: "passed" for name in NAMES} | overrides
        if self.mutate:
            self.mutate()
        return {
            "run_id": "test-run", "image_id": image_id or IMAGE,
            "state": "completed", "exit_code": int(any(v != "passed" for v in outcomes.values())),
            "elapsed_seconds": 0.01, "log_path": "complete.log", "xml_path": "results.xml",
            "outcomes": outcomes, "error": None, "environment": {"image_id": image_id or IMAGE},
        }


def service(tmp_path, **options):
    from agentforge.acceptance.service import AcceptanceService

    manager, record = create_workspace(tmp_path)
    runner = FakeRunner(manager, **options)
    return manager, record, runner, AcceptanceService(manager, runner)


def edit(record):
    path = record.path / "todo_app/main.py"
    path.write_bytes(path.read_bytes() + b"\n# candidate\n")


def test_baseline_and_fixed_image_candidate_are_persisted(tmp_path: Path) -> None:
    from agentforge.acceptance.service import AcceptanceService

    manager, record, runner, verifier = service(tmp_path)
    baseline = verifier.baseline(record.id)
    assert baseline["state"] == "recorded"
    assert baseline["existing_failures"] == [NAMES[-1]]
    assert baseline["execution"]["image_id"] == IMAGE
    edit(record)
    candidate = verifier.verify(record.id)
    assert candidate["state"] == "passed"
    assert candidate["baseline_id"] == baseline["report_id"]
    assert candidate["candidate_digest"] != baseline["candidate_digest"]
    assert candidate["fixed_failures"] == [NAMES[-1]]
    assert runner.calls[1][2] == IMAGE
    assert all(not call[1].exists() for call in runner.calls)
    assert json.loads(Path(candidate["report_path"]).read_text())["state"] == "passed"
    queried = AcceptanceService(manager, runner).show(record.id)
    assert queried["state"] == "passed"
    assert queried["valid_for_current_candidate"] is True
    edit(record)
    queried = verifier.show(record.id)
    assert queried["state"] == "stale"
    assert queried["recorded_state"] == "passed"
    assert queried["valid_for_current_candidate"] is False


def test_missing_baseline_and_dirty_baseline_do_not_run(tmp_path: Path) -> None:
    _, record, runner, verifier = service(tmp_path)
    assert verifier.verify(record.id)["state"] == "rejected"
    edit(record)
    assert verifier.baseline(record.id)["state"] == "rejected"
    assert runner.calls == []


@pytest.mark.parametrize(("candidate", "expected", "new", "remaining"), [
    ({NAMES[-1]: "failed"}, "existing_failure", [], [NAMES[-1]]),
    ({NAMES[0]: "failed"}, "new_failure", [NAMES[0]], []),
    ({NAMES[-1]: "failed", NAMES[0]: "failed"}, "new_failure", [NAMES[0]], [NAMES[-1]]),
    ({NAMES[0]: "skipped"}, "new_failure", [NAMES[0]], []),
])
def test_failure_classification(tmp_path, candidate, expected, new, remaining):
    _, record, _, verifier = service(tmp_path, results=[{NAMES[-1]: "failed"}, candidate])
    verifier.baseline(record.id)
    edit(record)
    result = verifier.verify(record.id)
    assert result["state"] == expected
    assert result["new_failures"] == new
    assert result["existing_failures"] == remaining


def test_protected_modification_rejects_without_running(tmp_path: Path) -> None:
    _, record, runner, verifier = service(tmp_path)
    verifier.baseline(record.id)
    (record.path / "tests/test_todos.py").write_bytes(b"# removed authority\n")
    result = verifier.verify(record.id)
    assert result["state"] == "rejected"
    assert "protected" in result["error"]
    assert len(runner.calls) == 1


def test_mutation_during_run_invalidates_evidence(tmp_path: Path) -> None:
    _, record, runner, verifier = service(tmp_path)
    verifier.baseline(record.id)
    edit(record)
    runner.mutate = lambda: edit(record)
    result = verifier.verify(record.id)
    assert result["state"] == "stale"
    assert result["execution"]["exit_code"] == 0


def test_environment_failure_cannot_be_a_baseline(tmp_path: Path) -> None:
    _, record, runner, verifier = service(tmp_path)

    def unavailable(*args, **kwargs):
        return {"state": "infrastructure_error", "image_id": None, "exit_code": None,
                "outcomes": {}, "error": "Docker unavailable"}

    runner.run = unavailable
    result = verifier.baseline(record.id)
    assert result["state"] == "environment_error"
    assert "Docker unavailable" in result["error"]
    assert verifier.verify(record.id)["state"] == "rejected"


def test_skipped_or_incomplete_baseline_is_not_recorded(tmp_path: Path) -> None:
    _, record, _, verifier = service(tmp_path, results=[{NAMES[0]: "skipped"}])
    assert verifier.baseline(record.id)["state"] == "environment_error"
    assert verifier.verify(record.id)["state"] == "rejected"


def test_image_and_rule_mismatch_are_rejected(tmp_path: Path) -> None:
    _, record, runner, verifier = service(tmp_path)
    baseline = verifier.baseline(record.id)
    baseline_path = Path(baseline["report_path"])
    saved = json.loads(baseline_path.read_text())
    saved["policy_digest"] = "wrong"
    baseline_path.write_text(json.dumps(saved), encoding="utf-8")
    assert verifier.verify(record.id)["state"] == "rejected"
    assert len(runner.calls) == 1


def test_new_baseline_keeps_old_report_identity(tmp_path: Path) -> None:
    _, record, runner, verifier = service(tmp_path, results=[{NAMES[-1]: "failed"}] * 2)
    first = verifier.baseline(record.id)
    second = verifier.baseline(record.id)
    assert first["report_id"] != second["report_id"]
    assert Path(first["report_path"]).exists()
    assert Path(second["report_path"]).exists()
    assert len(runner.calls) == 2


def test_rejected_baseline_attempt_preserves_last_valid_baseline(tmp_path: Path) -> None:
    _, record, runner, verifier = service(tmp_path)
    baseline = verifier.baseline(record.id)
    edit(record)
    assert verifier.baseline(record.id)["state"] == "rejected"
    candidate = verifier.verify(record.id)
    assert candidate["state"] == "passed"
    assert candidate["baseline_id"] == baseline["report_id"]
    assert len(runner.calls) == 2


@pytest.mark.parametrize("phase", ["baseline", "candidate"])
def test_execution_io_fault_is_an_environment_error(tmp_path: Path, phase: str) -> None:
    _, record, runner, verifier = service(tmp_path)
    if phase == "candidate":
        verifier.baseline(record.id)
        edit(record)

    def disk_failure(*args, **kwargs):
        raise OSError("disk full while preparing evidence")

    runner.run = disk_failure
    result = (verifier.baseline if phase == "baseline" else verifier.verify)(record.id)
    assert result["state"] == "environment_error"
    assert "disk full" in result["error"]
