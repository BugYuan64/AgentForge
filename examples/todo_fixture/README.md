# FastAPI Todo 示例目标仓库

这是 AgentForge 的小型、独立练习仓库。它提供固定代码基线，让后续步骤练习隔离修改与验收；不是 AgentForge 的后端，也不保存真实用户数据。

## 当前功能与预置缺陷

- `POST /todos` 接收 JSON 标题，返回 201、从 1 递增的 ID、标题及 `completed: false`。
- `GET /todos/{todo_id}` 查询存在的 Todo，返回 200。
- 查询不存在的整数 ID **目前错误地返回 200** 和 `{"detail":"Todo not found"}`。预期应为 404；修复留给后续练习，当前测试必须真实失败。
- 每个 `create_app()` 实例拥有独立的内存数据；服务重启后数据消失。没有数据库、登录、前端或外部网络调用。

## 技术栈与目录

需要 Python 3.11+。FastAPI 提供 HTTP 路由，Pydantic 校验请求标题的字符串类型，Uvicorn 启动本地服务，pytest 与 Starlette 的 `TestClient` 验证行为；当前依赖使用 `httpx2`，以匹配[测试客户端文档](https://www.starlette.io/testclient/)。`requirements.lock` 固定直接及传递依赖；日常安装不要求 uv。

| 路径 | 作用 |
|---|---|
| `todo_app/main.py` | `create_app()`、内存 Todo 和两个 HTTP 接口；`app` 供 Uvicorn 启动 |
| `todo_app/__init__.py` | 标记应用包 |
| `tests/test_todos.py` | 正常行为和预置缺陷的 pytest 用例 |
| `requirements.in` | 人工维护的直接依赖 |
| `requirements.lock` | 精确版本的完整依赖集 |
| `.gitattributes`、`.gitignore` | 固定 Git 文本行尾，忽略本地环境与测试缓存 |
| `项目最终架构.md`、`阶段步骤实现.md` | 目标结构、当前状态和后续修复步骤 |

## 配置与启动

无需环境变量或密钥。在本仓库根目录运行以下 PowerShell 命令：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m uvicorn todo_app.main:app
```

服务默认监听本机 `127.0.0.1:8000`。可用另一个终端提交一个 Todo：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/todos -Method Post -ContentType application/json -Body '{"title":"学习 AgentForge"}'
```

## 验证基线

```powershell
.\.venv\Scripts\python.exe -m pytest -q -W error
git rev-parse HEAD
```

在 M4 基线提交上，pytest 应报告 **4 passed, 1 failed**，唯一失败是 `test_get_missing_todo_returns_404`：实际 200，期望 404。这里的退出码 1 是有意保留的教学基线，不代表所有检查通过。提交 ID 由 AgentForge 根目录的 `examples/todo_baseline.commit` 记录；修复时应从该提交创建独立工作区，不直接改本仓库。
