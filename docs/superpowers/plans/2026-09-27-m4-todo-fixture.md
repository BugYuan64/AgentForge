# M4 Todo Fixture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可重建的独立 FastAPI Todo Git 基线，基线上只有预置的“缺失 Todo 返回 200”验收测试失败。

**Architecture:** AgentForge 跟踪 `examples/todo_fixture/` 模板；生成器复制模板到被忽略的 `.local/todo_baseline/` 并在该目录创建独立 Git 初始提交。Todo 使用 `create_app()` 的进程内状态，模板测试直接通过 FastAPI `TestClient` 调用接口。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、Uvicorn、httpx2、pytest、Git；uv 仅用于生成锁定文件。

**Spec:** `docs/superpowers/specs/2026-09-27-m4-todo-fixture-design.md`

## Global Constraints

- 不改 AgentForge 的 M1–M3 业务代码；不实现 M5 工作区、Agent、数据库、容器或联网数据。
- 模板不是嵌套 Git 仓库；生成目标固定在 `.local/todo_baseline/`，已存在时不得覆盖。
- `requirements.lock` 固定直接及传递依赖；测试使用独立虚拟环境，不能改 AgentForge `.venv`。
- 基线保留一个真实失败，不标记 `skip` / `xfail`；报告必须区分示例仓库预期红灯与 AgentForge 测试绿灯。
- 示例新项目必须含准确命名的 `README.md`、`项目最终架构.md`、`阶段步骤实现.md`，标明已实现和规划。
- 除了示例仓库的固定基线提交，不自动提交用户已有的 AgentForge 改动。

## Review Focus

- 目标路径已存在：生成器测试应证实它拒绝覆盖且原内容不变。
- 不同临时目录：生成器测试应证实相同模板得到相同提交 ID，提交不依赖目录名。
- 父仓库隔离：生成器测试应核对生成仓库的 Git 顶层目录与 AgentForge 不同。
- 两个应用实例：API 测试应证实 `create_app()` 不共享 Todo 或 ID 计数器。
- 无效/缺失 Todo ID：API 测试应区别框架的非整数路径 422 与预置的不存在整数 ID 缺陷。

---

### Task 1: 独立示例的依赖与基础配置

**Files:**
- Create: `examples/todo_fixture/requirements.in`
- Create: `examples/todo_fixture/requirements.lock`
- Create: `examples/todo_fixture/.gitattributes`
- Create: `examples/todo_fixture/.gitignore`
- Modify: `.gitignore`

**Interfaces:**
- Produces: 可供 `python -m pip install -r requirements.lock` 安装的完整锁定依赖；测试环境可导入 `fastapi.testclient.TestClient`。

- [ ] **Step 1: 声明直接依赖**：`requirements.in` 逐行列出 `fastapi`、`uvicorn`、`httpx2`、`pytest`；模板 `.gitattributes` 规定文本文件 LF，模板 `.gitignore` 排除 `.venv/`、`__pycache__/`、`.pytest_cache/`；根 `.gitignore` 加入 `.local/`。
- [ ] **Step 2: 生成锁定文件**：在模板目录运行 `uv pip compile requirements.in --python-version 3.11 --universal -o requirements.lock`；检查所有安装项均为精确版本 `==`。
- [ ] **Step 3: 验证安装**：在 `.local/` 内创建专用虚拟环境并安装锁定文件；运行 `python -c "import fastapi, httpx, pytest, uvicorn"`。预期退出码 0，且不修改根项目虚拟环境。

### Task 2: 以测试驱动最小 Todo API

**Files:**
- Create: `examples/todo_fixture/todo_app/__init__.py`
- Create: `examples/todo_fixture/todo_app/main.py`
- Create: `examples/todo_fixture/tests/test_todos.py`

**Interfaces:**
- Produces: `create_app() -> FastAPI`、供 Uvicorn 使用的 `app`；`POST /todos` 和 `GET /todos/{todo_id}`。
- Consumes: Task 1 的虚拟环境和依赖。

