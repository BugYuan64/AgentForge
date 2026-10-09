"""Complete, version-bound report packs from persisted M9 evidence."""

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agentforge.acceptance.checks import CHECK_COMMAND, EXPECTED_TESTS
from agentforge.acceptance.service import AcceptanceService
from agentforge.acceptance.snapshot import Snapshot, content_digest

ID = "a" * 32
COMMIT = "b" * 40
IMAGE = "sha256:" + "c" * 64


@pytest.fixture
def context(tmp_path, monkeypatch):
    manager = SimpleNamespace(workspaces_directory=tmp_path / "workspaces",
                              source_repository=tmp_path / "source", baseline_commit=COMMIT)
    manager.workspaces_directory.mkdir()
    fixed = {"todo_app/main.py": b"before\n"}
    current = {"todo_app/main.py": b"after\n"}
    state = SimpleNamespace(files=current, head=COMMIT)

    def capture(*args, **kwargs):
        return Snapshot(state.head, content_digest(state.files), state.files.copy())

    import agentforge.reporting.service as module

    monkeypatch.setattr(module, "fixed_files", lambda manager: fixed)
    monkeypatch.setattr(module, "capture", capture)
    acceptance = AcceptanceService(manager)

    def record(kind, failed=()):
        report = acceptance._new_report(ID, kind)
        report.update(head=COMMIT, candidate_digest=content_digest(
            fixed if kind == "baseline" else state.files),
            policy_digest=acceptance.policy_digest(fixed))
        run_id = uuid4().hex
        cases = "".join(
            f'<testcase classname="tests.test_todos" name="{name}">'
            + ('<failure message="failed"/>' if name in failed else '') + '</testcase>'
            for name in EXPECTED_TESTS
        )
        xml = (f'<testsuites><testsuite tests="5" failures="{len(failed)}" '
               f'errors="0" skipped="0">{cases}</testsuite></testsuites>').encode()
        runs = manager.workspaces_directory / ".runs"
        runs.mkdir(exist_ok=True)
        log_path, xml_path = runs / f"{run_id}.log", runs / f"{run_id}.xml"
        log_path.write_bytes(b"full output\nAGENTFORGE_JUNIT_BASE64="
                             + base64.b64encode(xml) + b"\n")
        xml_path.write_bytes(xml)
        report["execution"] = {
            "run_id": run_id, "state": "completed", "image_id": IMAGE,
            "exit_code": int(bool(failed)), "elapsed_seconds": 0.02,
            "log_path": str(log_path), "xml_path": str(xml_path),
            "outcomes": {name: "failed" if name in failed else "passed"
                         for name in EXPECTED_TESTS}, "error": None,
            "environment": {"command": list(CHECK_COMMAND), "image_id": IMAGE},
        }
        report["state"] = "recorded" if kind == "baseline" else "passed"
        if kind == "candidate":
            baseline = acceptance.load(ID, baseline_id)
            report["baseline_id"] = baseline_id
            old = {name for name, outcome in baseline["execution"]["outcomes"].items()
                   if outcome == "failed"}
            report["existing_failures"] = sorted(set(failed) & old)
            report["new_failures"] = sorted(set(failed) - old)
            report["fixed_failures"] = sorted(old - set(failed))
            report["state"] = ("new_failure" if report["new_failures"]
                               else "existing_failure" if failed else "passed")
        return acceptance._save(report)

    baseline_id = record("baseline", (EXPECTED_TESTS[-1],))["report_id"]
    candidate = record("candidate")
    return SimpleNamespace(manager=manager, fixed=fixed, state=state, record=record,
                           candidate=candidate, acceptance=acceptance,
                           service=module.ReportingService(manager))


