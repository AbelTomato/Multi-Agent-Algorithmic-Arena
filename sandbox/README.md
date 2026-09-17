# Arena Sandbox 执行控制器

本目录包含本地受控验证用的 Go 执行控制器。它仅绑定 loopback，并通过固定 Docker CLI 参数运行一次性 Python 3.11 候选程序。普通 Docker/WSL2 共享宿主机内核，不构成强安全沙箱，也不得暴露到公网。

## 当前状态

- Go 单元测试、`go vet` 已通过。
- Docker Desktop 29.8.0（cgroup v2）下的真实 Docker 验收已于 2026-09-17 通过；未拉取镜像，测试结束后无 Arena 标签容器残留。
- 已取得本地 Docker 对生命周期、资源限制、网络/文件边界、OOM 证据、取消、并发和自有资源清理的证据；该结论不等同强安全、Judge 集成、ECS 或公网准入。
- 旧 Python/FastAPI 原型保留为历史契约参考，不是正式执行入口。

## 构建与启动

本项目使用项目内、经 SHA-256 校验的 Go 1.24.0 工具链：

```bash
cd /home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/sandbox
GO=/home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/.tools/go-1.24.0/bin/go

"$GO" test ./...
"$GO" vet ./...
"$GO" run ./cmd/controller
```

控制器固定监听 `127.0.0.1:8001`。启动控制器本身不会创建容器；只有收到有效的 `POST /execute` 请求才会调用 Docker CLI。

真实 Docker 测试会创建并删除带固定 Arena 标签的临时容器，必须先获得对此操作的单独授权，并确认 Docker CLI、daemon 和固定镜像均可用。

已授权时的真实验收命令：

```bash
cd /home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/sandbox
GO=/home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/.tools/go-1.24.0/bin/go
ARENA_SANDBOX_INTEGRATION=1 "$GO" test ./tests/integration -v -count=1
```

## HTTP 契约

### `GET /health`

成功返回：

```json
{"status":"ok","service":"sandbox"}
```

### `POST /execute`

请求只能包含以下字段；JSON 解码禁止未知字段，原始请求体有上限。

```json
{
  "code": "完整可执行 Python 程序",
  "stdin_input": "{\"s\":\"()\"}",
  "protocol_version": "json-stdio-v1"
}
```

- `code` 不得为空白，按 UTF-8 字节计算最大 64 KiB。
- `stdin_input` 按 UTF-8 字节计算最大 64 KiB。
- `protocol_version` 必须严格为 `json-stdio-v1`。
- 调用方不能传入 `task_id`、镜像、挂载、命令或资源限制；任务 ID 仅由控制器通过加密随机数生成。
- 单槽准入：槽被占用时立即返回 `409`，不排队；服务关闭时拒绝新请求并返回 `503`。

执行响应包含 `exit_reason`、可选 `exit_code`、有界 `stdout`/`stderr`、`wall_time_ms` 和 `oom_killed`。其结果仅描述执行状态，不包含 AC/WA 判题结果。

## 固定 Docker 边界

控制器只生成固定 Docker 参数：

- 固定镜像：`python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534`
- `--network none`、`--read-only`、`--tmpfs /tmp:size=64m,noexec`
- 非 root 用户 `65534:65534`、`--cap-drop ALL`、`no-new-privileges`
- `--cpus 1`、`--memory 128m`、`--memory-swap 128m`、`--pids-limit 32`
- 5 秒单用例墙钟限制，stdout/stderr 共享 64 KiB 预算；只有超过预算才为 OLE。

每个任务带有 `io.arena.sandbox.owner=true` 和服务端任务 ID 标签。清理前先读取 OOM 状态，再校验两项所有权标签；标签不匹配或 inspect 失败时不会停止或删除资源。仅可靠 Docker OOM 证据可产生 `memory_limit_exceeded`；退出码 137 本身仍是 `non_zero_exit`。

## 已知限制

- 真实验收只在本次 Docker Desktop/WSL2、本地 daemon 和固定镜像摘要下取得；环境、Docker 版本或运行时改变后必须重新验收。
- Docker 控制器拥有访问 Docker daemon 的高权限，必须保持 loopback 边界，任务容器不得获得 Docker Socket、数据库凭据或工作区挂载。
- 控制器不会返回 Docker 原始错误、宿主机路径或运行参数诊断；Judge/API 层还需完成错误语义映射和隐藏用例保护验收。
