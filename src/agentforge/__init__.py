"""AgentForge packages and compatibility for unchanged legacy imports."""

from agentforge import job_management, workspace_management

job_management.register_legacy_imports()
workspace_management.register_legacy_imports()
