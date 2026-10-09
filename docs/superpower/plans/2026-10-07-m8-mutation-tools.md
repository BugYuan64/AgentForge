# M8 修改与测试工具实施计划

设计见 `docs/superpower/specs/2026-10-07-m8-mutation-tools-design.md`。直接在原项目目录实施，保留 M7 尚未提交的成果。

- [x] 写补丁与范围保护测试，确认缺失功能的红灯。
- [x] 扩展请求/结果契约，提取共享路径保护，实现严格文本补丁与失败回滚。
- [x] 实现有界状态、固定基线 Diff 和 M6 测试适配。
- [x] 扩展 JSON CLI，验证修改、查询和测试退出状态。
- [x] 审查代码并运行全量单元测试和 Ruff。
- [x] 默认 CLI 应用预设补丁、查询状态和 Diff，验证 Docker 不可用的错误结果并清理。
- [x] 完成真实固定补丁到容器测试演示并清理。
- [x] 同步原有根文档，记录实际验收和待完成事项。
- [x] 容器验收通过后标记 M8 完成与 M9 下一步。

## 当前验收记录（2026-10-07）

- 最终 `python -m pytest -ra`：**212 passed**，207.47 秒，无跳过。补丁范围、全文件先校验、创建/删除、失败回滚及回滚不完整报告、硬链接与 Windows junction、Git 状态/固定基线 Diff、输出限制、M6 结果适配和 CLI 退出码均覆盖。
- `ruff check src tests scripts examples/todo_fixture`：通过；`git diff --check`：通过。
- 新增 `examples/todo_fix.patch` 和 `tests/integration/test_workspace_mutation.py`，保留原 Todo 模板和固定来源仓库的预置缺陷；集成流程先验证原有 4 passed/1 failed，再应用补丁并要求 5 passed、来源不变和工作区清理。
- `.gitattributes` 为预设补丁禁用 Git 换行转换，保证 hunk 内容与固定基线精确匹配；未跟踪文本 Diff 按 Git 的 LF 行边界处理，并保留 BOM、Unicode 分隔字符和末尾无换行标记。
- 实际默认 CLI 演示工作区为 `5a4f2a56eb744a8387b410ab749a3bcb`：预设补丁、状态和 Diff 均退出 0；来源提交、文件和状态保持不变；演示修改恢复后由 M5 清理，记录为 `removed`。运行根目录只留下 `.records/` 和 `.runs/`。完整命令结果存于 `.local/workspaces/.runs/m8-cli-acceptance-20261007.json`。
- 真实 CLI 基线与候选测试均诚实返回 `infrastructure_error`、进程退出 2，日志分别为 `.local/workspaces/.runs/8a11d4392f0448299822ca2d4e8e92a9.log` 与 `6a14614693624b2cb1ba3c217b4fb732.log`；未声称它们通过。
- 首次真实 Docker 集成执行为 **1 skipped**：Docker Desktop 因过期运行时 socket 启动失败，Linux 引擎管道不存在；保留这个历史结果，没有将跳过当成验收通过。
- 先前通过正常停止/启动尝试恢复环境，并保留旧 `Docker/run` 为同目录的 `run.m8-backup-20261007`。强制终止 Docker 进程并移动运行目录的后续操作曾被自动审批拒绝，未执行。用户随后手动启动 Docker，当前真实验收已通过，无需该修复操作。
- 原有 `README.md`、`最终目标.md`、`阶段目标.md` 已同步实际接口和完成状态。M0–M8 与阶段 2 已完成，下一步 M9 尚未开始。开发改动在原项目目录，未建立开发分支或提交。

## Docker 恢复后的最终验收（2026-10-07）

- Docker Engine **29.6.1**，已有镜像 `agentforge-todo-test:m6` 可用，未重新构建镜像；本次固定镜像 ID 为 `sha256:a13ab392aa82d4330c3fe51a030c21b7c669cb1c178b712dd0beed74adde83a4`。
- `python -m pytest tests/integration -ra`：**4 passed**，25.94 秒，无跳过。覆盖 M6 真实基线失败、非 root/只读挂载/密钥隔离、超时容器清理，以及 M8 预设补丁、Diff、测试通过和来源/测试文件不变。
- 默认 CLI 创建工作区 `088914ad24a94e95b313c05f028edfcd`，基线 `run-tests` 得到 **4 passed、1 failed**，测试与进程退出码均为 **1**，工具调用状态为 `completed`，耗时 **2.266 秒**；应用 `examples/todo_fix.patch`、`status` 与 `diff` 均退出 **0**；候选 `run-tests` 得到 **5 passed**，测试与进程退出码均为 **0**，耗时 **2.141 秒**。两次使用相同镜像；基线失败仍是预置的 404 缺陷。
- 完整默认 CLI 结果保存于 `.local/workspaces/.runs/m8-cli-acceptance-20261007-docker.json`；基线日志为 `b01bae6700884677b8206db9bb6ba684.log`，候选日志为 `b0892c398b47444d90ec68ff7b19917e.log`，均位于 `.local/workspaces/.runs/`。此前基础设施错误的证据仍保留。
- 来源提交、状态、应用文件和测试文件保持不变，候选测试文件未修改；恢复演示补丁后通过 M5 清理，生命周期为 `removed`。来源 Git 仅剩其主工作树，运行根目录仅剩 `.records/` 与 `.runs/`；Docker 中无遗留 `agentforge-m6-` 测试容器。
- 本次 Ruff 检查再次通过。上述 **4 passed** 是 AgentForge 的集成测试数量；**5 passed** 是容器内 Todo 目标仓库的测试数量。M8 不包含 M9 的独立验收器、失败分类或候选版本绑定报告。
