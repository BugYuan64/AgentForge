# AgentForge

AgentForge 是一个学习式开发的软件工程 Agent 项目：在受控工作区中处理代码任务，并交付可审查的修改和验证证据。

## 项目文档

- [最终目标.md](最终目标.md)：项目目的、当前实现与目标架构、技术栈、数据流和完成标准。
- [阶段目标.md](阶段目标.md)：M0–M28 的实施顺序、状态、前置依赖、交付物和验收条件。
- [docs/superpower/](docs/superpower/)：各步骤的设计和计划；完成后的必要验收记录归入对应计划，不保留单独的工具临时目录。

## 当前状态

仓库保留最小 Python 项目配置与开发工具设置，已完成 M1 的状态规则、M2 的 Job 与内存存储、M3 的应用服务和 CLI 演示、M4 的固定 FastAPI Todo 示例目标仓库、M5 的本地 Git 工作区管理、M6 的受限容器测试、M7 的受控只读文件工具，以及 M8 的补丁、状态/Diff 和固定测试工具。M8 已通过真实容器验收：预设补丁将候选 Todo 测试从 4 passed、1 failed 修复为 5 passed，来源仓库保持不变。M9 的独立验收器已完成并通过验收：记录修改前基线，对固定检查结果分类，并将报告绑定候选内容与环境。M3 的执行仍是确定性的模拟成功；M6/M9 只运行预设的 Todo pytest 命令，不接受任意命令。M10 综合 Diff/报告、真实 Agent、AgentForge API、Worker 和前端仍在规划中。

开发时一次只完成 [阶段目标.md](阶段目标.md) 中的一个步骤。当前 M0–M9 已完成，M10 尚未开始。AgentForge 的核心领域对象仍用普通 Python；示例 FastAPI 项目在 HTTP 请求边界使用 Pydantic。

## 技术栈、目录与环境

当前 AgentForge 使用 Python 3.11+、标准库、Git、Docker、pytest 和 Ruff；没有 Python 运行时第三方依赖。实现按功能放在 `src/agentforge/job_management/`、`src/agentforge/workspace_management/`、`src/agentforge/container_execution/`、`src/agentforge/workspace_tools/` 与 `src/agentforge/acceptance/`，目录内再按职责拆分：

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
├─ container_execution/ 受限容器内的固定 Todo 测试
│  ├─ runner.py         校验工作区、控制 Docker、保存退出码和日志
│  └─ cli.py            按工作区 ID 运行固定测试
├─ acceptance/          修改前基线、受保护检查与候选版本绑定
│  ├─ snapshot.py       固定提交原始字节、候选快照、范围保护与 SHA256
│  ├─ checks.py         固定五项检查、JUnit 传输与证据校验
│  ├─ service.py        基线持久化、同镜像比较、失败分类与过期检测
│  └─ cli.py            baseline / verify / show JSON 命令入口
└─ workspace_tools/     活动工作区的受控文件、补丁、Git 查询与测试工具
   ├─ contracts.py      统一请求、结果与宿主控制的限制
   ├─ paths.py          相对路径、Git 元数据与链接保护
   ├─ readonly.py       列文件、UTF-8 读取与字面搜索
   ├─ patches.py        宿主写入范围、严格文本补丁与失败回滚
   ├─ inspection.py     有界状态/Diff 查询与 M6 固定测试适配
   ├─ service.py        WorkspaceTools 统一工具路由
   └─ cli.py            所有工作区工具的 JSON 命令入口
