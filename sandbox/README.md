# Arena Sandbox 执行控制器

本目录包含本地受控验证用的 Go 执行控制器。它仅绑定 loopback，通过受信任 Runtime Registry 运行 Python 3.11 解释型程序或 C++ GCC 14/C++20 编译产物。普通 Docker/WSL2 共享宿主机内核，不构成强安全沙箱，也不得暴露到公网。

## 当前状态

- Go 单元测试、`go vet` 已通过。
- Docker Desktop 29.8.0（cgroup v2）下的真实 Docker 验收已于 2026-09-17 通过；未拉取镜像，测试结束后无 Arena 标签容器残留。
- 已取得本地 Docker 对生命周期、资源限制、网络/文件边界、OOM 证据、取消、并发和自有资源清理的证据；该结论不等同强安全、Judge 集成、ECS 或公网准入。
- 阶段 4 的启动恢复逻辑已由 fake Docker 单元测试和真实 Docker 遗留任务恢复测试覆盖；Docker daemon 短暂不可用与清理失败仅有隔离单元测试证据，尚未在共享 daemon 上主动制造故障。
- 旧 Python/FastAPI 控制器及其专属测试已于 2026-09-20 移除；Go 是唯一正式执行控制器。
- `cpp-gcc-14-cpp20-v1` 已在 Docker Desktop 29.8.0、Linux/amd64 真实验证：合法 C++20 程序、编译错误和运行超时均按阶段结果返回，且测试结束后无 Arena 标签容器或产物 volume 残留。Python 后端 Client 仍固定 Python runtime；C++ 的提交/语言选择接入须等待阶段 D Spec。

## 构建与启动

本项目使用项目内、经 SHA-256 校验的 Go 1.24.0 工具链：

```bash
cd /home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/sandbox
GO=/home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/.tools/go-1.24.0/bin/go

"$GO" test ./...
"$GO" vet ./...
"$GO" run ./cmd/controller
```

控制器默认监听 `127.0.0.1:8001`。启动控制器本身不会创建容器；只有收到有效的 `POST /execute` 请求才会调用 Docker CLI。

受控的同机 ECS 灰度可设置 `ARENA_SANDBOX_LISTEN_ADDR=172.30.0.1:8001`，使仅连接 Docker internal bridge 的 backend 访问控制器。该变量只接受 loopback 或 RFC1918 私有 IPv4，端口必须为 `8001`；`0.0.0.0`、公网地址、主机名和其他端口都会在 Docker 初始化前被拒绝。不得将 `8001` 加入安全组、防火墙或 Nginx 公网入口。

启动前，控制器会以 `io.arena.sandbox.owner=true` 过滤列出可能遗留的容器，再逐个读取容器 ID、名称、owner 标签和 task-id 标签。只有容器名称与 `arena-task-*` task-id 精确一致且两项标签都正确时，才会停止并删除它；标签不匹配的候选不会被操作。清理过程中 Docker 返回“资源不存在”按幂等成功处理；列举、inspect、stop 或 remove 的其他错误会阻止控制器启动，避免在遗留任务未处置时接受新请求。

真实 Docker 测试会创建并删除带固定 Arena 标签的临时容器，必须先获得对此操作的单独授权，并确认 Docker CLI、daemon 和固定镜像均可用。

已授权时的真实验收命令：

```bash
cd /home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/sandbox
GO=/home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/.tools/go-1.24.0/bin/go
ARENA_SANDBOX_INTEGRATION=1 "$GO" test ./tests/integration -v -count=1
```

已授权时，可仅执行真实控制器进程重启恢复验收：

```bash
cd /home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/sandbox
GO=/home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/.tools/go-1.24.0/bin/go
ARENA_SANDBOX_INTEGRATION=1 "$GO" test ./tests/integration -run '^TestControllerProcessRestartRecoversActiveTask$' -v -count=1
```

该测试构建本地控制器二进制，在 loopback 地址启动第一个控制器，提交一个 `sleep(30)` 执行以创建唯一的受限 Arena 任务，终止该测试启动的第一个控制器进程，再启动替代控制器并验证启动恢复删除该任务。测试只会强制删除名称、owner 标签和 task-id 标签均精确匹配的 Arena 测试容器；必须先取得单独授权。

## HTTP 契约

### `GET /health`

成功返回：

```json
{"status":"ok","service":"sandbox"}
```

### `POST /execute`

请求只能包含以下字段；JSON 解码禁止未知字段，原始请求体有上限。旧 `code`、`protocol_version` 请求不再兼容。

