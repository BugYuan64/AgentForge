# AgentForge

AgentForge 是一个学习式开发的软件工程 Agent 项目：在受控工作区中处理代码任务，并交付可审查的修改和验证证据。

## 项目文档

- [最终目标.md](最终目标.md)：项目目的、最终使用效果、架构、技术栈和完成标准。
- [阶段目标.md](阶段目标.md)：各阶段的学习重点、逐步实施内容和验收条件。
- [项目最终架构.md](项目最终架构.md)：当前实现与目标架构中各组成部分的职责和数据流。
- [阶段步骤实现.md](阶段步骤实现.md)：逐阶段、逐步骤的状态、交付物和完成标准。

## 当前状态

仓库保留最小 Python 项目配置与开发工具设置，已完成 M1 的状态规则、M2 的 Job 与内存存储、M3 的应用服务和 CLI 演示、M4 的固定 FastAPI Todo 示例目标仓库，以及 M5 的本地 Git 工作区管理。M3 的执行仍是确定性的模拟成功；M5 只隔离代码目录，不执行目标代码。真实 Agent、容器执行器、AgentForge API、Worker 和前端仍在规划中。

开发时一次只完成 [阶段目标.md](阶段目标.md) 中的一个步骤。下一步是 M6：在受限容器中运行预设测试命令。AgentForge 的核心领域对象仍用普通 Python；示例 FastAPI 项目在 HTTP 请求边界使用 Pydantic。

## 技术栈、目录与环境

当前 AgentForge 使用 Python 3.11+、标准库、Git、pytest 和 Ruff；没有运行时第三方依赖。实现按功能放在 `src/agentforge/job_management/` 与 `src/agentforge/workspace_management/`，目录内再按职责拆分：

```text
src/agentforge/
├─ __init__.py          集中注册旧导入路径的兼容映射
├─ job_management/      Job 领域对象、状态规则、存储接口、应用服务和演示 CLI
│  ├─ model.py          Job 数据对象
│  ├─ status.py         JobStatus 与合法转换
│  ├─ repository.py     JobRepository 协议与内存实现
│  ├─ service.py        创建、查询、取消和假执行用例
│  └─ cli.py            Job 生命周期演示入口
├─ workspace_management/ Git 工作区管理及生命周期
│  ├─ manager.py        固定提交校验、工作区生命周期与清理保护
│  └─ cli.py            创建、查询和清理命令
```

新实现从功能目录导入；包的 `__init__.py` 注册旧导入名，使未修改的 `tests/` 继续工作。旧的 `python -m agentforge.cli` 与 `python -m agentforge.workspace_cli` 命令改为上面两个功能目录内的入口。`tests/unit/` 验证当前行为；`examples/todo_fixture/` 是独立的 FastAPI/Pydantic Todo 模板；`scripts/create_todo_baseline.py` 生成固定本地仓库；`docs/superpowers/` 保存各步设计与实施记录。`.local/todo_baseline/` 和 `.local/workspaces/` 是被 Git 忽略的运行数据，不属于 Python 代码包。目标中的 Docker、PostgreSQL、FastAPI 服务、Vue 等技术只在对应阶段引入。

需要已安装 Git 和 Python 3.11+。在项目根目录创建虚拟环境并安装开发依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

当前无需环境变量或服务配置。Todo 示例有单独的依赖文件和启动说明；AgentForge 本身尚无 Web 服务。下面的命令从项目根目录运行。

## 本地演示与验证

在项目根目录运行（需要 Python 3.11+ 和已安装的开发依赖）：

```powershell
.\.venv\Scripts\python.exe -m agentforge.job_management.cli demo
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests scripts examples/todo_fixture
```

CLI 每次启动都创建新的内存存储；任务状态只在这次运行中有效，不能跨命令或进程查询。

## M4 示例仓库

| 路径 | 作用 |
|---|---|
| `examples/todo_fixture/` | 受 AgentForge 管理的 Todo 源码模板，含三个启动/架构/阶段文档 |
| `examples/todo_fixture/todo_app/main.py` | 小型 FastAPI Todo 应用；刻意保留缺失 ID 返回 200 的缺陷 |
| `examples/todo_fixture/tests/test_todos.py` | 四个正常行为检查和一个预期失败的缺陷验收测试 |
| `examples/todo_fixture/requirements.in`、`requirements.lock` | 直接依赖与全部依赖的固定版本 |
| `scripts/create_todo_baseline.py` | 从模板生成独立本地 Git 仓库，存在时拒绝覆盖 |
| `examples/todo_baseline.commit` | M4 基线的完整提交 ID，供 M5 使用 |
| `.local/todo_baseline/` | 生成的独立仓库；被忽略，不属于 AgentForge 的 Git 提交 |

首次在 AgentForge 根目录生成本地基线，并在生成仓库中安装和验证：

```powershell
.\.venv\Scripts\python.exe scripts\create_todo_baseline.py
python -m venv .local\todo_baseline\.venv
.\.local\todo_baseline\.venv\Scripts\python.exe -m pip install -r .local\todo_baseline\requirements.lock
git -C .local\todo_baseline rev-parse HEAD
Get-Content examples\todo_baseline.commit
Push-Location .local\todo_baseline
.\.venv\Scripts\python.exe -m pytest -q -W error
Pop-Location
```

生成命令只运行一次；若目录已存在，它会拒绝覆盖。两条提交 ID 应相同。基线测试的预期结果是 **4 passed, 1 failed**，唯一失败为 `test_get_missing_todo_returns_404`：实际 200、期望 404。这个红灯是 M4 交付的练习题，不是 AgentForge 自身测试失败，也不能通过跳过测试来掩盖。示例项目的单独启动方式见其 [README](examples/todo_fixture/README.md)。

## M5 工作区管理

先按上节生成 `.local/todo_baseline/`。M5 命令默认读取 `examples/todo_baseline.commit`，在 `.local/workspaces/` 建立与来源仓库隔离的工作区。命令输出 JSON，`create` 返回的 `id` 用于后续查询和清理：

```powershell
.\.venv\Scripts\python.exe -m agentforge.workspace_management.cli create
.\.venv\Scripts\python.exe -m agentforge.workspace_management.cli show <id>
.\.venv\Scripts\python.exe -m agentforge.workspace_management.cli remove <id>
```

`src/agentforge/workspace_management/manager.py` 验证固定提交、检查来源仓库状态、调用 `git worktree`，并在 `.local/workspaces/.records/` 保存生命周期记录。创建时来源仓库有已暂存、未暂存或未跟踪修改会报错。`show` 实时报告工作区是否有变更；`remove` 对已修改文件、未跟踪或忽略文件、新增提交一律拒绝，成功后保留 `removed` 记录。M5 没有强制清理命令；需要先自行审查并处理候选修改。`tests/unit/test_workspace_manager.py` 和 `test_workspace_cli.py` 覆盖隔离、失败路径与清理保护。