```

新实现从功能目录导入；包的 `__init__.py` 注册旧导入名，使原有测试继续工作。旧的 `python -m agentforge.cli` 与 `python -m agentforge.workspace_cli` 命令改为功能目录内的入口。`tests/unit/` 验证当前行为；`tests/integration/` 单独验收真实 Docker；`examples/todo_fixture/` 是独立的 FastAPI/Pydantic Todo 模板；`scripts/create_todo_baseline.py` 生成固定本地仓库；`containers/todo-test/Dockerfile` 安装示例的锁定依赖；`docs/superpower/` 保存各步设计、实施计划与必要的验收记录。`.local/todo_baseline/` 和 `.local/workspaces/` 是被 Git 忽略的运行数据，不属于 Python 代码包。目标中的 PostgreSQL、AgentForge FastAPI 服务、Vue 等技术只在对应阶段引入。

需要已安装 Git 和 Python 3.11+。在项目根目录创建虚拟环境并安装开发依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

当前无需模型密钥或数据库。运行 M6/M8/M9 的固定测试需本机 Docker Engine 的 Linux 容器模式，并先构建下文的本地镜像；测试容器自身不联网。Todo 示例有单独的依赖文件和启动说明；AgentForge 本身尚无 Web 服务。下面的命令从项目根目录运行。

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

## M6 固定测试容器

Docker Engine 启动后，从项目根目录构建仅安装 Todo 锁定依赖的镜像；构建阶段需要取得基础镜像与依赖，运行测试时不会下载或安装：

```powershell
docker build -t agentforge-todo-test:m6 -f containers/todo-test/Dockerfile examples/todo_fixture
```

先用 M5 的 `create` 取得工作区 ID，再运行固定测试。`test` 输出 JSON；M4 基线预期为 `state: completed`、`exit_code: 1`，进程也返回 1，日志包含 **4 passed, 1 failed**。这表示预置 Todo 缺陷被真实复现，并非容器基础设施错误。

```powershell
.\.venv\Scripts\python.exe -m agentforge.container_execution.cli test <id>
.\.venv\Scripts\python.exe -m agentforge.workspace_management.cli remove <id>
```

执行器只接受 M5 的活动工作区 ID，只读挂载候选目录，固定执行 `python -m pytest -q -W error -p no:cacheprovider tests/test_todos.py`。容器使用非 root 用户、只读根文件系统、临时 `/tmp`、禁用网络、1 CPU、512 MiB 内存和 64 个进程的上限；不挂载来源仓库、宿主密钥或 Docker socket。默认测试等待上限为 30 秒，超时会停止并删除容器。日志留在 `.local/workspaces/.runs/<run-id>.log`；Docker 或镜像错误返回 `infrastructure_error` 并保留诊断。受限容器不等于可运行任意恶意租户代码的安全边界。

根目录 `python -m pytest` 只收集 `tests/unit/`。真实 Docker 验收须另行运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_container_execution.py -q
```

## M7 只读工作区工具

先用 M5 的 `create` 取得活动工作区 ID，再列文件、读取文件或搜索候选内容。命令默认使用 M5 相同的来源仓库、工作区根目录和固定提交文件；只读操作不会执行目标代码，也不需要 Docker：

```powershell
.\.venv\Scripts\python.exe -m agentforge.workspace_tools.cli list-files <id>
.\.venv\Scripts\python.exe -m agentforge.workspace_tools.cli list-files <id> todo_app
.\.venv\Scripts\python.exe -m agentforge.workspace_tools.cli read-file <id> todo_app/main.py
.\.venv\Scripts\python.exe -m agentforge.workspace_tools.cli search <id> "get_todo" todo_app
```

文件工具通过 M5 校验活动工作区，允许读取候选修改；`list-files` 输出相对文件路径，`read-file` 读取 UTF-8 文本，`search` 进行区分大小写的字面搜索，匹配结果格式为 `相对路径:行号:文本`。省略列文件或搜索的路径时从工作区根目录开始。

只接受工作区内的相对路径。绝对路径、盘符、UNC、`..`、Windows 文件名别名、设备名及 ADS 均被拒绝；`.git` 不开放读取或搜索。显式指定符号链接或重解析点（包括 Windows junction）会被拒绝；遍历时跳过它们并记录提示。默认最多输出 12,000 个字符、读取单文件 256 KiB、发现 2,000 个目录条目、搜索累计读取 4 MiB。这些限制由宿主配置控制，CLI 不提供覆盖参数。超出单文件限制的直接读取被拒绝；搜索跳过过大或非 UTF-8 文件并记录提示，达到输出、条目或累计读取限制时返回截断标记。

三个工具共用 `ToolRequest` 与 `ToolResult`。JSON 结果中的 `status` 为 `completed`、`rejected` 或 `error`，并包含 `output`、`truncated`、`notices` 和 `error`；正常或已截断结果进程退出码为 0，拒绝或错误为 2。只读工具适用于当前单主机、受信任仓库且文件操作期间工作区稳定的范围；并发替换目录或修改文件的对抗场景仍未提供完整防护。

