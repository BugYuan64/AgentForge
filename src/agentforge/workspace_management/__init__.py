"""Local Git worktree management for code tasks."""

from importlib import import_module
from sys import modules
from types import ModuleType


def register_legacy_imports() -> None:
    """Keep the original workspace imports usable without root-level files."""
    root = modules["agentforge"]
    manager = import_module(f"{__name__}.manager")
    modules["agentforge.workspace_manager"] = manager
    root.workspace_manager = manager

    legacy_cli = ModuleType("agentforge.workspace_cli")

    def cli_attribute(name: str) -> object:
        if name in {"main", "PROJECT_ROOT"}:
            return getattr(import_module(f"{__name__}.cli"), name)
        raise AttributeError(name)

    legacy_cli.__getattr__ = cli_attribute
    modules[legacy_cli.__name__] = legacy_cli
    root.workspace_cli = legacy_cli
