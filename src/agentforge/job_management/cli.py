"""Small command-line entry point for the local Job lifecycle demo."""

import argparse
from collections.abc import Sequence

from agentforge.job_management.repository import InMemoryJobRepository
from agentforge.job_management.service import JobService


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentForge learning CLI")
    parser.add_argument("command", choices=("demo",))
    parser.parse_args(argv)

    service = JobService(InMemoryJobRepository())

    created = service.create("demo-success", "Demonstrate a successful Job")
    print(f"{created.id}: {created.status.value}")
    completed = service.run_fake(created.id)
    print(f"{completed.id}: {completed.status.value}")

    created = service.create("demo-cancel", "Demonstrate cancellation")
    print(f"{created.id}: {created.status.value}")
    cancelled = service.cancel(created.id)
    print(f"{cancelled.id}: {cancelled.status.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
