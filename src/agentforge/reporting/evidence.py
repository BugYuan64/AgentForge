"""Bounded host evidence reads, independent validation and durable copies."""

import hashlib
import json
import re
import stat
from pathlib import Path

from agentforge.acceptance.checks import CHECK_COMMAND, EXPECTED_TESTS, validate_evidence
from agentforge.acceptance.service import AcceptanceService
from agentforge.workspace_tools.paths import checked_path

LOG_LIMIT = 8 * 1024 * 1024
XML_LIMIT = 1024 * 1024
JSON_LIMIT = 4 * 1024 * 1024


def identity(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError("report/workspace/run ID must be 32 lowercase hexadecimal characters")
    return value


def read_regular(root: Path, relative: str, limit: int) -> bytes:
    path = checked_path(root, relative)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("evidence must be a regular file without hard links")
    if info.st_size > limit:
        raise ValueError("complete evidence exceeds byte limit")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("complete evidence exceeds byte limit")
    return data


def write_artifact(directory: Path, filename: str, data: bytes) -> dict:
    path = checked_path(directory, filename, allow_missing=True)
    with path.open("xb") as stream:
        stream.write(data)
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def copy_record(service: AcceptanceService, workspace_id: str, record: dict,
                directory: Path, prefix: str, artifacts: dict) -> None:
    """Capture exact saved JSON, full log and XML; compare XML to its log transport."""
    root = service.manager.workspaces_directory
    report_id = identity(record.get("report_id"))
    raw = read_regular(root, f".acceptance/{workspace_id}/{report_id}.json", XML_LIMIT)
    if json.loads(raw) != record:
        raise ValueError("acceptance record changed while copying evidence")
    artifacts[f"{prefix}_acceptance"] = write_artifact(directory, f"{prefix}.json", raw)
    run = record.get("execution")
    if not isinstance(run, dict):
        raise ValueError("candidate has no execution evidence")
    run_id = identity(run.get("run_id"))
    paths = {}
    for extension, limit in (("log", LOG_LIMIT), ("xml", XML_LIMIT)):
        relative = f".runs/{run_id}.{extension}"
        expected = root / ".runs" / f"{run_id}.{extension}"
        if run.get(f"{extension}_path") != str(expected):
            raise ValueError("execution evidence path is outside its host run")
        data = read_regular(root, relative, limit)
        artifact = write_artifact(directory, f"{prefix}.{extension}", data)
        artifact["source_path"] = str(expected)
        artifacts[f"{prefix}_{extension}"] = artifact
        paths[extension] = Path(artifact["path"])
    outcomes = validate_evidence(paths["log"], paths["xml"], run.get("exit_code"))
    if outcomes != run.get("outcomes"):
        raise ValueError("JUnit evidence and saved test summary disagree")
    if (not service.valid_execution(run, baseline=True)
            or not isinstance(run.get("image_id"), str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", run["image_id"])):
        raise ValueError("checks are incomplete or lack an immutable image")
    environment = run.get("environment")
    if (not isinstance(environment, dict) or environment.get("command") != list(CHECK_COMMAND)
            or environment.get("image_id") != run["image_id"]
            or set(outcomes) != set(EXPECTED_TESTS)):
        raise ValueError("execution command or environment is inconsistent")