```json
{
  "api_version": "execution-api-v2",
  "runtime_id": "python-3.11-v1 或 cpp-gcc-14-cpp20-v1",
  "source": "完整可执行的受支持语言程序",
  "stdin_input": "{\"s\":\"()\"}",
  "io_protocol": "json-stdio-v1"
}
```

- `api_version` 必须严格为 `execution-api-v2`。
- `runtime_id` 必须存在于受信任 Registry；当前注册 `python-3.11-v1` 与 `cpp-gcc-14-cpp20-v1`。
- `source` 不得为空白，按 UTF-8 字节计算最大 64 KiB。
- `stdin_input` 按 UTF-8 字节计算最大 64 KiB。
- `io_protocol` 必须受对应 runtime 支持，当前严格为 `json-stdio-v1`。
- 调用方不能传入 task ID、镜像、挂载、命令或资源限制；这些配置由 Registry 提供，任务 ID 仅由控制器通过加密随机数生成。随机源不可用时请求失败关闭，不会降级为固定或可预测的 task ID，也不会调用 Docker。
- 单槽准入：槽被占用时立即返回 `409`，不排队；服务关闭时拒绝新请求并返回 `503`。

执行响应包含 `exit_reason`、可选 `exit_code`、有界 `stdout`/`stderr`、`wall_time_ms` 和 `oom_killed`。其结果仅描述执行状态，不包含 AC/WA 判题结果。

## 固定 Docker 边界

控制器只生成固定 Docker 参数：

- `python-3.11-v1` Registry 条目固定镜像：`m.daocloud.io/docker.io/library/python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534`。镜像来源可变，但必须以该精确 digest 和 `linux/amd64` 核验；当前 ECS 已从该来源拉取并核验。
- `cpp-gcc-14-cpp20-v1` Registry 条目固定镜像：`m.daocloud.io/docker.io/library/gcc@sha256:cb57ac6c7917425c057c736fe3a240df25bce310418d61cd223bc8e411364876`，仅含 GCC 14 自带 C++20 标准库，不预装 Boost、PBDS 或其他第三方库；本地已核验 `linux/amd64`。
- `--network none`、`--read-only`、`--tmpfs /tmp:size=64m,noexec`
- 非 root 用户 `65534:65534`、`--cap-drop ALL`、`no-new-privileges`
- `--cpus 1`、`--memory 128m`、`--memory-swap 128m`、`--pids-limit 32`
- 候选执行的单用例墙钟限制为 5 秒；超时后允许最多 1 秒用于同步 Docker inspect、标签校验、stop/remove 清理，因此控制器端到端返回上限为 6 秒。stdout/stderr 共享 64 KiB 预算；只有超过预算才为 OLE。

### C++ 编译与产物生命周期

- 编译命令固定为 `g++ -std=c++20 -O2 -pipe -o /arena/out/program /arena/out/main.cpp`；调用方不能覆盖参数、镜像、挂载或命令。
- 编译使用 15 秒墙钟、512 MiB memory/swap、1 CPU、32 PID 和 64 KiB 合并 stdout/stderr 预算；运行仍使用 5 秒、128 MiB memory/swap 和 64 KiB 输出预算。
- 每次执行创建一个带 Arena owner/task-id 双标签的临时 Docker volume。只读 root 文件系统的初始化容器仅额外授予 `CAP_CHOWN` 以将该 volume 交给 UID/GID `65534:65534`；非 root 编译容器写入源码和产物，运行容器只读挂载产物并只执行固定 `/arena/out/program`。
- 编译成功后必须确认产物存在且可执行；编译失败、超时或输出超限分别返回 `compilation_failed`、`compilation_timeout`、`compilation_output_limit_exceeded`，不会进入候选运行。清理前会核验 volume 的双标签；无法核验时拒绝删除。

每个任务带有 `io.arena.sandbox.owner=true` 和服务端任务 ID 标签。清理前先读取 OOM 状态，再校验两项所有权标签；标签不匹配或 inspect 失败时不会停止或删除资源。仅可靠 Docker OOM 证据可产生 `memory_limit_exceeded`；退出码 137 本身仍是 `non_zero_exit`。

## 阶段 4 安全矩阵与运行时评估

