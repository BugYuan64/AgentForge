"""Local command-line operations for the M5 Todo workspace."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agentforge.workspace_management.manager import WorkspaceError, WorkspaceManager

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage local Todo Git workspaces")
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT / ".local" / "todo_baseline")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / ".local" / "workspaces")
    parser.add_argument(
        "--commit-file", type=Path, default=PROJECT_ROOT / "examples" / "todo_baseline.commit"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create", help="create a detached workspace at the fixed baseline")
    show = commands.add_parser("show", help="show a saved record and current change state")
    show.add_argument("id")
    remove = commands.add_parser("remove", help="remove a clean workspace and retain its record")
    remove.add_argument("id")
    arguments = parser.parse_args(argv)

    try:
        baseline_commit = arguments.commit_file.read_text(encoding="utf-8").strip()
        manager = WorkspaceManager(arguments.source, arguments.root, baseline_commit)
        if arguments.command == "create":
            record = manager.create()
        elif arguments.command == "show":
            record = manager.get(arguments.id)
        else:
            record = manager.remove(arguments.id)
    except (WorkspaceError, KeyError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
