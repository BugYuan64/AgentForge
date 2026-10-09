"""Use bounded file, patch, Git and test tools on an active M5 workspace."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agentforge.workspace_management.manager import WorkspaceError, WorkspaceManager
from agentforge.workspace_tools.contracts import ToolLimits, ToolRequest, ToolStatus
from agentforge.workspace_tools.service import WorkspaceTools

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Use tools in an active M5 workspace")
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT / ".local" / "todo_baseline")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / ".local" / "workspaces")
    parser.add_argument(
        "--commit-file", type=Path, default=PROJECT_ROOT / "examples" / "todo_baseline.commit"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list-files", help="list files under a relative directory")
    listing.add_argument("id", help="M5 workspace ID")
    listing.add_argument("path", nargs="?", default=".")
    reading = commands.add_parser("read-file", help="read a relative UTF-8 text file")
    reading.add_argument("id", help="M5 workspace ID")
    reading.add_argument("path")
    searching = commands.add_parser("search", help="search text for a literal query")
    searching.add_argument("id", help="M5 workspace ID")
    searching.add_argument("query")
    searching.add_argument("path", nargs="?", default=".")
    applying = commands.add_parser("apply-patch", help="apply an allowed UTF-8 unified patch")
    applying.add_argument("id", help="M5 workspace ID")
    applying.add_argument("patch_file", type=Path, help="local UTF-8 patch file")
    for command, description in (
        ("status", "show candidate Git status"),
        ("diff", "show candidate diff against the baseline"),
        ("run-tests", "run the predetermined M6 container test command"),
    ):
        operation = commands.add_parser(command, help=description)
        operation.add_argument("id", help="M5 workspace ID")
    arguments = parser.parse_args(argv)

    try:
        patch = None
        if arguments.command == "apply-patch":
            patch_limit = ToolLimits().max_patch_bytes
            with arguments.patch_file.open("rb") as patch_input:
                patch_bytes = patch_input.read(patch_limit + 1)
            if len(patch_bytes) > patch_limit:
                raise ValueError(f"patch exceeds the {patch_limit}-byte limit")
            patch = patch_bytes.decode("utf-8")
        baseline_commit = arguments.commit_file.read_text(encoding="utf-8").strip()
        manager = WorkspaceManager(arguments.source, arguments.root, baseline_commit)
        request = ToolRequest(
            tool=arguments.command.replace("-", "_"),
            workspace_id=arguments.id,
            path=getattr(arguments, "path", "."),
            query=getattr(arguments, "query", None),
            patch=patch,
        )
        result = WorkspaceTools(manager).execute(request)
    except (WorkspaceError, KeyError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    if arguments.command == "run-tests":
        details = result.details or {}
        if details.get("state") == "timed_out":
            return 124
        if details.get("state") == "completed" and result.status is ToolStatus.COMPLETED:
            exit_code = details.get("exit_code")
            return exit_code if type(exit_code) is int else 2
        return 2
    return 0 if result.status is ToolStatus.COMPLETED else 2


if __name__ == "__main__":
    raise SystemExit(main())
