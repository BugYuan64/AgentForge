# M6 Container Execution Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task; checkboxes track completion.

**Goal:** Run one fixed Todo pytest command inside a constrained Docker container from an M5 workspace and retain its exit code and log.

**Architecture:** A new `container_execution` package validates an active M5 record, inspects a prebuilt local image, and drives Docker create/start/wait/logs/remove without accepting arbitrary commands. A small CLI invokes it by workspace ID; a separate Dockerfile installs the locked Todo dependencies.

**Tech Stack:** Python 3.11 standard library, Docker CLI, Git worktree, pytest, Ruff.

**Spec:** `docs/superpower/specs/2026-09-30-m6-container-execution-design.md`

## Global Constraints

- Keep implementation in the original AgentForge checkout and preserve existing uncommitted documentation edits.
- Only run `python -m pytest -q -W error -p no:cacheprovider tests/test_todos.py` in the container; no caller supplied command or bind mount.
- Use a local image ID, a read only workspace mount, non root user, disabled network, CPU/memory/process limits and bounded execution time.
- Keep M4 fixed commit and Todo fixture unchanged; keep source repository and candidate worktree unwritten by the container.
- Mark M6 complete in root documents only after actual Docker acceptance runs.

## Review Focus

- Docker Engine or image unavailable: produce a diagnostic log and infrastructure state without changing source or workspace.
- A candidate with uncommitted changes remains runnable; removed, unknown or detached workspaces are rejected before Docker.
- A red Todo test returns its real exit code and log; it is not classified as infrastructure failure.
- A timed out test leaves no running container and retains partial logs.
- A Unicode Windows workspace path is passed as one `--mount` argument without shell interpolation.

## Task 1: Fixed container runner

**Files:** Create `src/agentforge/container_execution/__init__.py`, `src/agentforge/container_execution/runner.py`; test in `tests/unit/test_container_runner.py`.

**Interfaces:** `ContainerTestRunner(workspace_manager: WorkspaceManager, image: str = "agentforge-todo-test:m6", timeout_seconds: float = 30.0)`; `run(workspace_id: str) -> TestRunResult`. Result fields: run/workspace IDs, image ID, state, exit code, elapsed seconds, log path and error.

- [x] Write a failing test with a fake Docker CLI process: only active M5 workspace accepted; fixed command, image ID, read only mount, no source or socket mount, all limits present.
- [x] Run that test and confirm the runner is missing.
- [x] Implement local image inspection and `docker create/start/wait/logs/rm` with an argument list, bounded control calls and a persistent log.
- [x] Run the focused test, then add failing tests for red pytest exit, Docker unavailable, timeout cleanup and changed candidate workspace.
- [x] Implement only the missing behavior and rerun focused tests.

## Task 2: Image and CLI

**Files:** Create `containers/todo-test/Dockerfile`, `src/agentforge/container_execution/cli.py`; test in `tests/unit/test_container_cli.py`.

- [x] Write a failing CLI test for workspace ID input, JSON result and exit status distinction.
- [x] Add a Dockerfile that installs `examples/todo_fixture/requirements.lock` via its build context, without modifying the M4 fixture.
- [x] Implement `python -m agentforge.container_execution.cli test <id>` using M5 default source/root/commit file and the fixed image.
- [x] Run CLI and runner unit tests, full AgentForge tests and Ruff.

## Task 3: Real Docker acceptance and documentation

**Files:** Update `README.md`, `最终目标.md`, `阶段目标.md`; add Docker integration checks under `tests/integration/` if an Engine is available.

- [x] Build the controlled image and run M4's fixed baseline through the new CLI; confirm 4 passed, 1 failed, exit code 1 and a preserved log.
- [x] Verify the source Git HEAD/status is unchanged, candidate mount is read only, and a timed out candidate leaves no container.
- [x] Confirm the local Engine is available and run the Docker acceptance checks.
- [x] Update the three root documents with actual capability and status, then check links, `git diff --check`, tests and Ruff.
