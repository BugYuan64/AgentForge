"""Persist baseline provenance and compare candidates under the same rules."""

import hashlib
import json
import os
import platform
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agentforge.acceptance.checks import (
    ACCEPTANCE_TEST,
    CHECK_COMMAND,
    EXPECTED_TESTS,
    POLICY_VERSION,
    AcceptanceRunner,
)
from agentforge.acceptance.snapshot import Snapshot, capture, content_digest, fixed_files
from agentforge.workspace_management.manager import WorkspaceError, WorkspaceManager


class AcceptanceService:
    def __init__(self, manager: WorkspaceManager, runner: AcceptanceRunner | None = None) -> None:
        self.manager = manager
        self.runner = runner or AcceptanceRunner(manager)

    def _directory(self, workspace_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", workspace_id):
            raise ValueError("workspace id must be 32 lowercase hexadecimal characters")
        return self.manager.workspaces_directory / ".acceptance" / workspace_id

    @staticmethod
    def _atomic(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _save(self, report: dict) -> dict:
        directory = self._directory(report["workspace_id"])
        path = directory / f"{report['report_id']}.json"
        report["report_path"] = str(path)
        self._atomic(path, report)
        self._atomic(directory / "latest.json", {"report_id": report["report_id"]})
        if report["kind"] == "baseline" and report["state"] == "recorded":
            self._atomic(directory / "baseline.json", {"report_id": report["report_id"]})
        return report

    @staticmethod
    def _read(path: Path) -> dict:
        with path.open("rb") as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError("acceptance record exceeds byte limit")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("invalid acceptance record")
        return value

    def _load(self, workspace_id: str, pointer: str) -> dict:
        directory = self._directory(workspace_id)
        identity = self._read(directory / f"{pointer}.json").get("report_id")
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{32}", identity):
            raise ValueError("invalid acceptance report id")
        report = self._read(directory / f"{identity}.json")
        if (report.get("report_id") != identity or report.get("workspace_id") != workspace_id
                or report.get("baseline_commit") != self.manager.baseline_commit
                or report.get("source_repository") != str(self.manager.source_repository)):
            raise ValueError("acceptance record provenance does not match this workspace")
        return report

    def _policy_digest(self, fixed: dict[str, bytes]) -> str:
        policy = {
            "version": POLICY_VERSION, "fixed_commit": self.manager.baseline_commit,
            "files": content_digest(fixed), "command": CHECK_COMMAND,
            "tests": EXPECTED_TESTS,
        }
        return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _valid_execution(run: dict, *, baseline: bool = False) -> bool:
        outcomes = run.get("outcomes")
        if (run.get("state") != "completed" or run.get("exit_code") not in {0, 1}
                or run.get("error") or not isinstance(outcomes, dict)
                or set(outcomes) != set(EXPECTED_TESTS)):
            return False
        if baseline and any(value not in {"passed", "failed"} for value in outcomes.values()):
            return False
        allowed = {"passed", "failed", "skipped", "error"}
        if any(value not in allowed for value in outcomes.values()):
            return False
        failed = any(value != "passed" for value in outcomes.values())
        # pytest's all-skipped exit 0 still cannot certify the authoritative suite.
        return run["exit_code"] == int(failed)

    def _new_report(self, workspace_id: str, kind: str) -> dict:
        self._directory(workspace_id)
        return {
            "schema_version": 1, "report_id": uuid4().hex, "kind": kind,
            "created_at": datetime.now(UTC).isoformat(), "workspace_id": workspace_id,
            "source_repository": str(self.manager.source_repository),
            "baseline_commit": self.manager.baseline_commit, "baseline_id": None,
            "policy_version": POLICY_VERSION, "policy_digest": None,
            "head": None, "candidate_digest": None,
            "state": "rejected", "error": None, "execution": None,
            "acceptance_tests": [ACCEPTANCE_TEST],
            "regression_tests": [test for test in EXPECTED_TESTS if test != ACCEPTANCE_TEST],
            "existing_failures": [], "new_failures": [], "fixed_failures": [],
            "environment": {"host_python": platform.python_version(),
                            "host_platform": platform.system()},
        }

    @staticmethod
    def _bind(report: dict, snapshot: Snapshot) -> None:
        report["head"] = snapshot.head
        report["candidate_digest"] = snapshot.digest

    def _execute(self, report: dict, snapshot: Snapshot, image_id: str | None) -> dict:
        root = self.manager.workspaces_directory / ".acceptance"
        run = {"state": "infrastructure_error", "image_id": image_id,
               "exit_code": None, "outcomes": {}, "error": None}
        try:
            root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="snapshot-", dir=root) as temporary:
                directory = Path(temporary) / "tree"
                snapshot.write_to(directory)
                run = self.runner.run(report["workspace_id"], directory, image_id=image_id)
        except (OSError, WorkspaceError) as exc:
            run["state"] = "infrastructure_error"
            run["error"] = f"acceptance execution infrastructure: {exc}"
        report["execution"] = run
        return run

    def _unchanged(self, report: dict, fixed: dict[str, bytes]) -> bool:
        try:
            current = capture(self.manager, report["workspace_id"], fixed)
            if current.digest == report["candidate_digest"] and current.head == report["head"]:
                return True
        except (WorkspaceError, KeyError, ValueError, OSError):
            pass
        report["state"] = "stale"
        report["error"] = (
            "candidate changed during execution; snapshot results are no longer current"
        )
        return False

    def baseline(self, workspace_id: str) -> dict:
        report = self._new_report(workspace_id, "baseline")
        try:
            fixed = fixed_files(self.manager)
            report["policy_digest"] = self._policy_digest(fixed)
            snapshot = capture(self.manager, workspace_id, fixed, baseline=True)
            self._bind(report, snapshot)
            run = self._execute(report, snapshot, None)
            if not self._valid_execution(run, baseline=True) or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", run.get("image_id") or "",
            ):
                report["state"] = "environment_error"
                report["error"] = run.get("error") or "baseline lacks complete check evidence"
            else:
                report["state"] = "recorded"
                report["existing_failures"] = sorted(
                    test for test, outcome in run["outcomes"].items() if outcome != "passed"
                )
            self._unchanged(report, fixed)
        except (WorkspaceError, KeyError, ValueError, OSError) as exc:
            report["error"] = str(exc)
        return self._save(report)

    def verify(self, workspace_id: str) -> dict:
        report = self._new_report(workspace_id, "candidate")
        try:
            fixed = fixed_files(self.manager)
            report["policy_digest"] = self._policy_digest(fixed)
            baseline = self._load(workspace_id, "baseline")
            if (baseline.get("kind") != "baseline" or baseline.get("state") != "recorded"
                    or baseline.get("policy_digest") != report["policy_digest"]
                    or baseline.get("candidate_digest") != content_digest(fixed)
                    or baseline.get("head") != self.manager.baseline_commit
                    or not isinstance(baseline.get("execution"), dict)
                    or not self._valid_execution(baseline["execution"], baseline=True)):
                raise ValueError("a valid baseline under the current policy is required")
            image_id = baseline["execution"].get("image_id")
            if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
                raise ValueError("baseline has no immutable image ID")
            report["baseline_id"] = baseline["report_id"]
            snapshot = capture(self.manager, workspace_id, fixed)
            self._bind(report, snapshot)
            run = self._execute(report, snapshot, image_id)
            if not self._valid_execution(run) or run.get("image_id") != image_id:
                report["state"] = "environment_error"
                report["error"] = run.get("error") or "candidate evidence or image is inconsistent"
            else:
                old = {test for test, outcome in baseline["execution"]["outcomes"].items()
                       if outcome != "passed"}
                failures = {
                    test for test, outcome in run["outcomes"].items() if outcome != "passed"
                }
                report["existing_failures"] = sorted(failures & old)
                report["new_failures"] = sorted(failures - old)
                report["fixed_failures"] = sorted(old - failures)
                report["state"] = (
                    "new_failure" if failures - old
                    else "existing_failure" if failures else "passed"
                )
            self._unchanged(report, fixed)
        except FileNotFoundError as exc:
            report["error"] = f"baseline or workspace is unavailable: {exc}"
        except (WorkspaceError, KeyError, ValueError, OSError) as exc:
            report["error"] = str(exc)
        return self._save(report)

    def show(self, workspace_id: str) -> dict:
        report = self._load(workspace_id, "latest")
        report["recorded_state"] = report["state"]
        report["valid_for_current_candidate"] = False
        try:
            fixed = fixed_files(self.manager)
            current = capture(self.manager, workspace_id, fixed)
            valid = (
                report["policy_digest"] == self._policy_digest(fixed)
                and report["head"] == current.head
                and report["candidate_digest"] == current.digest
            )
            report["valid_for_current_candidate"] = valid
            if not valid and report["candidate_digest"] is not None:
                report["state"] = "stale"
                report["error"] = "candidate or policy changed since this report"
        except (WorkspaceError, KeyError, ValueError, OSError) as exc:
            if report["candidate_digest"] is not None:
                report["state"] = "stale"
            report["error"] = str(exc)
        return report
