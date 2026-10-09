"""Repeatable preset patch to acceptance to complete review report, with real Docker."""

from pathlib import Path

from test_container_execution import _source_snapshot

from agentforge.acceptance.checks import EXPECTED_TESTS
from agentforge.acceptance.service import AcceptanceService
from agentforge.reporting.service import ReportingService
from agentforge.workspace_tools.contracts import ToolRequest, ToolStatus
from agentforge.workspace_tools.service import WorkspaceTools

pytest_plugins = ("test_container_execution",)
PATCH = Path(__file__).resolve().parents[2] / "examples" / "todo_fix.patch"


def test_patch_acceptance_report_preserves_failures_evidence_and_source(workspace):
    manager, record = workspace
    original = (record.path / "todo_app/main.py").read_bytes()
    before = _source_snapshot(manager.source_repository)
    acceptance = AcceptanceService(manager)
    reporting = ReportingService(manager)
    try:
        baseline = acceptance.baseline(record.id)
        assert baseline["state"] == "recorded", baseline["error"]
        candidate = acceptance.verify(record.id)
        assert candidate["state"] == "existing_failure", candidate["error"]
        failed_report = reporting.build(record.id)
        assert failed_report["state"] == "existing_failure", failed_report["unverified"]
        assert failed_report["existing_failures"] == [EXPECTED_TESTS[-1]]
        assert failed_report["changes"] == []
        tools = WorkspaceTools(manager)
        result = tools.execute(ToolRequest("apply_patch", record.id,
                                           patch=PATCH.read_text(encoding="utf-8")))
        assert result.status is ToolStatus.COMPLETED, result.error
        fixed = acceptance.verify(record.id)
        assert fixed["state"] == "passed", fixed["error"]
        report = reporting.build(record.id)
        assert report["state"] == "passed", report["unverified"]
        assert report["acceptance_id"] == fixed["report_id"]
        assert report["baseline_id"] == baseline["report_id"]
        assert report["candidate_digest"] == fixed["candidate_digest"]
        assert report["fixed_failures"] == [EXPECTED_TESTS[-1]]
        assert [item["path"] for item in report["changes"]] == ["todo_app/main.py"]
        diff = Path(report["artifacts"]["diff"]["path"]).read_text(encoding="utf-8")
        assert "+            raise HTTPException(status_code=404" in diff
        for key in ("candidate_log", "baseline_log", "candidate_xml", "baseline_xml"):
            assert Path(report["artifacts"][key]["path"]).is_file()
        assert reporting.show(record.id)["state"] == "passed"
        (record.path / "todo_app/main.py").write_bytes(original)
        assert reporting.show(record.id)["state"] == "stale"
        assert _source_snapshot(manager.source_repository) == before
    finally:
        (record.path / "todo_app/main.py").write_bytes(original)
        manager.remove(record.id)
    assert reporting.show(record.id)["recorded_state"] == "passed"
    assert _source_snapshot(manager.source_repository) == before
