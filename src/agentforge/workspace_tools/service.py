"""Route the fixed workspace tool set through one request/result interface."""

from agentforge.container_execution.runner import ContainerTestRunner
from agentforge.workspace_management.manager import WorkspaceManager
from agentforge.workspace_tools.contracts import ToolLimits, ToolRequest, ToolResult
from agentforge.workspace_tools.inspection import InspectionTools
from agentforge.workspace_tools.patches import ModificationTools, WritePolicy
from agentforge.workspace_tools.readonly import ReadOnlyWorkspaceTools


class WorkspaceTools:
    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        limits: ToolLimits | None = None,
        policy: WritePolicy | None = None,
        test_runner: ContainerTestRunner | None = None,
    ) -> None:
        limits = limits or ToolLimits()
        self.readonly = ReadOnlyWorkspaceTools(workspace_manager, limits)
        self.modification = ModificationTools(workspace_manager, limits, policy)
        self.inspection = InspectionTools(workspace_manager, limits, test_runner)

    def execute(self, request: ToolRequest) -> ToolResult:
        if isinstance(request.tool, str) and request.tool in {"list_files", "read_file", "search"}:
            return self.readonly.execute(request)
        if request.tool == "apply_patch":
            return self.modification.execute(request)
        return self.inspection.execute(request)
