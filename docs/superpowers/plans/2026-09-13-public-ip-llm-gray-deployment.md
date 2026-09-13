# 公网 IP 真实 LLM 受限灰度部署实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 ICP 备案期间，将当前 MVP 以“公网 IP + 受限访问 + 低额度真实 LLM”的方式部署到已有 Alibaba Cloud Linux 3 ECS；备案完成后再切换正式域名和 HTTPS。

**Architecture:** 保持宿主机 Nginx → `127.0.0.1:8000` → FastAPI container → `arena_private` Docker network → PostgreSQL container 拓扑。真实 LLM 只由后端 Provider 调用，API Key 仅注入后端运行环境；灰度阶段使用 ECS 安全组/IP 白名单和 Nginx 限流。

**Tech Stack:** Python 3.12、FastAPI、httpx、SQLAlchemy async、PostgreSQL 16.4、Docker Compose、Nginx、Alibaba Cloud ECS、OpenAI Compatible API、pytest、Vitest、Vite。

**Spec:** `docs/开发日志/2026-09-13.md`、`README.md`、`docs/部署方案-Nginx与Docker.md`、`docs/MVP开发构想.md`

## Global Constraints

- 灰度阶段是受限环境，不是匿名公开服务。
- `LLM_PROVIDER=openai_compatible` 只在 ECS 后端运行环境启用；公开样例和本地默认值继续使用 `mock`。
- 生产 API Key 使用专用 Key，设置模型范围、每日/月度硬限额和告警；真实 Key 不进入 Git、前端、镜像或日志。
- `DEBUG=false`；`CORS_ORIGINS` 不使用 `*`；PostgreSQL 和 FastAPI 不直接暴露公网。
- ECS 只开放必要端口；优先通过安全组限制到操作者当前公网 IP，并在 Nginx 侧保留限流。
- 不自动执行生产数据库 migration、seed、restore、删除或覆盖；这些动作须针对目标 ECS/数据库单独批准。
- 不将 HTTP Basic Auth 作为纯 HTTP 灰度的默认保护方式。
- 先确认生产容器代理环境；不需要代理时清除 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 等变量。
- 验证失败时停止发布，保留旧镜像、旧前端版本和数据库备份以支持回滚。

## 变更范围

- `/home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/backend/requirements.txt`：仅在生产确实需要 SOCKS 代理时加入 `socksio`。
- `/home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/deploy/nginx/multi-agent-arena.conf`：备案完成后使用正式域名 HTTPS 模板；灰度期单独使用公网 IP 站点配置。
- `/home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/.env.deploy.example`、`README.md`、`docs/部署方案-Nginx与Docker.md`：补充灰度前置条件、代理判断、限流、访问控制和验收步骤。
- `/home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/backend/tests/`、`frontend/src/`：运行与改动直接相关的测试和构建。
- ECS-only：`/opt/multi-agent-arena/app/.env.deploy`、实际 Nginx 配置、安全组、Compose 启停、数据库备份/migration/seed、真实 Provider 请求和回滚。

---

### Task 1: 建立发布基线

**Files:** 读取 README、2026-09-13 开发日志、部署方案、`compose.yaml`、Dockerfile、依赖、Nginx 模板和相关测试。

**Interfaces:** 消费当前 Provider/配置/测试改动；产出可追踪的测试基线、Git commit、后端镜像 tag 和前端 release。

- [x] 检查工作区：

```bash
cd /home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena
git status --short
git diff --check
git diff --stat
```

确认没有意外 `.env`、数据库文件、缓存或密钥。

执行结果：`git diff --check` 通过；发现被忽略的本地运行时文件 `backend/.env`，其中存在形似 API Key 的值，未读取、未输出、未纳入发布；该值不得复用到生产，若对应真实凭据应在 Provider 平台轮换或撤销。

- [x] 运行本地验证：

```bash
cd /home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena
.venv/bin/python -m pytest -q backend
.venv/bin/python -m compileall -q backend/app backend/alembic backend/tests
cd frontend
npm test -- --run
npm run build
```

预期后端 `38 passed, 1 skipped`（或当前代码对应结果）、前端测试和构建均通过。

执行结果：后端 `38 passed, 1 skipped`；Python `compileall` 通过；前端 `8 passed`；Vite 生产构建通过。