| 控制项 | 当前配置/证据 | 限制 |
| --- | --- | --- |
| 容器所有权与恢复 | fake Docker 单元测试、真实遗留任务恢复测试，以及真实控制器进程终止/替代进程启动恢复测试；双标签和 task-id/名称二次校验 | 未物理停止共享 Docker Desktop daemon 验收 |
| 任务 ID | 服务端加密随机 task ID；随机源失败时 fail-closed，不创建 Docker 任务；4,096 个 ID 有界样本均格式正确且无重复 | 有界样本不是概率性碰撞证明；128 位随机 ID 的碰撞概率在本地单槽模型下可忽略 |
| 网络 | 固定 `--network none`；真实容器对 `1.1.1.1:53` 的单次、1 秒连接尝试被阻断 | 不覆盖内核或 Docker daemon 漏洞 |
| 文件系统 | `--read-only`、64 MiB `tmpfs /tmp`、无工作区/凭据/Docker Socket 挂载；真实容器根目录写入失败、`/tmp` 写入成功且第 65 MiB 写入失败 | 镜像内容与 Docker daemon 仍属可信边界 |
| 进程与资源 | 1 CPU、128 MiB memory/swap、32 PID、5 秒候选执行墙钟、6 秒含同步清理的返回上限、64 KiB 双流输出预算；真实容器在最多 64 次 fork 尝试中受 PID 限制，256 MiB 分配取得 OOMKilled 证据 | 不是对宿主机 DoS 的完整防护，不能抵御内核漏洞 |
| 权限 | UID/GID `65534:65534`、`--cap-drop ALL`、`no-new-privileges`；真实容器断言非 root、`CapEff` 为零和 `NoNewPrivs: 1` | 普通 Docker/runc 仍与宿主机共享内核 |
| 控制器入口 | 默认 `127.0.0.1:8001`；受控同机 ECS 仅允许 Docker internal bridge 网关 `172.30.0.1:8001`，请求不接受镜像、挂载、命令、资源限制或 task ID | Docker daemon 权限仍然高；同机 ECS 会与业务进程和凭据共置，不是强隔离 |

未安装或引入新的隔离运行时。基于当前代码和已有本地证据的选型结论如下：

- **rootless Docker**：可降低 daemon/容器的宿主机权限暴露，但需要重新验证 cgroup 资源限制、网络行为、Docker Desktop/WSL2 兼容性和运维方式；未安装、未测试、未选定。
- **gVisor**：可通过用户态内核提高对容器逃逸的防护层级，但会引入运行时兼容性、性能和运维成本；未安装、未测试、未选定。
- **独立 VM/执行主机**：可把不可信执行与数据库、Provider 凭据及业务进程分离，是后续 ECS 准入前的优先隔离方向；尚未部署或验证。

因此当前实现只能用于本地受控试用，不能宣称强安全隔离、匿名公网执行安全、真实 Provider 验收或 ECS 准入。

## 已知限制

- 真实验收只在本次 Docker Desktop/WSL2、本地 daemon 和固定镜像摘要下取得；环境、Docker 版本或运行时改变后必须重新验收。
- Docker 控制器拥有访问 Docker daemon 的高权限，必须保持 loopback 边界，任务容器不得获得 Docker Socket、数据库凭据或工作区挂载。
- 控制器不会返回 Docker 原始错误、宿主机路径或运行参数诊断；Judge/API 层还需完成错误语义映射和隐藏用例保护验收。
- 当前 Python Judge Client 固定提交 `python-3.11-v1`；C++ 已是 Go 控制器受信任 runtime，但尚未通过后端 Submission、题目语言准入或 Checker 完成公开产品接入。
- 已在真实 Docker 中验证：经双标签和名称匹配的遗留 Arena 任务可被恢复逻辑停止并删除；第一个 loopback 控制器进程被终止后，替代控制器可在启动阶段恢复该进程遗留的活动任务；两项验收后均无 owner 标签容器残留。令独立控制器使用不存在的本地 Unix Docker socket 时，它会在监听前因恢复扫描失败而退出，验证 Docker CLI 不可达时的失败关闭。Docker Desktop 的受控停止/重启入口在本 Linux 会话中无法确认，故未物理停止共享 daemon；inspect/stop/remove 失败仍以隔离单元测试覆盖。
- 候选执行的 5 秒墙钟与端到端返回上限不同：超时后必须同步完成 Docker CLI inspect、标签校验、stop/remove 清理，控制器在 6 秒内返回。本机 Docker Desktop 下连续 3 次真实超时验收分别为约 `5.53s`、`5.53s` 和 `5.51s`，每轮后无 Arena 标签容器残留。任一后续真实验收超过 6 秒时不得继续放宽阈值，应改为对 inspect、stop、remove 分段计时并定位长尾来源。
