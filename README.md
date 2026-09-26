# AgentForge

AgentForge 是一个学习式的软件工程 Agent 项目。长期目标是让单个 Agent 在隔离工作区中完成代码修改、运行可信验证，并交付可审查的 Diff 和执行记录。

M0 已确认项目起点。项目 Python 源码已清空，目前没有可运行的 API、Worker、CLI 或 Agent。后续按一个模块一轮的方式推进。

- [学习式开发路线](AgentForge_Learning_Roadmap.md)：模块顺序、每轮验收和第一版范围。
- [原项目方案](AgentForge_Project_Plan_Optimized..md)：长期目标与设计背景。

当前保留了最小 Python 项目配置，以及供下一模块使用的 `src/agentforge/domain/` 和 `tests/unit/` 目录。本地 `.venv/` 是可重建的开发环境，不属于项目实现。

## M0 起点记录

- 当前 `.git` 已按要求删除，目录中的项目文件仍在；开始下一模块前需要重新建立仓库和版本基线。原本地提交 `88fd0bc` 不再属于此目录。
- 本地使用 Python 3.11；pytest 与 Ruff 已安装。测试入口是 `.venv/Scripts/python.exe -m pytest -q`，单元测试放在 `tests/unit/`。
- 目前没有测试用例，pytest 收集到 0 项并返回退出码 5；这是当前真实状态，不表示测试通过。M1 将先写 Job 状态规则的失败测试，再实现规则。
- 后续示例目标选用一个**独立的最小 FastAPI Todo 仓库**。它只需基本 Todo 接口、pytest 和一个可复现的小型缺陷；到 M4 准备工作区时创建该仓库并固定基线提交。本轮不编写示例应用。

M0 的开发工具已核对；Git 版本基线待重新建立。进入 M1 前，先审查这些选择是否适合你的学习节奏。
