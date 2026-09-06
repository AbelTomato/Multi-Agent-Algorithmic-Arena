# Multi-Agent-Algorithmic-Arena

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Status](https://img.shields.io/badge/status-learning%20prototype-orange.svg)](#当前状态)

> 一个学习式渐进开发项目。远期目标是构建“多智能体算法竞技场”：多个 AI Agents 同台解算法题，由裁判系统评测代码，并支持辩驳、人机对战和实时观赛。

当前仓库不是完整产品，而是后端最小切片阶段。README 按当前真实状态编写，远期能力会在后续阶段逐步接入。

---

## 当前状态

当前已实现：

- FastAPI 后端应用入口：`backend/app/main.py`
- 配置管理：`backend/app/config.py`
- SQLAlchemy async 基础数据库连接：`backend/app/database.py`
- 最小 `Problem` 数据模型：`backend/app/models/problem.py`
- PostgreSQL 配置：`backend/.env.example`
- Agent 重试配置：`AGENT_RETRY_COUNT`（默认失败后重试 1 次）
- Alembic migration：`backend/alembic/`
- 题目 seed：`backend/app/seed.py`
- Problem API：`GET /api/problems`、`GET /api/problems/{problem_id}`
- Agent 抽象与 MockAgent：`backend/app/agents/`
- Solutions API：`POST /api/solutions`
- 健康检查：`GET /health`
- pytest 测试基线

当前尚未实现：

- React 前端
- Docker Compose
- Redis
- Judge0 沙箱
- LLM Provider 接入
- WebSocket 实时通信
- 比赛状态机
- 裁判与辩驳系统

当前测试基线：

```text
24 passed, 1 skipped
```

warnings 主要来自当前 Python 版本和依赖包的弃用提示，不阻塞现阶段学习开发。后续会评估将长期开发版本固定到 Python 3.11 或 3.12。

---

## 项目愿景

远期系统目标包括：

### 1. 多 Agent 算法竞赛

- 多个 AI Agent 同时接收算法题目；
- 各 Agent 独立思考、生成代码；
- 支持 OpenAI、Anthropic、DeepSeek、本地模型等 Provider；
- 实时追踪 Agent 思考、编码和提交过程。

### 2. 智能裁判系统

- 自动运行测试用例；
- 判断正确性、时间、内存；
- 结合 LLM 进行代码质量评审；
- 综合评分：正确性、效率、质量。

### 3. 辩驳机制

- Agent 可对裁判结果提出异议；
- Judge 审查辩驳理由；
- 支持有限轮次辩驳；
- 必要时进入仲裁。

### 4. 人机对战模式

- 限制 Agent 输出速度；
- 模拟人类思考和打字节奏；
- 提供 Web IDE；
- 支持人类与 Agent 同题竞赛。

### 5. 实时观赛

- WebSocket 推送比赛事件；
- 多客户端同步观赛；
- 实时排行榜；
- 比赛历史回放。

---

## 当前架构

当前实际架构：

```text
backend/
├── app/
│   ├── api/
│   │   └── problems.py
│   ├── schemas/
│   │   └── problem.py
│   ├── agents/
│   │   ├── base.py
│   │   ├── factory.py
│   │   └── mock.py
│   ├── providers/
│   │   └── base.py
│   ├── services/
│   │   └── solutions.py
│   ├── models/
│   │   └── problem.py
│   ├── config.py
│   ├── database.py
│   └── main.py
├── tests/
│   ├── test_config.py
│   ├── test_health.py
│   ├── test_problem_model.py
│   ├── test_problems_api.py
│   ├── test_problem_schemas.py
│   ├── test_agents.py
│   ├── test_solutions.py
│   ├── test_seed.py
│   └── test_postgres_integration.py
├── .env.example
├── pyproject.toml
└── requirements.txt
```

远期目标架构：

```text
React Frontend
      │ HTTP + WebSocket
      ▼
FastAPI Backend
      ├── Contest Manager
      ├── Agent Manager
      ├── Judge System
      ├── Debate Manager
      ├── WebSocket Hub
      └── Code Runner
      │
      ├── PostgreSQL
      ├── Redis
      └── Judge0
```

当前 MVP 的范围与后续决策基线见：[`docs/MVP开发构想.md`](./docs/MVP开发构想.md)。

---

## 技术栈

### 当前已使用

| 技术 | 版本 | 用途 |
| --- | --- | --- |
| Python | 3.11+ | 后端开发语言 |
| FastAPI | 0.115.x | Web API 框架 |
| SQLAlchemy async | 2.0.x | 异步 ORM |
| PostgreSQL + asyncpg | MVP 主数据库 | 题目、migration 和 seed |
| SQLite + aiosqlite | 仅用于现有快速单元测试 | 不作为 MVP 运行数据库 |
| Pydantic Settings | 2.x | 环境变量配置 |
| pytest | 8.x | 后端测试 |
| httpx | 0.28.x | 测试/HTTP 客户端依赖 |

### 后续计划接入

| 技术 | 用途 | 接入时机 |
| --- | --- | --- |
| Redis | 缓存/消息 | 比赛事件和队列需求明确后 |
| Judge0 | 代码执行沙箱 | Judge 抽象稳定后 |
| React + Vite | 前端界面 | 后端 API 和事件模型稳定后 |
| WebSocket | 实时通信 | 比赛状态机稳定后 |
| OpenAI / Anthropic / DeepSeek SDK | LLM Agent | MockAgent 跑通后 |
| Docker Compose | 本地多服务编排 | PostgreSQL、Redis、Judge0 接入时 |

---

## 快速开始：当前后端最小版本

### 1. 环境准备

当前需要：

- Python 3.11+
- Git
- PostgreSQL

暂不需要：

- Docker
- Node.js
- Redis
- Judge0
- LLM API Key

### 2. 克隆项目

```bash
git clone https://github.com/AbelTomato/Multi-Agent-Algorithmic-Arena.git
cd Multi-Agent-Algorithmic-Arena
```

### 3. 创建并激活虚拟环境

Windows PowerShell / CMD 示例：

```bat
python -m venv .venv
.venv\Scripts\activate
```

### 4. 安装后端依赖

```bat
cd backend
python -m pip install -r requirements.txt
```

### 5. 配置环境变量

当前环境变量示例位于：

```text
backend/.env.example
```

复制为本地 `.env`：

```bat
copy .env.example .env
```

当前 `.env.example` 内容：

```env
APP_NAME="Multi-Agent Algorithmic Arena API"
DEBUG=true
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/multi_agent_arena"
```

说明：`DATABASE_URL` 需要替换为本机或部署环境中的真实 PostgreSQL 连接串。当前阶段不需要填写 OpenAI、Anthropic、DeepSeek、Redis、Judge0 等配置。

### 6. 运行测试

在 `backend/` 目录执行：

```bat
python -m pytest -q
```

预期结果：

```text
24 passed, 1 skipped
```

如果未设置 `TEST_DATABASE_URL`，PostgreSQL 集成测试会跳过；设置后应执行全部测试。当前环境验证结果为 `21 passed, 1 skipped`。

### 7. 启动后端服务

在 `backend/` 目录执行：

```bat
python -m uvicorn app.main:app --reload
```

访问：

- 根路由：http://localhost:8000/
- 健康检查：http://localhost:8000/health
- API 文档：http://localhost:8000/docs
- 题目列表：http://localhost:8000/api/problems
- 解题接口：`POST http://localhost:8000/api/solutions`

当前阶段已经完成 PostgreSQL migration、seed、Problem API、Agent 抽象、MockAgent 和 Solutions API；数据库 Engine 按应用复用，Session 按请求创建。在运行 API 前，需要先执行 migration 和 seed。

在 `backend/` 目录执行：

```bat
python -m alembic upgrade head
python -m app.seed
```

---

## 文档

后续产品与技术决策以 [`docs/MVP开发构想.md`](./docs/MVP开发构想.md) 为唯一基线；已被替代的旧流程和决策文档已删除，当前实施计划与项目协作规则见下表。

| 文档 | 说明 |
| --- | --- |
| [`docs/MVP开发构想.md`](./docs/MVP开发构想.md) | 当前 MVP 范围、已确认决策、暂不实现功能与未决事项；后续决策基线 |
| [`docs/实施计划.md`](./docs/实施计划.md) | MVP 分阶段实施、测试、验收、部署和文档回填计划 |
| [`docs/学习笔记/Python项目结构与pytest.md`](./docs/学习笔记/Python项目结构与pytest.md) | Python 项目结构和 pytest 学习笔记 |
| [`.clinerules/项目开发协作规则.md`](./.clinerules/项目开发协作规则.md) | 本项目代码、测试、文档和高危操作的协作规则 |

---

## 当前 MVP 路线图

以 `docs/MVP开发构想.md` 的决策基线为准，按以下顺序推进：

1. 接入 PostgreSQL，配置 Alembic migration 与题目 seed。
2. 实现题目列表和题目详情 API，并补充 PostgreSQL 集成测试。
3. 定义统一 Agent / Provider 抽象，实现 MockAgent。
4. 实现同步 `POST /api/solutions`，由服务端统一生成 Prompt，并补充失败重试测试。
5. 实现 React + Vite + TypeScript + shadcn/ui + Tailwind CSS 前端，展示 Markdown 解题结果。
6. 部署 MockAgent 版本，验证 PostgreSQL、环境变量、CORS、白名单和健康检查。
7. 根据成本预算确定部署平台与一个真实 LLM Provider，再实现对应适配器。

当前不实现 Judge0、代码执行、评分、多 Agent、Redis、WebSocket、流式输出、历史记录或登录系统。

---

## 开发原则

本项目采用学习式渐进开发：

1. 先跑通最小闭环，再接复杂外部依赖。
2. 每个切片都要有明确学习目标、构建目标和验证方式。
3. 新功能优先配套测试。
4. 不把本地运行时文件提交进 Git，例如 `.env`、SQLite 数据库、缓存文件。
5. 文档要区分当前可运行状态和远期设计。

---

## 贡献说明

当前项目仍处于个人学习与原型阶段，暂不按成熟开源项目流程运作。

如果后续进入协作阶段，将补充：

- `LICENSE`
- issue 模板
- PR 模板
- 贡献指南
- 代码风格和 CI 规则

---

## 许可证

当前仓库尚未添加 `LICENSE` 文件。正式开源前需要明确许可证。

---

## 联系方式

- 作者：AbelTomato
- GitHub：https://github.com/AbelTomato
- 项目主页：https://github.com/AbelTomato/Multi-Agent-Algorithmic-Arena