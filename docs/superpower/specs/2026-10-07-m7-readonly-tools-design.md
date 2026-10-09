# M7 工作区只读工具设计

## 范围与调用关系

在 `src/agentforge/workspace_tools/` 中提供列文件、读文件和字面搜索；CLI 与后续 Agent 使用相同的请求和结果。`workspace_tools.cli → ReadOnlyWorkspaceTools → WorkspaceManager / 文件系统`。每次调用使用 `WorkspaceManager.get(id, inspect_changes=False)` 校验活动工作区、Git 根目录和来源附着关系，跳过与只读调用无关的全量变更扫描；返回的 `has_changes=None` 表示未检查修改状态。M5 默认查询与清理仍执行完整检查。候选文件已有修改仍可读取；只做文件读取，不运行目标代码。

`ToolRequest(tool, workspace_id, path=".", query=None)` 使用普通 Python dataclass。工具名为 `list_files`、`read_file`、`search`。`ToolResult` 包含相同的工具、工作区和路径，另有 `status`（`completed/rejected/error`）、`output`、`truncated`、`notices` 和 `error`，提供 JSON 序列化。完成且截断的结果仍是成功调用，调用者必须检查 `truncated`。

## 路径与读取规则

- 只接收工作区相对路径，统一输出 `/` 分隔符。拒绝绝对路径、盘符、UNC、`..`、Windows 特殊路径和 `.git` 元数据。
- 逐级检查符号链接和 Windows reparse point（包括 junction），并核对实际路径仍在工作区内。显式指向链接的调用被拒绝；递归列文件和搜索跳过链接并记录数量，不进入链接目标。
- 列文件递归输出工作区相对文件名；读文件只接受常规 UTF-8 文本；搜索是大小写敏感的单行字面查询，输出 `文件:行号:内容`。不支持正则表达式或任意命令。
- 这是单用户、受信任本地仓库的文件工具；调用期间目录应保持稳定，不将路径预检查宣称为针对恶意并发替换的文件系统沙箱。

## 限额

可信宿主配置 `ToolLimits` 固定默认上限：正文 12,000 字符、单文件 256 KiB、目录发现 2,000 项、单次搜索读取 4 MiB。请求和 CLI 不提供提高上限的参数。正文达到上限时返回前缀并设 `truncated=true`；错误正文也受字符上限约束，截断时标记 `error_limit`。过大的显式文件读取被拒绝；搜索跳过过大文件并记录，发现或搜索总预算耗尽时返回部分结果及截断说明。非文本文件在搜索中跳过并记录。发现预算计入所有目录条目，跳过原因按数量汇总，避免提示本身无限增长。

## 验收

使用真实临时 Git 工作区验证三项正常行为、来源仓库和候选内容不变、未知或已移除工作区拒绝、路径越界和 Windows 路径别名拒绝、真实符号链接/junction 拒绝和跳过、文本与输入限额、结果序列化及 CLI 退出状态。最后运行根单元测试、Ruff 和文档路径检查；M7 完成后下一步为 M8。