- [ ] **Step 1: 写创建测试**：`test_post_creates_todo` 提交 `{"title":"学习 AgentForge"}`，断言 201 与 `{"id":1,"title":"学习 AgentForge","completed":false}`；运行并确认因 API 尚不存在而失败。
- [ ] **Step 2: 实现创建接口**：用 Pydantic 请求模型接收标题，在 `create_app()` 内保存每实例独立的 Todo 字典和下一个 ID；只实现让创建测试通过的行为。运行该测试，预期通过。
- [ ] **Step 3: 写查询、隔离与路径测试**：`test_get_existing_todo` 创建后查询 ID 1，断言 200 和同一 Todo；`test_new_app_starts_empty` 让两个实例分别创建不同标题，断言各自首个 ID 为 1，且查询前一个实例时标题未被后一个覆盖；`test_non_integer_id_is_rejected` 断言 `GET /todos/not-an-int` 为 422。运行并确认因查询接口尚不存在而失败。
- [ ] **Step 4: 实现查询接口**：增加整数 `todo_id` 路由，存在时返回对应项；不存在时暂返回 200 与 `{"detail":"Todo not found"}`，这是刻意保留的基线缺陷。运行此时全部正常路径测试，预期通过。

### Task 3: 固定唯一预置失败

**Files:**
- Modify: `examples/todo_fixture/tests/test_todos.py`

**Interfaces:**
- Consumes: Task 2 的 `create_app() -> FastAPI`。
- Produces: `test_get_missing_todo_returns_404` 作为后续修复的验收测试。

- [ ] **Step 1: 写缺陷测试**：对全新应用请求 `GET /todos/999`，断言 404；运行并确认它真实失败，实际状态码为 200，而不是导入错误或异常。
- [ ] **Step 2: 确认红色基线**：不得修复为 404，也不得跳过该测试。运行模板全套 pytest，预期仅此测试失败，其余测试通过。

### Task 4: 以测试驱动可重建 Git 基线

**Files:**
- Create: `scripts/create_todo_baseline.py`
- Create: `tests/unit/test_create_todo_baseline.py`

**Interfaces:**
- Produces: `create_baseline(template: Path, destination: Path) -> str`，返回 40 位提交 ID；无参数 CLI 固定使用项目模板和 `.local/todo_baseline/`。
- Consumes: Task 1–3 的完整模板内容。

- [ ] **Step 1: 写生成器测试**：两个不同 `tmp_path` 目标产生相同提交 ID；各自 Git 顶层为自身；模板无 `.git`。预先存在的目标与标记文件必须保持不变并引发 `FileExistsError`。运行并确认因生成器尚不存在而失败。
- [ ] **Step 2: 实现最小生成器**：复制模板，先拒绝已存在目标；用 SHA-1 格式的本地 Git 仓库、`main` 分支、固定作者与提交者 `AgentForge Fixture <fixture@agentforge.invalid>`、固定时间 `2020-01-01T00:00:00 +0000`、消息 `fixture: initial Todo baseline` 创建提交。禁用签名与模板钩子对初始提交的影响；运行 Step 1 测试，预期通过。
- [ ] **Step 3: 回归检查**：运行全部 AgentForge 测试与 Ruff，预期均通过；检查 `.local/` 被根仓库忽略。

### Task 5: 示例文档、真实基线与最终核验

**Files:**
- Create: `examples/todo_fixture/README.md`
- Create: `examples/todo_fixture/项目最终架构.md`
- Create: `examples/todo_fixture/阶段步骤实现.md`
- Create: `examples/todo_baseline.commit`
- Modify: `README.md`
- Modify: `阶段目标.md`

**Interfaces:**
- Consumes: Task 1–4 的模板、锁定文件和生成器。
- Produces: M5 可读取的固定提交 ID 文件和清楚的复现命令。

- [ ] **Step 1: 写示例文档**：目标、已实现 API、故意缺陷、依赖、目录、环境、配置、启动和验证方法写入示例 README；架构与阶段文档分别标明当前实现和目标/待完成内容。
- [ ] **Step 2: 生成实际基线**：运行 `python scripts/create_todo_baseline.py`，记录输出的完整 40 位提交 ID 到 `examples/todo_baseline.commit`。若目标已存在，不删除或改用其他路径；停下并请用户决定如何处理。
- [ ] **Step 3: 在生成仓库验证**：从其锁定文件安装依赖，在生成仓库运行 pytest；预期只有 `test_get_missing_todo_returns_404` 失败，其余通过，失败原因是 200 与 404。检查 `git rev-parse HEAD` 与记录一致，`git status --short` 无未忽略改动。
- [ ] **Step 4: 更新根文档与回归检查**：README 和阶段目标只把 M4 写成已完成，M5 仍待完成；README 解释 M4 新增文件的作用和复现步骤。运行根 `python -m pytest` 和 `python -m ruff check src tests scripts examples/todo_fixture`。预期根测试与 Ruff 通过；模板红灯在报告中明确为预期。
