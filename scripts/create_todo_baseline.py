"""Copy the Todo fixture and commit a reproducible local Git baseline."""

import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "examples" / "todo_fixture"
DESTINATION = PROJECT_ROOT / ".local" / "todo_baseline"
COMMIT_MESSAGE = "fixture: initial Todo baseline"


def _git(repository: Path, environment: dict[str, str], *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def create_baseline(template: Path, destination: Path) -> str:
    """Create an independent Git repository without replacing an existing path."""
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Refusing to overwrite existing path: {destination}")
    if not template.is_dir() or (template / ".git").exists():
        raise ValueError(f"Expected a fixture template without .git: {template}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        template,
        destination,
        ignore=shutil.ignore_patterns(".venv", "__pycache__", ".pytest_cache", "*.pyc"),
    )

    environment = os.environ.copy()
    for name in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CONFIG_PARAMETERS",
    ):
        environment.pop(name, None)
    for name in list(environment):
        if name.startswith("GIT_CONFIG_"):
            environment.pop(name)
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_AUTHOR_NAME="AgentForge Fixture",
        GIT_AUTHOR_EMAIL="fixture@agentforge.invalid",
        GIT_COMMITTER_NAME="AgentForge Fixture",
        GIT_COMMITTER_EMAIL="fixture@agentforge.invalid",
        GIT_AUTHOR_DATE="2020-01-01T00:00:00 +0000",
        GIT_COMMITTER_DATE="2020-01-01T00:00:00 +0000",
    )

    with TemporaryDirectory() as empty_git_template:
        _git(
            destination,
            environment,
            "init",
            "--object-format=sha1",
            "--initial-branch=main",
            f"--template={empty_git_template}",
        )
    _git(destination, environment, "-c", "core.autocrlf=false", "add", "--all")
    _git(
        destination,
        environment,
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--no-verify",
        "-m",
        COMMIT_MESSAGE,
    )
    return _git(destination, environment, "rev-parse", "HEAD")


if __name__ == "__main__":
    print(create_baseline(TEMPLATE, DESTINATION))
