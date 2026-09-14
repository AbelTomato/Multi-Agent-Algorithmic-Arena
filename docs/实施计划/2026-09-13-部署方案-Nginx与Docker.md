# 部署方案-Nginx与Docker

## 1. 部署目标与适用范围

明确当前部署的是：

- 单 Agent 算法题解答 MVP；
- 本地和公开样例默认使用 MockAgent；
- ECS 灰度环境已通过后端环境变量启用 OpenAI Compatible Provider，并完成一次受控真实请求验证；
- 不部署 Redis；
- 不部署 Judge0；
- 灰度环境尚未完成安全组来源限制、Nginx 限流、专用 Key 额度/告警和 HTTPS 收口，不应视为匿名公开或正式生产服务；
- 不包含 WebSocket、异步任务和多副本高可用。

明确该方案属于：

> 单 VPS 生产级部署学习环境，不是高可用生产架构。

---

## 2. 总体架构

文档会记录完整拓扑：

```text
Client
  │
  ▼
Nginx on VPS
  ├── /           → /srv/multi-agent-arena/frontend/current
  ├── /api/*      → 127.0.0.1:8000
  └── /health     → 127.0.0.1:8000

FastAPI container
  │ Docker network: arena_private
  ▼
PostgreSQL container
  │
  ▼
Docker named volume
```

重点说明：

- Nginx 是唯一公网入口；
- FastAPI 不直接暴露公网；
- PostgreSQL 不暴露公网；
- 前端与 API 使用同一域名；
- 同域部署后，生产环境可以将前端请求配置为相对路径；
- `CORS_ORIGINS` 仍然需要配置正式域名，不使用 `*`。

---

## 3. VPS 目录规划

建议目录：

```text
/opt/multi-agent-arena/
├── app/
│   ├── backend/
│   ├── frontend/
│   ├── compose.yaml
│   └── .env
├── releases/
│   ├── <git-sha-1>/
│   └── <git-sha-2>/
├── backups/
├── logs/
└── scripts/
```

Nginx 静态文件：

```text
/srv/multi-agent-arena/frontend/
├── current -> /opt/multi-agent-arena/releases/<version>/frontend/dist
└── releases/
```

设计目标：

- 发布使用版本目录；
- `current` 作为当前版本软链接；
- 回滚时只切换软链接；
- 不直接覆盖当前运行版本；
- 前端静态文件和后端镜像版本保持可追踪。

---

## 4. Docker 化后端

已落地文件：

```text
backend/Dockerfile
backend/.dockerignore
```

后端容器原则：

- 基于 Python 3.11 或 3.12 slim 镜像；
- 使用非 root 用户；
- 安装固定依赖；
- 工作目录为 `/app`；
- 监听 `0.0.0.0:8000`；
- 日志输出 stdout/stderr；
- 不在镜像构建阶段执行 migration；
- 不在镜像中包含 `.env`、SQLite 数据库、缓存和本地构建产物。

启动命令：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

已配置容器健康检查：

```text
GET /health
```

后续可增加数据库就绪检查：

```text
GET /ready
```

其中：

- `/health`：只检查 FastAPI 进程是否存活；
- `/ready`：检查数据库连接是否可用。

---

## 5. Docker 化 PostgreSQL

已在 `compose.yaml` 中配置 PostgreSQL；2026-09-10 已在 Alibaba Cloud Linux 3 ECS 上启动并验证健康。

数据库原则：

- 固定 PostgreSQL 镜像版本；
- 使用 Docker named volume；
- 仅连接私有 Docker 网络；
- 不绑定 `5432:5432` 到公网；
- 使用强随机密码；
- 不把密码写入 Git；
- 使用 PostgreSQL 官方 healthcheck；
- FastAPI 通过 Compose 服务名连接数据库。

容器内连接地址：

```env
DATABASE_URL=postgresql+asyncpg://arena_app:<password>@postgres:5432/multi_agent_arena
```

不能使用：

```env
DATABASE_URL=postgresql+asyncpg://...@localhost:5432/...
```

因为在 FastAPI 容器中，`localhost` 指向 FastAPI 容器本身，而不是 PostgreSQL 容器。

数据库卷示意：

```yaml
volumes:
  postgres_data:
```

需要明确：

> Docker volume 不是备份。VPS 磁盘损坏、误删 volume 或宿主机故障仍会导致数据丢失。

---

## 6. Docker Compose 编排

已落地样例：

```text
compose.yaml
.env.deploy.example
```

建议服务：

```text
postgres
backend
```

Nginx 不放入 Compose，继续运行在 VPS 宿主机，这样可以学习传统 Nginx 管理方式：

```text
systemctl status nginx
nginx -t
systemctl reload nginx
```

