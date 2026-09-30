# M5 Git 工作区设计

## 目的与范围

AgentForge 从 M4 记录的完整提交创建 Todo 工作区，保存工作区来源和生命周期。M5 只管理 Git 工作区；代码执行、补丁、Agent 和容器均留给后续步骤。

## 接口与数据

`WorkspaceManager(source_repository, workspaces_directory, baseline_commit)` 提供 `create()`、`get(id)` 和 `remove(id)`。每个工作区使用随机生成的 32 位十六进制 ID；目录为工作区根目录下的该 ID，记录写入 `.records/<id>.json`。记录包含来源仓库绝对路径、固定基线提交、工作区路径、创建及清理时间，以及 `creating`、`active`、`failed` 或 `removed` 状态。`get()` 对活动工作区实时检查 Git，返回是否有未提交修改或偏离基线的提交。

创建前验证来源是指定路径的 Git 仓库、固定提交确实存在、来源没有已暂存、未暂存或未跟踪文件，然后用 `git worktree add --detach` 从固定提交创建。来源仓库即使之后移动到其他提交，既有工作区仍绑定创建时的固定提交。

清理仅接受状态为 `active` 且 Git 工作区仍属于来源仓库的记录。存在文件改动、未跟踪文件、忽略文件或新提交时拒绝清理，不提供隐式强制删除。成功清理后保留 `removed` 记录以供追溯。创建、查询和清理失败给出明确异常与可检查的记录；不会自动覆盖已有目录。

## 使用与验证

仓库内 CLI 读取 `examples/todo_baseline.commit`，默认使用 `.local/todo_baseline` 和 `.local/workspaces`，提供创建、查询和清理命令。单元测试用临时 M4 仓库检验固定提交、来源隔离、脏来源拒绝、脏工作区拒绝、生命周期持久化和失败诊断。M5 不执行 Todo 代码，也不改变预置的红色基线。