## M8 修改、差异与固定测试工具

所有工具经 `WorkspaceTools.execute(ToolRequest)` 路由。使用 M5 的活动工作区 ID，下面的预设补丁修复缺失 Todo 返回 404 的行为：

```powershell
.\.venv\Scripts\python.exe -m agentforge.workspace_tools.cli apply-patch <id> examples/todo_fix.patch
.\.venv\Scripts\python.exe -m agentforge.workspace_tools.cli status <id>
.\.venv\Scripts\python.exe -m agentforge.workspace_tools.cli diff <id>
.\.venv\Scripts\python.exe -m agentforge.workspace_tools.cli run-tests <id>
```

`apply-patch` 接受 UTF-8 unified 文本补丁，精确匹配行号和原内容，支持修改、创建、删除常规文本文件。默认 `WritePolicy` 只允许 `todo_app/`；测试、依赖和文档文件受写入范围保护。策略由可信宿主配置，请求和 CLI 不能扩大。绝对/越界路径、Git 元数据、链接、junction 和硬链接目标均被拒绝。补丁最多 256 KiB、20 个文件，原文件及结果各最多 256 KiB；先校验全部文件，再用同目录临时文件替换，普通写入失败回滚并报告结果。重命名、二进制、权限变化和模糊匹配尚不支持。

`status` 查看当前候选状态，`diff` 相对 M5 固定提交报告已提交、已暂存、未暂存和未跟踪文本改动。Git 查询不修改暂存区，禁用外部 Diff/textconv/fsmonitor，限制为 15 秒和最多 12,000 个输出字符；查询及测试前检查候选文件树，拒绝链接、嵌套 Git 元数据和硬链接。过大或非文本的未跟踪文件记录跳过提示。文件操作仍要求工作区在操作期间稳定；进程崩溃恢复留待后续阶段。

`run-tests` 复用 M6 的固定镜像和 pytest 命令，不接收自定义命令、镜像、挂载或超时。JSON 的 `details` 包含运行 ID、镜像 ID、实际测试状态、退出码、耗时和完整日志位置；pytest 非零退出仍表示测试调用完成，CLI 保留真实退出码，超时为 124，基础设施错误为 2。补丁成功后，原有五项 Todo 测试应全部通过。它们是目标仓库测试，AgentForge 自身单元测试仍由项目根目录的 pytest 验证。

