"""Job lifecycle, storage contract, service, and local demo."""

from importlib import import_module
from sys import modules
from types import ModuleType


def register_legacy_imports() -> None:
    """Keep the original Job imports usable without root-level Job files."""
    root = modules["agentforge"]
    for old_name, new_name in {
        "job_repository": "repository",
        "job_service": "service",
    }.items():
        module = import_module(f"{__name__}.{new_name}")
        modules[f"agentforge.{old_name}"] = module
        setattr(root, old_name, module)

    domain = ModuleType("agentforge.domain")
    domain.__path__ = []
    modules[domain.__name__] = domain
    root.domain = domain
    for old_name, new_name in {"job": "model", "job_status": "status"}.items():
        module = import_module(f"{__name__}.{new_name}")
        modules[f"{domain.__name__}.{old_name}"] = module
        setattr(domain, old_name, module)

    legacy_cli = ModuleType("agentforge.cli")

    def cli_attribute(name: str) -> object:
        if name == "main":
            return import_module(f"{__name__}.cli").main
        raise AttributeError(name)

    legacy_cli.__getattr__ = cli_attribute
    modules[legacy_cli.__name__] = legacy_cli
    root.cli = legacy_cli