- [x] 记录部署基线信息。

执行结果：当前 HEAD 为 `eaf0af4148dfd1d373e4045c354558d34b72c801`，建议后端镜像短标签为 `eaf0af4`，前端构建目录为 `frontend/dist`。由于工作区仍有未提交改动，该 HEAD 不能作为包含本次 LLM Provider 改动的最终发布版本。

- [ ] Git 提交/推送必须单独批准后执行：

```bash
git add README.md .env.deploy.example backend deploy docs
git commit -m "feat: prepare restricted production LLM deployment"
git push origin main
```

### Task 2: 统一生产代理依赖

**Files:** 检查 `backend/app/providers/openai_compatible.py`、`backend/requirements.txt`。

**Interfaces:** 保持 `OpenAICompatibleProvider.complete(prompt: str) -> str` 不变；产出与 ECS 网络环境一致的生产镜像。

- [ ] ECS 只读检查：

```bash
cd /opt/multi-agent-arena/app
docker compose exec backend sh -c 'env | grep -E "^(HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY|http_proxy|https_proxy|all_proxy|no_proxy)=" || true'
```

- [ ] 默认清除不需要的代理变量并直连 HTTPS。只有网络明确要求 SOCKS 代理时，才在依赖中增加 `socksio==1.0.0`，随后运行 Provider 测试、构建镜像并验证容器内 `import socksio`。

- [ ] 验证 Compose 和镜像：

```bash
docker compose config
docker compose build backend
```

### Task 3: 准备公网 IP 灰度入口

**Files:** 读取/必要时修改 `/home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/deploy/nginx/multi-agent-arena.conf`；ECS 实际 Nginx 配置为运行时文件。

**Interfaces:** 消费 `127.0.0.1:8000` 后端；产出来源限制和 `/api/solutions` IP 限流。

- [ ] 在阿里云安全组将 HTTP 灰度入口限制为操作者当前公网 IPv4 `/32`，保留可恢复 SSH 规则；禁止开放 5432 和 8000。

- [ ] 公网 IP 灰度站点使用 `server_name _`，不要启用尚无证书的正式 HTTPS 模板。将 `limit_req_zone $binary_remote_addr zone=solution_by_ip:10m rate=2r/min;` 放在 Nginx `http {}` 上下文，并在 `/api/solutions` 使用 `limit_req zone=solution_by_ip burst=2 nodelay;`、`limit_req_status 429` 和 `proxy_read_timeout 120s`。

- [ ] 检查并 reload：

```bash
sudo nginx -t
sudo systemctl reload nginx
curl -i http://127.0.0.1/health
```

- [ ] 从允许来源连续发起超过限额的解题请求，确认出现 HTTP 429，且不会全部到达 LLM Provider。

### Task 4: 安全注入生产配置

**Files:** 读取 `.env.deploy.example`、`compose.yaml`；运行时写入 ECS `/opt/multi-agent-arena/app/.env.deploy`。

**Interfaces:** 消费 Compose `.env.deploy`、Settings 和 `get_agent()`；产出只存在于 ECS 的真实 Provider 配置。

- [ ] 创建专用低额度 API Key，限制模型、每日/月度硬额度并开启告警；不要复用可能暴露过的本地 Key。

- [ ] 在 ECS 写入运行时配置，真实值不得进入命令历史：

```env
DEBUG=false
LLM_PROVIDER=openai_compatible
LLM_API_KEY=<dedicated-production-key>
LLM_BASE_URL=https://<provider-base-url>/v1
LLM_MODEL=<provider-model>
LLM_TIMEOUT_SECONDS=30
LLM_MAX_TOKENS=<provider-allowed-limit>
```

同时保证 `DATABASE_URL` 与 `POSTGRES_PASSWORD` 一致，`CORS_ORIGINS` 为实际灰度来源且不为 `*`。

- [ ] 设置 `chmod 600 /opt/multi-agent-arena/app/.env.deploy`，只检查非敏感字段，不打印 API Key、数据库密码或完整连接串。

### Task 5: 备份、启动和数据库初始化

**Files:** 读取 Alembic versions 和 `backend/app/seed.py`；运行时使用 ECS Docker volume 与 `/opt/multi-agent-arena/backups/`。

