# M5 工作区实施计划

**目标**：从 M4 固定提交建立独立 Git 工作区，持久记录生命周期，并在创建和清理时保护用户改动。

**设计**：`docs/superpowers/specs/2026-09-29-m5-workspace-design.md`

## 任务 1：管理器与行为测试

1. 在 `tests/unit/test_workspace_manager.py` 写失败测试：固定提交与来源隔离、跨管理器查询、脏来源拒绝、脏工作区和新提交拒绝清理、清理后记录保留、错误路径。
2. 在 `src/agentforge/workspace_management/manager.py` 实现最小持久记录和 Git 操作。错误要附带动作与路径；记录先写 `creating`，工作区创建失败写 `failed`。顶层包注册旧 `workspace_manager` 导入映射。
3. 运行该文件测试、根项目测试和 Ruff。

## 任务 2：仓库内入口与文档

1. 增加 `src/agentforge/workspace_management/cli.py`，提供 `create`、`show <id>`、`remove <id>`；仅从 M4 提交文件读取基线，不接受任意提交作为默认来源。CLI 命令使用功能目录内的模块路径。
2. 测试 CLI 的完整创建、查询和清理流程以及非零错误结果。
3. 更新根 README、阶段文档和根级项目架构与步骤文档，标明 M5 已完成、M6 待完成，写出使用和验证命令。
4. 用实际固定 Todo 基线运行一次可复现演示；再次运行根测试与 Ruff，检查 Git diff 和工作区状态。

## 限制

- 不修改 M4 模板或固定提交；不运行目标仓库代码。
- 不引入数据库、Docker、模型或网络服务。
- 清理不提供强制选项；有改动时让用户保留工作区并自行审查。
