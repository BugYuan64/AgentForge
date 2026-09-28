# AgentForge

AgentForge 是一个学习式开发的软件工程 Agent 项目：在受控工作区中处理代码任务，并交付可审查的修改和验证证据。

## 项目文档

- [最终目标.md](最终目标.md)：项目目的、最终使用效果、架构、技术栈和完成标准。
- [阶段目标.md](阶段目标.md)：各阶段的学习重点、逐步实施内容和验收条件。

## 当前状态

仓库保留最小 Python 项目配置与开发工具设置，已完成 M1 的状态规则、M2 的 Job 与内存存储、M3 的应用服务和 CLI 演示，以及 M4 的固定 FastAPI Todo 示例目标仓库。M3 的执行仍是确定性的模拟成功；M4 示例不等于 AgentForge 已具备真实 Agent、目标代码执行器、API、Worker 或前端。

开发时一次只完成 [阶段目标.md](阶段目标.md) 中的一个步骤。下一步是 M5：从 M4 的固定提交创建独立工作区。AgentForge 的核心领域对象仍用普通 Python；示例 FastAPI 项目在 HTTP 请求边界使用 Pydantic。

## 本地演示与验证

在项目根目录运行（需要 Python 3.11+ 和已安装的开发依赖）：

```powershell
.\.venv\Scripts\python.exe -m agentforge.cli demo
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
