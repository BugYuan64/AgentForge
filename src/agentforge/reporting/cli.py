"""Build and display bounded reports from existing workspace acceptance artifacts."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agentforge.reporting.service import ReportingService
from agentforge.workspace_management.manager import WorkspaceError, WorkspaceManager

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and show workspace verification reports")
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT / ".local" / "todo_baseline")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / ".local" / "workspaces")
    parser.add_argument(
        "--commit-file", type=Path, default=PROJECT_ROOT / "examples" / "todo_baseline.commit"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command, description in (
        ("build", "build a report from persisted diff and acceptance summaries"),
        ("show", "show the saved verification report"),
    ):
        subcommand = commands.add_parser(command, help=description)
        subcommand.add_argument("id", help="M5 workspace ID")
    arguments = parser.parse_args(argv)

    try:
        baseline_commit = arguments.commit_file.read_text(encoding="utf-8").strip()
        manager = WorkspaceManager(arguments.source, arguments.root, baseline_commit)
        service = ReportingService(manager)
        if arguments.command == "build":
            result = service.build(arguments.id)
        else:
            result = service.show(arguments.id)
    except (WorkspaceError, KeyError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("state") == "passed":
        return 0
    if result.get("state") in {"existing_failure", "new_failure"}:
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
