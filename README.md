# Multi-Agent-Algorithmic-Arena

## 项目简介

Multi-Agent-Algorithmic-Arena 当前是一个单 Agent 算法题解答 MVP，并提供一个默认关闭的本地候选程序评测闭环：用户浏览 PostgreSQL 中的题目，可请求 Markdown 解法，或在显式启用本地评测后生成 Python 候选程序并获取 Judge 摘要。

当前 MVP 包含：

- 题目列表和题目详情；
- 同步 `POST /api/solutions` 解题接口；
- 默认关闭的 `POST /api/evaluations` 本地评测接口：固定 Python 3.11、版本化用例、可信 Judge 与 Go 执行控制器；
- 服务端统一 Prompt、Agent 重试和受控错误返回；
- 默认 `MockAgent`，以及可选的 OpenAI Compatible Provider；
- React 前端、FastAPI 后端、PostgreSQL 数据库；
- Docker Compose、Nginx、ECS 公网 IP 灰度部署；
- ECS 监控、QQ 邮箱故障告警和 PostgreSQL 自动备份。

当前不包含评分、比赛状态机、多 Agent 协作、Redis、WebSocket、流式输出、登录和历史记录。评测不支持真实 Provider 验收、ECS 部署或公网匿名代码执行。

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 前端 | React、TypeScript、Vite、Tailwind CSS、React Markdown、Vitest |
| 后端 | Python 3.11+、FastAPI、Pydantic Settings、SQLAlchemy Async、Alembic、pytest |
| Agent | MockAgent、OpenAI Compatible Provider、httpx |
| 数据库 | PostgreSQL 16.4 |
| 部署 | Docker、Docker Compose、Nginx、Alibaba Cloud Linux 3 ECS |
| 运维 | systemd timer、PostgreSQL gzip 逻辑备份、OSS 校验、QQ SMTP SSL 告警 |

## 配置

### 本地后端配置

复制 `backend/.env.example` 为 `backend/.env`，默认使用本地 PostgreSQL 和 MockAgent：

```env
APP_NAME="Multi-Agent Algorithmic Arena API"
DEBUG=true
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/multi_agent_arena"
AGENT_RETRY_COUNT=1
CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"
LLM_PROVIDER=mock
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=
LLM_TIMEOUT_SECONDS=30
LLM_MAX_TOKENS=4096
EVALUATION_ENABLED=false
EVALUATION_TOTAL_TIMEOUT_SECONDS=210
SANDBOX_CONTROLLER_URL=http://127.0.0.1:8001
SANDBOX_CONTROLLER_TIMEOUT_SECONDS=10
```

启用真实 OpenAI Compatible Provider 时，必须显式设置 `LLM_PROVIDER=openai_compatible`、`LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL`。真实密钥不得提交到 Git、前端、日志或镜像。

本地评测默认关闭。启用 `EVALUATION_ENABLED=true` 前，必须先启动 `/home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/sandbox` 中仅绑定 `127.0.0.1:8001` 的 Go 控制器，并明确授权其创建和删除带 Arena 标签的临时容器。控制器不可用时 API 会失败关闭，不会降级为宿主机执行。普通 Docker/WSL2 与宿主机共享内核，不是强安全沙箱，不得直接暴露公网。

### 前端配置

复制 `frontend/.env.example` 为 `frontend/.env.local`。本地开发保持为空，Vite 会将 `/api` 和 `/health` 代理到 `http://localhost:8000`：

```env
VITE_API_BASE_URL=
```

### ECS 配置

复制 `.env.deploy.example` 为根目录 `.env.deploy`，替换数据库密码和实际 Provider 配置，并限制文件权限：

```bash
cp .env.deploy.example .env.deploy
chmod 600 .env.deploy
```

生产配置默认仍为 `LLM_PROVIDER=mock` 且 `EVALUATION_ENABLED=false`；只有经过审查的 ECS 运行环境才启用真实 Provider。PostgreSQL 仅加入 Compose 私有网络，backend 仅发布到宿主机 `127.0.0.1:8000`。

同机 ECS 评测灰度使用宿主机 systemd 控制器和仅供 backend 使用的 `arena_sandbox` internal bridge；控制器只允许监听该 bridge 网关 `172.30.0.1:8001`，不得开放 TCP/8001。控制器经 Docker daemon 运行不可信候选代码，拥有高宿主机权限；当前部署决策已接受它与 backend、PostgreSQL 和 Provider 运行时凭据同机的风险，但这不是强隔离或匿名公网代码执行安全方案。评测关闭路径是：在受保护编辑器中设置 `EVALUATION_ENABLED=false`、执行 `docker compose up -d --no-deps backend`，再停止 `multi-agent-arena-sandbox-controller.service`；不执行数据库操作。

