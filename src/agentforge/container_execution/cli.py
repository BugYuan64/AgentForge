"""Run the fixed Todo test suite in a constrained container from an M5 workspace."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agentforge.container_execution.runner import ContainerTestRunner, RunState
from agentforge.workspace_management.manager import WorkspaceError, WorkspaceManager

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run fixed Todo tests in Docker")
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT / ".local" / "todo_baseline")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / ".local" / "workspaces")
    parser.add_argument(
        "--commit-file", type=Path, default=PROJECT_ROOT / "examples" / "todo_baseline.commit"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    test = commands.add_parser("test", help="run the fixed Todo pytest command")
    test.add_argument("id", help="M5 workspace ID")
    arguments = parser.parse_args(argv)

    try:
        baseline_commit = arguments.commit_file.read_text(encoding="utf-8").strip()
        manager = WorkspaceManager(arguments.source, arguments.root, baseline_commit)
        result = ContainerTestRunner(manager).run(arguments.id)
    except (WorkspaceError, KeyError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    if result.state is RunState.TIMED_OUT:
        return 124
    if result.state is RunState.COMPLETED and result.exit_code is not None:
        return result.exit_code
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