def test_pack_contains_complete_diff_and_copied_evidence(context):
    report = context.service.build(ID)
    assert report["state"] == "passed"
    assert report["candidate_digest"] == content_digest(context.state.files)
    assert [item["path"] for item in report["changes"]] == ["todo_app/main.py"]
    assert len(report["tests"]) == 5
    assert report["unverified"]  # Checks alone do not replace human review.
    for artifact in report["artifacts"].values():
        data = Path(artifact["path"]).read_bytes()
        assert len(data) == artifact["bytes"]
        assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
    diff = Path(report["artifacts"]["diff"]["path"]).read_text()
    assert "-before\n+after" in diff
    markdown = Path(report["artifacts"]["markdown"]["path"]).read_text(encoding="utf-8")
    assert "todo_app/main.py" in markdown and "未验证" in markdown
    assert context.service.show(ID)["state"] == "passed"


@pytest.mark.parametrize("failed,state", [((EXPECTED_TESTS[-1],), "existing_failure"),
                                          ((EXPECTED_TESTS[0],), "new_failure")])
def test_test_failure_is_not_certified_as_completed(context, failed, state):
    context.record("candidate", failed)
    report = context.service.build(ID)
    assert report["state"] == state
    assert any(test["candidate"] == "failed" for test in report["tests"])


def test_changed_candidate_does_not_reuse_passing_checks(context):
    context.state.files["todo_app/main.py"] = b"new version\n"
    report = context.service.build(ID)
    assert report["state"] == "stale"
    assert report["valid_for_current_candidate"] is False
    assert "new version" in Path(report["artifacts"]["diff"]["path"]).read_text()


def test_saved_report_becomes_stale_after_edit(context):
    saved = context.service.build(ID)
    context.state.files["todo_app/main.py"] = b"edited\n"
    shown = context.service.show(ID)
    assert shown["state"] == "stale"
    assert shown["recorded_state"] == "passed"
    assert shown["report_id"] == saved["report_id"]
    assert json.loads(Path(saved["report_path"]).read_text(encoding="utf-8"))["state"] == "passed"


@pytest.mark.parametrize("issue", ["missing", "external", "mismatch", "wrong_summary"])
def test_incomplete_or_inconsistent_evidence_cannot_pass(context, issue, tmp_path):
    candidate = context.candidate
    run = candidate["execution"]
    if issue == "missing":
        Path(run["log_path"]).unlink()
    elif issue == "external":
        run["log_path"] = str(tmp_path / "secret.txt")
        Path(run["log_path"]).write_text("must not copy")
    elif issue == "mismatch":
        Path(run["xml_path"]).write_bytes(b"<wrong/>")
    else:
        run["outcomes"][EXPECTED_TESTS[0]] = "failed"
    context.acceptance._atomic(Path(candidate["report_path"]), candidate)
    report = context.service.build(ID)
    assert report["state"] == "unverified"
    assert report["unverified"]
    assert all("secret.txt" not in str(item) for item in report["artifacts"].values())


def test_baseline_only_and_missing_acceptance_are_unverified(context):
    context.record("baseline")
    assert context.service.build(ID)["state"] == "unverified"
    (context.manager.workspaces_directory / ".acceptance" / ID / "latest.json").unlink()
    assert context.service.build(ID)["state"] == "unverified"


def test_tampered_artifact_is_unverified(context):
    saved = context.service.build(ID)
    Path(saved["artifacts"]["candidate_log"]["path"]).write_bytes(b"tampered")
    assert context.service.show(ID)["state"] == "unverified"


def test_changed_during_build_is_stale(context, monkeypatch):
    import agentforge.reporting.service as module

    original = module.build_diff

    def mutate(*args):
        result = original(*args)
        context.state.files["todo_app/main.py"] = b"race\n"
        return result

    monkeypatch.setattr(module, "build_diff", mutate)
    assert context.service.build(ID)["state"] == "stale"


def test_head_change_without_file_change_is_stale(context):
    context.state.head = "d" * 40
    assert context.service.build(ID)["state"] == "stale"


@pytest.mark.parametrize("issue", ["policy", "image", "baseline", "classification"])
def test_wrong_provenance_or_classification_is_unverified(context, issue):
    record = context.candidate
    if issue == "policy":
        record["policy_digest"] = "wrong"
    elif issue == "image":
        record["execution"]["image_id"] = "sha256:" + "e" * 64
        record["execution"]["environment"]["image_id"] = record["execution"]["image_id"]
    elif issue == "baseline":
        record["baseline_id"] = "f" * 32
    else:
        record["new_failures"] = [EXPECTED_TESTS[0]]
    context.acceptance._atomic(Path(record["report_path"]), record)
    assert context.service.build(ID)["state"] == "unverified"


