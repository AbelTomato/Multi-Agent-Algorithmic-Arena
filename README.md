# Multi-Agent-Algorithmic-Arena

## 项目简介

Multi-Agent-Algorithmic-Arena 当前是一个单 Agent 算法题解答 MVP：用户浏览 PostgreSQL 中的题目，选择题目后由后端调用 Agent 生成 Markdown 格式的解题结果，前端负责展示题目和结果。

当前 MVP 包含：

- 题目列表和题目详情；
- 同步 `POST /api/solutions` 解题接口；
- 服务端统一 Prompt、Agent 重试和受控错误返回；
- 默认 `MockAgent`，以及可选的 OpenAI Compatible Provider；
- React 前端、FastAPI 后端、PostgreSQL 数据库；
- Docker Compose、Nginx、ECS 公网 IP 灰度部署；
- ECS 监控、QQ 邮箱故障告警和 PostgreSQL 自动备份。

当前不包含代码执行、正确性评测、评分、比赛状态机、多 Agent 协作、Redis、WebSocket、流式输出、登录和历史记录。

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
```

启用真实 OpenAI Compatible Provider 时，必须显式设置 `LLM_PROVIDER=openai_compatible`、`LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL`。真实密钥不得提交到 Git、前端、日志或镜像。

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

生产配置默认仍为 `LLM_PROVIDER=mock`；只有经过审查的 ECS 运行环境才启用真实 Provider。PostgreSQL 仅加入 Compose 私有网络，backend 仅发布到宿主机 `127.0.0.1:8000`。

备份和监控的 ECS 配置分别参见：

- [`docs/实施计划/2026-09-14-自动备份方案.md`](./docs/实施计划/2026-09-14-自动备份方案.md)
- [`docs/实施计划/2026-09-14-监控与告警方案.md`](./docs/实施计划/2026-09-14-监控与告警方案.md)

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
- API 文档：http://localhost:8000/docs

### 本地前端

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

前端默认地址：http://localhost:5173。后端和前端同时启动后，可按“题目列表 → 题目详情 → 请求解题 → 查看 Markdown 结果”的流程验证 MVP。

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