Compose 网络：

```text
arena_private
```

拓扑：

```text
Nginx
  │ 127.0.0.1:8000
  ▼
backend container
  │ arena_private
  ▼
postgres container
```

后端端口建议：

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

这样：

- Nginx 可以通过宿主机回环地址访问 FastAPI；
- 外部网络不能直接访问 `8000`；
- PostgreSQL 不需要暴露宿主机端口。

---

## 7. 前端构建与 Nginx 静态托管

当前前端为 Vite 项目，生产构建命令：

```bash
cd frontend
npm ci
npm run build
```

生成目录：

```text
frontend/dist
```

Nginx 直接托管 `dist`。

生产环境建议优先使用同域路径：

```env
VITE_API_BASE_URL=
```

前端 API 请求会使用：

```text
/api/problems
/api/problems/{id}
/api/solutions
```

Nginx 将这些请求转发到 FastAPI。

这样比把 API 配置成独立域名更简单：

```text
https://arena.example.com/
https://arena.example.com/api/problems
```

Nginx 需要配置 SPA fallback：

```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```

但 `/api/` 必须放在静态文件 fallback 之前，避免 API 请求被错误地返回 `index.html`。

---

## 8. Nginx 配置

已落地模板：

```text
deploy/nginx/multi-agent-arena.conf
```

主要职责：

- 静态文件托管；
- `/api/` 反向代理；
- `/health` 反向代理；
- HTTPS；
- HTTP 跳转 HTTPS；
- 访问日志和错误日志；
- 基础安全响应头；
- 请求体大小限制；
- 代理超时；
- 可选 IP 白名单或 Basic Auth。

逻辑结构：

```nginx
server {
    listen 80;
    server_name arena.example.com;

    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name arena.example.com;

    root /srv/multi-agent-arena/frontend/current;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location = /health {
        proxy_pass http://127.0.0.1:8000/health;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

实际文档中会标明：

- `proxy_pass` 尾部斜杠行为；
- `location /api/` 路径保留方式；
- `proxy_read_timeout` 对同步 Agent 请求的影响；
- 不能盲目信任来自公网的 `X-Forwarded-*`；
- Nginx 是可信代理，FastAPI 不应自行接受任意伪造代理头。

---

## 9. HTTPS 与域名

目标环境使用 Certbot + Let’s Encrypt 作为经典 Nginx 方案；截至 2026-09-10，域名仍在 ICP 审核，HTTPS 尚未启用：

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo certbot --nginx -d arena.example.com
```

说明：

- 域名 A/AAAA 记录指向 VPS；
- 80 端口必须可访问；
- 443 端口必须开放；
- Certbot 自动配置证书和 Nginx；
- 需要测试自动续期：

```bash
sudo certbot renew --dry-run
```

这部分会作为待用户在真实 VPS 上执行的命令记录。不会在当前环境自动执行。

---

## 10. VPS 防火墙与 SSH

建议只开放：

```text
22/tcp   SSH
80/tcp   HTTP / ACME
443/tcp  HTTPS
```

禁止开放：

```text
5432/tcp PostgreSQL
8000/tcp FastAPI
```

实际 ECS 使用 firewalld：

```bash
sudo systemctl enable --now firewalld
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

注意：

- 启用或收紧防火墙前必须确保 SSH 规则正确，否则可能锁死自己；
- 如果公网 IP 经常变化，不应只依赖固定 IP 白名单；
- 可用 SSH 隧道或 VPN 管理数据库，不开放 PostgreSQL 公网端口；
- 当前未开放 PostgreSQL `5432` 和 FastAPI `8000` 公网端口。

---

## 11. 环境变量

已落地公开样例：

```text
.env.deploy.example
```

示例只包含占位符：

```env
APP_NAME="Multi-Agent Algorithmic Arena API"
DEBUG=false
DATABASE_URL=postgresql+asyncpg://arena_app:CHANGE_ME@postgres:5432/multi_agent_arena
AGENT_RETRY_COUNT=1
CORS_ORIGINS=https://arena.example.com