def test_original_evidence_can_be_deleted_after_pack_creation(context):
    report = context.service.build(ID)
    for key in ("log_path", "xml_path"):
        Path(context.candidate["execution"][key]).unlink()
    Path(context.candidate["report_path"]).unlink()
    assert context.service.show(ID)["state"] == "passed"
    assert Path(report["artifacts"]["candidate_log"]["path"]).is_file()


def test_publication_failure_preserves_previous_pointer(context, monkeypatch):
    import agentforge.reporting.service as module

    first = context.service.build(ID)
    original = module.write_artifact

    def fail(directory, filename, data):
        if filename == "report.json":
            raise OSError("disk full")
        return original(directory, filename, data)

    monkeypatch.setattr(module, "write_artifact", fail)
    with pytest.raises(OSError, match="disk full"):
        context.service.build(ID)
    assert context.service.show(ID)["report_id"] == first["report_id"]


def test_removed_workspace_keeps_a_readable_historical_pack(context, monkeypatch):
    import agentforge.reporting.service as module

    saved = context.service.build(ID)

    def missing(*args):
        raise ValueError("workspace removed")

    monkeypatch.setattr(module, "capture", missing)
    shown = context.service.show(ID)
    assert shown["report_id"] == saved["report_id"]
    assert shown["state"] == "stale" and shown["recorded_state"] == "passed"
    assert shown["valid_for_current_candidate"] is False


@pytest.mark.parametrize("artifact", ["diff", "markdown", "baseline_xml"])
def test_all_saved_artifact_hashes_are_checked(context, artifact):
    saved = context.service.build(ID)
    Path(saved["artifacts"][artifact]["path"]).write_bytes(b"changed")
    assert context.service.show(ID)["state"] == "unverified"


@pytest.mark.parametrize("issue", ["remove_evidence", "forge_state"])
def test_manifest_tampering_cannot_retain_a_passing_result(context, issue):
    context.record("candidate", (EXPECTED_TESTS[0],))
    report = context.service.build(ID)
    assert report["state"] == "new_failure"
    if issue == "remove_evidence":
        report["artifacts"] = {}
    else:
        report["state"] = "passed"
    Path(report["report_path"]).write_text(json.dumps(report), encoding="utf-8")
    assert context.service.show(ID)["state"] == "unverified"


def test_malformed_pointer_is_a_value_error(context):
    report = context.service.build(ID)
    pointer = Path(report["report_path"]).parent.parent / "latest.json"
    pointer.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="pointer"):
        context.service.show(ID)


def test_malformed_xml_is_saved_as_unverified(context):
    run = context.candidate["execution"]
    raw = b"<testsuites>"
    Path(run["xml_path"]).write_bytes(raw)
    Path(run["log_path"]).write_bytes(b"AGENTFORGE_JUNIT_BASE64="
                                     + base64.b64encode(raw) + b"\n")
    assert context.service.build(ID)["state"] == "unverified"


@pytest.mark.parametrize("filename", ["report.md", "report.json"])
def test_change_during_artifact_writes_is_stale(context, monkeypatch, filename):
    import agentforge.reporting.service as module

    original = module.write_artifact

    def mutate(directory, name, data):
        result = original(directory, name, data)
        if name == filename:
            context.state.files["todo_app/main.py"] = b"changed during publication\n"
        return result

    monkeypatch.setattr(module, "write_artifact", mutate)
    report = context.service.build(ID)
    assert report["state"] == "stale"
    markdown = Path(report["artifacts"]["markdown"]["path"]).read_text(encoding="utf-8")
    assert "**stale**" in markdown
    assert context.service.show(ID)["recorded_state"] == "stale"


@pytest.mark.parametrize("identity", ["../escape", "x" * 32])
def test_invalid_id_cannot_create_artifacts(context, identity):
    with pytest.raises(ValueError):
        context.service.build(identity)