真实 M8 集成入口：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_workspace_mutation.py -q
```

2026-10-07 验收记录：AgentForge 单元测试 **212 passed**，Ruff 检查通过；Docker 恢复后运行全部 `tests/integration`，**4 passed，25.94 秒，无跳过**。这四项是 AgentForge 的集成测试；其中 M8 流程在容器内先复现 Todo 基线的 4 passed、1 failed 和退出码 1，再应用补丁得到 5 passed 和退出码 0。来源仓库与目标测试文件保持不变，验证用工作区和容器已清理。完整验收记录见 [M8 实施计划](docs/superpower/plans/2026-10-07-m8-mutation-tools.md)。

演示工作区的候选修改需要先审查。确认只用于演示时，可用 `git -C .local/workspaces/<id> restore -- todo_app/main.py` 恢复，再运行 M5 `remove <id>`；日志和 `removed` 生命周期记录会保留。预设补丁不修改 `examples/todo_fixture/` 或固定来源仓库。

## M9 基线与独立验收器（已完成）

先生成 M4 来源仓库、构建 M6 镜像，再创建新的 M5 工作区。必须在修改候选前运行 `baseline`，随后应用补丁并验收；`<id>` 使用 `create` 返回的工作区 ID：

```powershell
.\.venv\Scripts\python.exe -m agentforge.workspace_management.cli create
.\.venv\Scripts\python.exe -m agentforge.acceptance.cli baseline <id>
.\.venv\Scripts\python.exe -m agentforge.workspace_tools.cli apply-patch <id> examples/todo_fix.patch
.\.venv\Scripts\python.exe -m agentforge.acceptance.cli verify <id>
.\.venv\Scripts\python.exe -m agentforge.acceptance.cli show <id>
```

`baseline` 要求 HEAD 等于 M4 固定提交，且所有候选文件与该提交的原始 Git blob 完全一致。固定套件只执行 `tests/test_todos.py` 的五项检查：`test_get_missing_todo_returns_404` 是验收，`test_post_creates_todo`、`test_get_existing_todo`、`test_new_app_starts_empty`、`test_non_integer_id_is_rejected` 是四项回归。M4 预置失败可以成为有效基线；报告的 `recorded` 只表示已记录完整证据，不表示目标测试全部通过。失败或拒绝的基线尝试保留报告，并保留上一份有效基线引用。

`snapshot.py` 从固定提交读取权威文件，在活动候选全树中读取常规文件，包括未跟踪与忽略文件，排除 `.git`；路径及文件字节共同计算 SHA256，HEAD 另行记录。只有 `todo_app/` 可以变化，其他文件，包括测试、依赖和配置，必须与固定提交逐字节相同；链接、重解析点、硬链接、特殊文件和资源超限均拒绝。被检查的字节写入临时快照，容器只读挂载该快照。`verify` 复用有效基线的完整镜像 ID 和固定检查，CLI 不开放命令、测试名单、镜像或权限覆盖。

`checks.py` 复用 M6 的容器权限、资源、网络和清理策略，以 `python -I` 启动镜像内 pytest，禁用候选 conftest、自动插件和配置发现。JUnit XML 在容器结束前通过 stdout 的 Base64 标记传回宿主，宿主从完整日志中有界提取并保存 XML；精确校验五项测试身份、所属模块、统计与退出码。缺失、重复、跳过、异常、证据损坏或执行故障均不能得到 `passed`。

| 报告状态 | 含义 | CLI 退出码 |
|---|---|---|
| `recorded` | 修改前基线证据完整，可供比较 | 0 |
| `passed` | 候选五项检查全部通过 | 0 |
| `existing_failure` | 仍有基线中已存在的失败，没有新增失败 | 1 |
| `new_failure` | 至少一项基线通过的检查在候选上失败 | 1 |
| `environment_error` | Docker、镜像、快照准备、执行或结构化证据故障 | 2 |
| `rejected` | 缺少有效基线、修改权威文件或违反候选边界 | 2 |
| `stale` | 当前候选或规则与被测报告不再一致，结果失效 | 2 |

`service.py` 比较每项检查，分别记录 `existing_failures`、`new_failures` 与 `fixed_failures`。运行后重新检查实际候选的 HEAD/摘要，发生变化则标记 `stale`；`show` 跨进程加载最新报告，再检查当前候选，返回 `recorded_state` 和 `valid_for_current_candidate`，原先通过的报告也会因修改失效。

JSON 报告位于 `.local/workspaces/.acceptance/<id>/<report-id>.json`，`baseline.json` 指向有效基线，`latest.json` 指向最新尝试；完整日志与提取的 XML 位于 `.local/workspaces/.runs/<run-id>.log`、`<run-id>.xml`。报告包含固定提交、规则摘要、候选 HEAD/内容摘要、基线/运行 ID、宿主及容器环境、实际退出码、耗时和证据路径。它们都位于候选工作区与固定来源仓库之外；本地 JSON 是验收证据，Job 数据库及 M10 综合 Diff/报告仍待实现。

M9 的真实 Docker 验收入口为 `.\.venv\Scripts\python.exe -m pytest tests/integration/test_acceptance.py -q`。2026-10-07 本轮全部 AgentForge `tests/integration` 得到 **5 passed，258.42 秒，无跳过**。默认 CLI 演示依次验证有效基线 `recorded`（CLI 退出 0、Todo pytest 退出 1）、未修复候选 `existing_failure`（退出 1）、预设补丁后 `passed`（CLI 与 Todo pytest 均退出 0），再验证查询过期 `stale`（退出 2）、新增 `test_post_creates_todo` 回归 `new_failure`（退出 1）与修改权威测试 `rejected`（退出 2）。演示最后恢复候选并记录为 `removed`，固定来源保持不变；完整结果见 [M9 CLI 验收记录](.local/workspaces/.runs/m9-cli-acceptance-20261007.json)。当前 M9 已完成；全量单元测试 **332 passed**，Ruff 与 Diff 格式检查通过。
