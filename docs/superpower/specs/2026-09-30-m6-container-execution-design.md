# M6 固定测试容器执行设计

## 目的与边界

M6 在 M5 的有效 Git 工作区运行预设的 Todo pytest 命令，交付退出码、耗时与日志。目标代码只在 Docker 容器中执行。M6 不提供任意命令、文件工具、补丁、模型调用或基线结果判定；M4 固定基线的单项失败应如实返回退出码 1。

## 方案选择

采用 Python 标准库调用 Docker CLI，避免在 AgentForge 中加入 Docker SDK 运行时依赖。镜像由仓库内受控 Dockerfile 和 Todo 的 `requirements.lock` 预先构建；执行器只使用已在本机存在的镜像 ID，不在运行测试时拉取镜像或安装依赖。相较于把源码复制进镜像，只读挂载 M5 候选工作区可检验当前候选版本，同时不挂载来源仓库。

## 接口与数据流

`ContainerTestRunner(workspace_manager, image="agentforge-todo-test:m6", timeout_seconds=30)` 提供 `run(workspace_id) -> TestRunResult`。它先用 `WorkspaceManager.get(id)` 校验工作区记录、来源、固定提交和 Git 附着关系，仅接受 `active` 状态；候选代码已有改动仍可运行。执行器内部固定命令为 `python -m pytest -q -W error -p no:cacheprovider tests/test_todos.py`，调用者不能提供命令、参数或额外挂载。

执行顺序为：检查本地镜像 ID；以随机容器名 `docker create`；`docker start`；在总测试时限内 `docker wait`；收集 `docker logs`；最后 `docker rm -f`。等待超时时先强制停止容器，再收集已有日志并清理。每个 Docker CLI 控制调用也有独立超时。结果区分 `completed`、`timed_out` 与 `infrastructure_error`；`completed` 时保留真实测试退出码。结果包含工作区 ID、镜像 ID、耗时、日志路径和错误说明，日志存放在工作区根目录的 `.runs/` 中，不写入来源仓库或候选工作区。

## 容器约束

只将已校验的候选工作区以 `--mount type=bind,...,readonly` 挂载到 `/workspace`，不挂载 Todo 来源仓库、AgentForge 根目录、宿主密钥目录或 Docker socket。使用非 root UID/GID、只读根文件系统、仅供临时文件的 `/tmp` tmpfs、`--network none`、`--cap-drop ALL`、`no-new-privileges`，并限制为 1 CPU、512 MiB 内存与交换总量、64 个进程。容器只接收固定的 HOME、TMPDIR、PYTHONDONTWRITEBYTECODE 和 PYTEST_DISABLE_PLUGIN_AUTOLOAD 环境值；不复制宿主模型密钥。禁用 pytest 缓存，避免向只读工作区写入。

Docker 与只读挂载只面向首个单用户、单主机、受信任目标仓库；不宣称能够安全承载任意恶意租户代码。Docker Desktop 未运行、镜像缺失、挂载失败或清理失败时返回有日志的基础设施错误，不伪装成 pytest 失败。

## 验收

单元测试覆盖固定命令与容器约束、拒绝非活动工作区、测试失败仍保留退出码和日志、超时后强制停止并删除容器、Docker 不可用的诊断。真实 Docker 验收在 M4 固定基线上得到 4 项通过、1 项预置失败及退出码 1；再用临时候选代码检查工作区不可写、来源仓库状态不变和超时无遗留容器。若本机 Docker Engine 不可连接，保持 M6 为待完成并明确未验证项。