正式域名 `tomato-agent-arena.me` 使用宿主机 Nginx 终止 TLS，正式配置模板位于 [`deploy/nginx/multi-agent-arena.conf`](./deploy/nginx/multi-agent-arena.conf)。该模板要求 Let’s Encrypt 证书位于 `/etc/letsencrypt/live/tomato-agent-arena.me/`，仅允许 TLS 1.2/1.3，并将 HTTP 请求重定向到 HTTPS。ICP 备案已通过，首页底部展示备案号 [粤ICP备2026139779号-1](http://beian.miit.gov.cn)。

首次在 ECS 上申请证书前，必须先确认 DNS 的 A/AAAA 记录指向 ECS、TCP/80 和 TCP/443 已按安全组策略开放，并保留公网 IP 灰度配置作为回退。以下命令只应在已确认维护窗口后由 ECS 管理员执行，不在本地开发环境运行：

```bash
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot \
  -w /var/www/certbot \
  -d tomato-agent-arena.me \
  --deploy-hook "systemctl reload nginx"
sudo nginx -t
sudo systemctl reload nginx
sudo certbot renew --dry-run
```

证书签发并通过 `nginx -t` 后，再将 ECS `.env.deploy` 中的 `CORS_ORIGINS` 设置为 `https://tomato-agent-arena.me`，重启或重建 backend 前须保留旧镜像和运行时配置。正式验收至少包括：HTTP 返回 `301`、HTTPS 首页返回 `200`、HTTPS `/health` 和 `/api/problems` 返回 `200`、证书域名匹配、TLS 1.0/1.1 被拒绝，以及首页备案链接指向工信部备案系统。

备份和监控的 ECS 配置分别参见：

- [`docs/实施计划/2026-09-14-自动备份方案.md`](./docs/实施计划/2026-09-14-自动备份方案.md)
- [`docs/实施计划/2026-09-14-监控与告警方案.md`](./docs/实施计划/2026-09-14-监控与告警方案.md)
- [`docs/实施计划/2026-09-17-ECS同机评测准入计划.md`](./docs/实施计划/2026-09-17-ECS同机评测准入计划.md)

## 启动方法

### 本地后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m alembic upgrade head
python -m app.seed
python -m uvicorn app.main:app --reload
```

后端默认地址：

- API 根地址：http://localhost:8000/
- 健康检查：http://localhost:8000/health
- 题目列表：http://localhost:8000/api/problems
- 本地评测：http://localhost:8000/api/evaluations（默认关闭）
- API 文档：http://localhost:8000/docs

### 本地前端

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

前端默认地址：http://localhost:5173。后端和前端同时启动后，可按“题目列表 → 题目详情 → 请求解题 → 查看 Markdown 结果”的流程验证旧 MVP；显式启用本地评测后，可使用“评测 Agent 代码”查看当前版本用例摘要。

### Docker Compose

```bash
cp .env.deploy.example .env.deploy
chmod 600 .env.deploy
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
```

首次初始化数据库需要在确认目标数据库和备份边界后执行：

```bash
docker compose run --rm backend python -m alembic upgrade head
docker compose run --rm backend python -m app.seed
```

这两条命令会写入数据库结构或题目数据，不应直接用于未知或生产数据库。

### 测试

后端：

```bash
cd backend
python -m pytest -q
python -m compileall -q app alembic tests
```

本地评测的非 Docker 回归：

```bash
cd backend
LLM_PROVIDER=mock .venv/bin/python -m pytest -q tests/test_evaluations.py tests/test_agents.py tests/test_solutions.py
```

真实评测集成测试会创建和删除 Arena 标签临时容器，必须另行授权并启动 Go 控制器：

```bash
cd backend
ARENA_SANDBOX_INTEGRATION=1 LLM_PROVIDER=mock .venv/bin/python -m pytest -q tests/integration/test_evaluation_flow.py
```

前端：

```bash
cd frontend
npm test -- --run
npm run build
```

## 相关文档

- [`docs/MVP开发构想.md`](./docs/MVP开发构想.md)：MVP 范围和技术决策基线。
- [`docs/实施计划/README.md`](./docs/实施计划/README.md)：实施计划和运维方案索引。
- [`docs/开发日志/README.md`](./docs/开发日志/README.md)：按日期记录实际开发和部署结果。