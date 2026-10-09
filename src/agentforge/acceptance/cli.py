"""Run host-controlled baseline and candidate acceptance checks for an M5 workspace."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agentforge.acceptance.service import AcceptanceService
from agentforge.workspace_management.manager import WorkspaceError, WorkspaceManager

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record and verify fixed Todo acceptance checks")
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT / ".local" / "todo_baseline")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / ".local" / "workspaces")
    parser.add_argument(
        "--commit-file", type=Path, default=PROJECT_ROOT / "examples" / "todo_baseline.commit"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command, description in (
        ("baseline", "record checks before candidate changes"),
        ("verify", "verify the candidate using the recorded baseline"),
        ("show", "show the saved acceptance result"),
    ):
        subcommand = commands.add_parser(command, help=description)
        subcommand.add_argument("id", help="M5 workspace ID")
    arguments = parser.parse_args(argv)

    try:
        baseline_commit = arguments.commit_file.read_text(encoding="utf-8").strip()
        manager = WorkspaceManager(arguments.source, arguments.root, baseline_commit)
        service = AcceptanceService(manager)
        if arguments.command == "baseline":
            result = service.baseline(arguments.id)
        elif arguments.command == "verify":
            result = service.verify(arguments.id)
        else:
            result = service.show(arguments.id)
    except (WorkspaceError, KeyError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("state") in {"recorded", "passed"}:
        return 0
    if result.get("state") in {"existing_failure", "new_failure"}:
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
