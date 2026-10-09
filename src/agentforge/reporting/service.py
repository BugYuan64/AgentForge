"""Build review packs without executing checks or changing job/candidate state."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agentforge.acceptance.checks import ACCEPTANCE_TEST, EXPECTED_TESTS, POLICY_VERSION
from agentforge.acceptance.service import AcceptanceService
from agentforge.acceptance.snapshot import capture, content_digest, fixed_files
from agentforge.reporting.diff import build_diff
from agentforge.reporting.evidence import (
    JSON_LIMIT,
    LOG_LIMIT,
    copy_record,
    identity,
    read_regular,
    write_artifact,
)
from agentforge.workspace_management.manager import WorkspaceError, WorkspaceManager
from agentforge.workspace_tools.paths import checked_path

ERRORS = (WorkspaceError, KeyError, ValueError, OSError, TypeError)


def _json(data: dict) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _text(value: object) -> str:
    """Render untrusted paths/messages as one table-safe, literal value."""
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace(
        "`", "\\`"
    ).replace("<", "&lt;").replace(">", "&gt;").replace("\r", "\\r").replace("\n", "\\n")


class ReportingService:
    def __init__(self, manager: WorkspaceManager) -> None:
        self.manager = manager
        self.acceptance = AcceptanceService(manager)

    def _root(self, workspace_id: str) -> Path:
        identity(workspace_id)
        root = checked_path(self.manager.workspaces_directory, f".reports/{workspace_id}",
                            allow_missing=True)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _record(self, workspace_id: str, directory: Path, report: dict, fixed: dict) -> None:
        try:
            candidate = self.acceptance.load(workspace_id)
            report["acceptance_id"] = candidate["report_id"]
            report["acceptance_state"] = candidate["state"]
            report["acceptance_candidate_digest"] = candidate.get("candidate_digest")
            report["acceptance_head"] = candidate.get("head")
            report["acceptance_error"] = candidate.get("error")
            report["execution"] = candidate.get("execution")
            if candidate.get("kind") != "candidate":
                raise ValueError("no candidate verification has been recorded")
            same_version = (candidate.get("head") == report["head"]
                            and candidate.get("candidate_digest") == report["candidate_digest"])
            if not same_version:
                report["state"] = "stale"
                report["unverified"].append("候选已变化: 现有验收与本次 Diff 不是同一版本。")
            baseline = self.acceptance.load(workspace_id, identity(candidate.get("baseline_id")))
            report["baseline_id"] = baseline["report_id"]
            policy = self.acceptance.policy_digest(fixed)
            if (candidate.get("policy_digest") != policy or baseline.get("policy_digest") != policy
                    or candidate.get("policy_version") != POLICY_VERSION
                    or baseline.get("policy_version") != POLICY_VERSION
                    or baseline.get("kind") != "baseline" or baseline.get("state") != "recorded"
                    or baseline.get("head") != self.manager.baseline_commit
                    or baseline.get("candidate_digest") != content_digest(fixed)):
                raise ValueError("baseline or candidate does not match the fixed policy")
            for prefix, record in (("baseline", baseline), ("candidate", candidate)):
                copy_record(self.acceptance, workspace_id, record, directory, prefix,
                            report["artifacts"])
            old, new = baseline["execution"], candidate["execution"]
            if old["image_id"] != new["image_id"]:
                raise ValueError("candidate checks did not use the baseline image")
            report["tests"] = [{"name": name,
                                "group": "acceptance" if name == ACCEPTANCE_TEST else "regression",
                                "baseline": old["outcomes"][name],
                                "candidate": new["outcomes"][name]}
                               for name in EXPECTED_TESTS]
            old_failures = {name for name, value in old["outcomes"].items() if value == "failed"}
            failures = {name for name, value in new["outcomes"].items() if value == "failed"}
            report["existing_failures"] = sorted(failures & old_failures)
            report["new_failures"] = sorted(failures - old_failures)
            report["fixed_failures"] = sorted(old_failures - failures)
            state = ("new_failure" if failures - old_failures
                     else "existing_failure" if failures else "passed")
            fields = ("existing_failures", "new_failures", "fixed_failures")
            if (candidate["state"] != state
                    or any(candidate.get(field) != report[field] for field in fields)):
                raise ValueError("saved acceptance classification is inconsistent")
            if same_version:
                report["state"] = state
                report["valid_for_current_candidate"] = True
        except ERRORS as exc:
            report["unverified"].append(f"验收证据未确认: {exc}")

    def _current(self, report: dict, fixed: dict) -> None:
        try:
            current = capture(self.manager, report["workspace_id"], fixed)
            if (current.head == report["head"] and current.digest == report["candidate_digest"]
                    and self.acceptance.policy_digest(fixed) == report["policy_digest"]):
                return
        except ERRORS as exc:
            report["unverified"].append(f"无法确认当前候选: {exc}")
        report["state"] = "stale"
        report["valid_for_current_candidate"] = False
        report["unverified"].append("候选或规则已变化, 保存的检查结论不能代表当前候选。")

    @staticmethod
    def _markdown(report: dict) -> bytes:
        lines = ["# 候选变更与验证报告", "", f"检查结论: **{report['state']}**",
                 "", "该结论仅针对固定检查; 用户仍需审查候选代码并决定是否接受。",
                 "", f"当前候选验收有效: {report['valid_for_current_candidate']}",
                 f"工作区: {_text(report['workspace_path'])}",
                 f"固定基线提交: {report['baseline_commit']}",
                 f"候选 HEAD: {report['head']}",
                 f"Diff 候选内容 SHA256: {report['candidate_digest']}",
                 f"验收候选内容 SHA256: {report.get('acceptance_candidate_digest')}",
                 f"验收记录: {report.get('acceptance_id')}; 基线记录: {report.get('baseline_id')}",
                 "", "## 变更文件", "", "| 路径 | 类型 | 原字节数 | 新字节数 |",
                 "|---|---|---:|---:|"]
        for item in report["changes"]:
            target = (Path(report["workspace_path"]) / item["path"]).as_posix()
            label = _text(item["path"])
            path = label if item["change"] == "deleted" else f"[{label}](<{target}>)"
            lines.append(f"| {path} | {item['change']} | "
                         f"{item['before_bytes']} | {item['after_bytes']} |")
        if not report["changes"]:
            lines.append("| 无文件变更 | — | — | — |")
        lines.extend(["", "每个变更的完整内容摘要见 report.json; 完整补丁见 changes.diff。",
                      "", "## 逐项测试", "",
                      "候选列来自所引用的验收版本; 当前有效性为 false 时不能代表本次 Diff。", "",
                      "| 检查 | 分组 | 基线 | 验收候选 |", "|---|---|---|---|"])
        for test in report["tests"]:
            lines.append(f"| {test['name']} | {test['group']} | "
                         f"{test['baseline']} | {test['candidate']} |")
        if not report["tests"]:
            lines.append("| 未确认检查证据 | — | — | — |")
        for field in ("existing_failures", "new_failures", "fixed_failures"):
            lines.append(f"\n{field}: {', '.join(report[field]) or '无'}")
        execution = report.get("execution")
        execution = execution if isinstance(execution, dict) else {}
        environment = execution.get("environment")
        environment = environment if isinstance(environment, dict) else {}
        lines.extend(["", "## 运行与完整证据", "",
                      f"运行 ID: {_text(execution.get('run_id'))}",
                      f"精确镜像: {_text(execution.get('image_id'))}",
                      f"退出码: {execution.get('exit_code')}; "
                      f"耗时: {execution.get('elapsed_seconds')} 秒",
                      "", "检查命令(JSON 数组): ", "", "```json",
                      json.dumps(environment.get("command"), ensure_ascii=False), "```", "",
                      "隔离配置及完整环境见候选验收 JSON。以下均为完整保存文件, 无内容截断。", ""])
        for key, artifact in report["artifacts"].items():
            if key == "markdown":
                continue  # A file cannot embed its own final hash.
            target = Path(artifact["path"]).as_posix()
            lines.append(f"- [{key}](<{target}>): {artifact['bytes']} 字节; "
                         f"SHA256 {artifact['sha256']}")
        lines.extend(["", "## 未验证事项", ""])
        lines.extend(f"- {_text(item)}" for item in report["unverified"])
        return ("\n".join(lines) + "\n").encode("utf-8")

    def build(self, workspace_id: str) -> dict:
        root = self._root(workspace_id)
        directory = root / uuid4().hex
        directory.mkdir()
        report = {
            "schema_version": 1, "report_id": directory.name, "workspace_id": workspace_id,
            "created_at": datetime.now(UTC).isoformat(), "state": "unverified",
            "source_repository": str(self.manager.source_repository),
            "workspace_path": str(self.manager.workspaces_directory / workspace_id),
            "baseline_commit": self.manager.baseline_commit, "head": None,
            "candidate_digest": None, "policy_digest": None,
            "valid_for_current_candidate": False, "changes": [], "tests": [], "artifacts": {},
            "existing_failures": [], "new_failures": [], "fixed_failures": [],
            "unverified": ["固定五项检查之外的功能、性能与安全行为未验证。",
                           "用户尚未审查并接受候选成果; 报告不改变 Job 状态。"],
            "report_path": str(directory / "report.json"),
        }
        try:
            fixed = fixed_files(self.manager)
            snapshot = capture(self.manager, workspace_id, fixed)
            report.update(head=snapshot.head, candidate_digest=snapshot.digest,
                          policy_digest=self.acceptance.policy_digest(fixed))
            changes, diff, unverified = build_diff(fixed, snapshot.files)
            report["changes"] = changes
            report["unverified"].extend(unverified)
            report["artifacts"]["diff"] = write_artifact(directory, "changes.diff", diff)
            self._record(workspace_id, directory, report, fixed)
            self._current(report, fixed)
        except ERRORS as exc:
            report["state"] = "rejected"
            report["valid_for_current_candidate"] = False
            report["unverified"].append(f"无法生成候选 Diff: {exc}")
        report["artifacts"]["markdown"] = write_artifact(directory, "report.md",
                                                        self._markdown(report))
        data = _json(report)
        if len(data) > JSON_LIMIT:
            raise ValueError("report metadata exceeds byte limit")
        write_artifact(directory, "report.json", data)
        if report["candidate_digest"] is not None:
            self._current(report, fixed)
            # Recheck after all artifacts have been written and before publication.
            # If stale, replace the unpublished summaries so they agree with JSON.
            if _json(report) != data:
                checked_path(directory, "report.md").unlink()
                report["artifacts"]["markdown"] = write_artifact(
                    directory, "report.md", self._markdown(report)
                )
                data = _json(report)
                checked_path(directory, "report.json").unlink()
                write_artifact(directory, "report.json", data)
        temporary = root / f"latest-{uuid4().hex}.tmp"
        try:
            temporary.write_bytes(_json({"report_id": report["report_id"],
                                         "sha256": hashlib.sha256(data).hexdigest()}))
            os.replace(temporary, root / "latest.json")
        finally:
            temporary.unlink(missing_ok=True)
        return report

    def show(self, workspace_id: str) -> dict:
        root = self._root(workspace_id)
        pointer = json.loads(read_regular(root, "latest.json", 1024))
        if not isinstance(pointer, dict):
            raise ValueError("invalid report pointer")
        report_id = identity(pointer.get("report_id"))
        directory = checked_path(root, report_id)
        raw = read_regular(directory, "report.json", JSON_LIMIT)
        report = json.loads(raw)
        if (not isinstance(report, dict) or report.get("schema_version") != 1
                or report.get("report_id") != report_id
                or report.get("workspace_id") != workspace_id
                or report.get("baseline_commit") != self.manager.baseline_commit
                or report.get("source_repository") != str(self.manager.source_repository)):
            raise ValueError("report provenance does not match this workspace")
        if (not isinstance(report.get("artifacts"), dict)
                or not isinstance(report.get("unverified"), list)
                or not isinstance(report.get("state"), str)):
            raise ValueError("invalid report structure")
        report["recorded_state"] = report["state"]
        try:
            if hashlib.sha256(raw).hexdigest() != pointer.get("sha256"):
                raise ValueError("saved report metadata changed")
            names = {"diff": "changes.diff", "markdown": "report.md"}
            names.update({f"{prefix}_{kind}": f"{prefix}.{extension}"
                          for prefix in ("baseline", "candidate")
                          for kind, extension in (("acceptance", "json"), ("log", "log"),
                                                  ("xml", "xml"))})
            if (report["state"] in {"passed", "existing_failure", "new_failure"}
                    and set(report["artifacts"]) != set(names)):
                raise ValueError("saved report lacks complete review evidence")
            for key, artifact in report["artifacts"].items():
                filename = names[key]
                if artifact["path"] != str(directory / filename):
                    raise ValueError("artifact reference is outside its report pack")
                data = read_regular(directory, filename, max(LOG_LIMIT, JSON_LIMIT * 4))
                if (len(data) != artifact["bytes"]
                        or hashlib.sha256(data).hexdigest() != artifact["sha256"]):
                    raise ValueError(f"saved artifact changed: {key}")
            if report["candidate_digest"] is not None:
                self._current(report, fixed_files(self.manager))
        except ERRORS as exc:
            report["state"] = "unverified"
            report["valid_for_current_candidate"] = False
            report["unverified"].append(f"保存的证据未确认: {exc}")
        return report