**Interfaces:** 消费 PostgreSQL healthcheck、Alembic head 和幂等 seed；产出 healthy 服务、备份和题库。

- [ ] 只读检查 Compose，确认 backend 仍绑定 `127.0.0.1:8000:8000`、PostgreSQL 无 `ports` 映射。

- [ ] 针对目标数据库明确批准后备份：

```bash
mkdir -p /opt/multi-agent-arena/backups
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  | gzip > /opt/multi-agent-arena/backups/multi-agent-arena-$(date +%F-%H%M%S).sql.gz
chmod 600 /opt/multi-agent-arena/backups/*.sql.gz
```

确认备份非空并复制到异地受保护存储；失败则停止后续数据库操作。

- [ ] 针对目标 ECS 明确批准后启动/重建：

```bash
docker compose up -d postgres
docker compose up -d --build backend
docker compose ps
docker compose logs --tail=100 backend postgres
```

- [ ] 针对目标数据库明确批准后执行：

```bash
docker compose run --rm backend python -m alembic upgrade head
docker compose run --rm backend python -m app.seed
```

预期 Alembic 到 head；首次 seed 2 道题，重复执行保持幂等。

### Task 6: 真实 LLM 灰度验收

**Files:** 读取前端 API、前端环境样例、Solutions API 和 Provider 实现。

**Interfaces:** 消费 healthy Compose、受限 Nginx 和真实 Provider；产出端到端请求、错误脱敏、限流和费用观察结果。

- [ ] 验证基础链路：

```bash
curl -i http://<ecs-public-ip>/health
curl -i http://<ecs-public-ip>/api/problems
```

确认返回 200，且 `:8000`、`:5432` 无公网直连。

- [ ] 只发起一次受控真实 `POST /api/solutions`，记录状态、耗时和结果结构；不记录 Prompt、Authorization、Key 或完整上游响应。

- [ ] 用不泄露真实 Key 的可控无效模型/配置验证通用错误和日志脱敏，之后恢复正式模型。

- [ ] 观察 Nginx/backend 日志、CPU、内存、Provider 429/5xx/超时、Key 调用量和费用；异常时切回 `mock` 或停止 backend。

### Task 7: 回滚和备案后的 HTTPS 切换

**Files:** `/home/abeltomato/workspace/projects/Multi-Agent-Algorithmic-Arena/deploy/nginx/multi-agent-arena.conf`、README 和部署方案文档。

**Interfaces:** 消费灰度版本、旧镜像、前端 release 和备案结果；产出可执行回滚和正式 HTTPS 入口。

- [ ] 记录旧 backend 镜像、旧前端 release、migration 版本和最近备份；应用回滚不自动执行数据库 downgrade。

- [ ] Provider 或费用异常时，先将 ECS `LLM_PROVIDER` 改回 `mock` 并重启 backend；必要时恢复旧镜像/前端链接，保留日志和备份。

- [ ] 备案完成且 DNS 生效后，配置正式域名并执行：

```bash
sudo certbot --nginx -d <正式域名>
sudo nginx -t
sudo systemctl reload nginx
sudo certbot renew --dry-run
```

- [ ] 验收 HTTP 跳转 HTTPS、正式域名下 `/health`、`/api/problems` 和受控真实 LLM 请求；将 `CORS_ORIGINS` 更新为 HTTPS Origin。

## 高危操作审批门

以下动作必须在执行前针对具体目标单独批准：Git 提交/推送；修改 ECS 安全组、防火墙或 Nginx 公网入口；写入 API Key/数据库密码；启停或重建生产容器；数据库备份、migration、seed、restore；申请/安装 TLS 证书；启用真实 Provider 对外访问。

## 完成标准

- 本地后端测试、编译、前端测试和构建通过。
- ECS 使用明确版本，PostgreSQL/backend healthy。
- 5432/8000 无公网直连；灰度入口有来源限制，解题接口可返回 429。
- 专用 API Key 已设置限额和告警，未出现在代码、镜像、日志或前端。
- 真实 LLM 请求成功，输出符合 MVP Markdown 规范，错误不会泄露密钥或上游响应。
- 已记录回滚点并完成备份；migration/seed 有目标数据库审批。
- 备案完成后，正式域名 HTTPS、自动续期和 CORS 验收通过。