POSTGRES_DB=multi_agent_arena
POSTGRES_USER=arena_app
POSTGRES_PASSWORD=CHANGE_ME
```

VPS 上首次部署前，复制样例并替换占位符：

```bash
cp .env.deploy.example .env.deploy
chmod 600 .env.deploy
```

`.env.deploy` 已加入 Git 忽略规则，不得提交真实密码。

真实文件：

```text
/opt/multi-agent-arena/app/.env
```

必须：

```bash
chmod 600 /opt/multi-agent-arena/app/.env
```

不会提交：

- 数据库密码；
- SSH 私钥；
- TLS 私钥；
- 真实域名凭据；
- 真实 API Key。

---

## 12. migration 与 seed

部署文档会明确区分：

### 只读或非破坏操作

```bash
docker compose config
docker compose ps
docker compose logs
curl http://127.0.0.1:8000/health
```

### 数据库写操作

```bash
docker compose run --rm backend python -m alembic upgrade head
docker compose run --rm backend python -m app.seed
```

上述命令会：

- 创建或修改数据库结构；
- 插入预置题目数据。

在正式 VPS 上执行前，需要获得针对该目标数据库的明确许可。文档只会提供命令、前置检查、备份和恢复说明，不会代替用户执行正式数据库写入。

---

## 13. 备份与恢复

数据库备份计划：

```bash
mkdir -p /opt/multi-agent-arena/backups

docker compose exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  | gzip > /opt/multi-agent-arena/backups/multi-agent-arena-$(date +%F-%H%M%S).sql.gz
```

恢复原则：

- 恢复到临时数据库后先验证；
- 不直接覆盖正式数据库；
- 备份不能只存储在同一台 VPS；
- 定期将备份复制到异地；
- 恢复前记录当前数据库备份；
- 恢复后验证 migration 版本、题目数量和 API。

文档会提供恢复命令模板，但不会在没有明确批准的情况下执行数据库恢复。

---

## 14. 发布与回滚

发布流程：

```text
准备代码
→ 执行本地测试
→ 构建前端 dist
→ 构建 backend 镜像
→ 上传或拉取代码
→ 启动 PostgreSQL
→ 检查 PostgreSQL health
→ 执行 migration
→ 执行 seed
→ 启动 backend
→ 检查 backend health
→ 发布前端静态文件
→ nginx -t
→ systemctl reload nginx
→ 浏览器端到端验证
```

回滚流程：

```text
保留旧 backend 镜像
→ 回退 frontend current 软链接
→ 回退 backend 镜像标签
→ nginx -t
→ reload nginx
→ 检查 API
```

数据库回滚需要单独处理：

- 不把 `alembic downgrade` 作为默认回滚方案；
- 先判断 migration 是否破坏性变更；
- 优先设计向前兼容 migration；
- 数据恢复使用经过验证的备份；
- 生产数据库 downgrade 或 restore 前需要明确批准。

---

## 15. 测试和验收

### 15.1 2026-09-13 实际验证状态

- ECS：Alibaba Cloud Linux 3.2104 U13.2，2 vCPU，约 1.8 GiB RAM，2 GiB Swap；
- Docker Engine：26.1.3；Docker Compose：v2.27.0；Nginx：1.24.0；
- PostgreSQL 与 FastAPI 容器均为 healthy；
- Alembic：`0001 (head)`；seed：2 道题，重复 seed 插入 0 条；
- `http://127.0.0.1:8000/health`、`http://127.0.0.1/health`、`http://127.0.0.1/api/problems` 均返回 HTTP 200；
- `http://47.119.120.86` 前端页面可访问，并通过同源 `/api` 完成公网联调；
- 2026-09-13 候选镜像 `app-backend:412ba74` 已在 ECS 重建并健康运行；`/health`、`/api/problems` 的本机及公网 IP 访问返回 HTTP 200；
- 已完成一次 PostgreSQL 备份，文件权限为 `600`；
- 已完成一次受控真实 LLM 请求，网页端能够返回解题结果；
- 尚未完成：安全组正式白名单、Nginx `/api/solutions` 限流和 429 验证、专用 Key 额度/费用告警、密码轮换、异地备份和恢复演练、正式域名、HTTPS 和 Certbot 自动续期。

### 15.2 验证命令模板

本地验证：

```powershell
cd backend
python -m pytest -q
python -m compileall -q app alembic tests

Set-Location "..\frontend"
npm test -- --run
npm run build
```

容器验证：

```bash
docker compose config
docker compose build
docker compose up -d postgres
docker compose ps
docker compose logs postgres
```

FastAPI 验证：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/problems
```

Nginx 验证：

```bash
sudo nginx -t
sudo systemctl reload nginx
curl -I https://arena.example.com/
curl -I https://arena.example.com/health
curl https://arena.example.com/api/problems
```

浏览器验收：

```text
首页加载
→ 题目列表加载
→ 题目详情加载
→ MockAgent 解题
→ Markdown 结果展示
```

网络安全验收：

- 公网不能访问 `5432`；
- 公网不能直接访问 `8000`；
- Nginx 未授权访问被拒绝；
- 当前公网 IP + HTTP 已验证，正式域名下应验证 HTTP 自动跳转 HTTPS；
- CORS 不允许未知来源；
- 日志不包含密码或密钥。
