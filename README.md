# Multi-Agent-Algorithmic-Arena

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![React](https://img.shields.io/badge/React-18+-61DAFB.svg)](https://reactjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)

> 🤖 一个创新的多智能体算法竞技场，让 AI Agents 实时竞赛解算法题，支持辩驳机制和人机对战。

## ✨ 项目亮点

- **🏆 多 Agent 实时竞赛** - 支持 GPT-4、Claude、DeepSeek 等多种 LLM 同台竞技
- **⚖️ AI 裁判系统** - 自动评判代码正确性、效率和质量，综合评分
- **💬 辩驳机制** - Agent 可对评判结果提出异议，智能仲裁系统保证公平
- **👥 人机对战** - 通过速度限制模拟人类行为，实现公平的人机竞赛
- **📊 实时可视化** - WebSocket 实时推送，观看 Agent 思考和编码全过程
- **🔒 安全沙箱** - Judge0 容器化执行环境，支持 60+ 编程语言

## 📋 核心功能

### 1. 多 Agent 算法竞赛

- 多个 AI agent 同时接收算法题目
- 各 agent 独立思考、编写解决方案
- 实时追踪解题进度和思维过程
- 支持自选 LLM 提供商（OpenAI / Anthropic / DeepSeek / 本地模型）

### 2. 智能裁判系统

- **正确性评判**：自动运行测试用例，验证代码正确性
- **效率评估**：分析时间复杂度和空间复杂度
- **质量审查**：LLM 评审代码风格、可读性和算法优雅度
- **综合评分**：正确性 50% + 效率 30% + 质量 20%

### 3. 辩驳（Debate）机制

- Agent 可对评判结果提出异议
- 提供论据和证据支撑辩驳
- Judge 审查并回应辩驳
- 最多 2 轮辩驳，超过则触发仲裁
- 辩驳成功可调整分数

### 4. 人机对战模式

- 限制 Agent 输出速度（字符/秒）
- 模拟思考延迟和打字节奏
- Web IDE 编辑器（Monaco Editor）
- 公平的竞赛体验

### 5. 实时通信

- WebSocket 双向通信
- 流式输出 Agent 思考过程
- 多客户端同步观赛
- 实时排行榜更新

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────┐
│              前端 (React + Vite + Tailwind)              │
│  比赛创建 | 实时竞赛页 | 题库管理 | 历史回放 | 统计分析  │
└───────────────────────┬─────────────────────────────────┘
                        │ WebSocket + HTTP API
┌───────────────────────┴─────────────────────────────────┐
│                   后端 (FastAPI)                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Contest Manager | Agent Manager | Judge System │   │
│  │  Debate Manager  | WebSocket Hub | Code Runner  │   │
│  └─────────────────────────────────────────────────┘   │
└───────────────────────┬─────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
   PostgreSQL        Redis          Judge0
   (数据存储)      (缓存/消息)    (代码执行)
```

详细设计请查看 [📖 总体设计文档](./docs/总体设计.md)

## 🛠️ 技术栈

### 后端

| 技术              | 版本     | 用途                 |
| ----------------- | -------- | -------------------- |
| **FastAPI**       | 0.115+   | 高性能异步 Web 框架  |
| **PostgreSQL**    | 16+      | 主数据库，支持 JSONB |
| **Redis**         | 7+       | 缓存和消息队列       |
| **SQLAlchemy**    | 2.0+     | 异步 ORM             |
| **Judge0**        | CE 1.13+ | 代码执行沙箱         |
| **OpenAI SDK**    | 最新     | GPT 模型接入         |
| **Anthropic SDK** | 最新     | Claude 模型接入      |
| **httpx**         | 最新     | 异步 HTTP 客户端     |

### 前端

| 技术              | 版本  | 用途       |
| ----------------- | ----- | ---------- |
| **React**         | 18+   | UI 框架    |
| **TypeScript**    | 5+    | 类型安全   |
| **Vite**          | 5+    | 构建工具   |
| **Tailwind CSS**  | 3+    | 样式框架   |
| **Shadcn UI**     | 最新  | 组件库     |
| **Monaco Editor** | 0.52+ | 代码编辑器 |
| **Zustand**       | 5+    | 状态管理   |

### DevOps

- **Docker** + **Docker Compose** - 容器化部署
- **Alembic** - 数据库迁移
- **pytest** - 后端测试
- **Vitest** - 前端测试

## 🚀 快速开始

### 环境准备

确保已安装：
- **Docker** 和 **Docker Compose**
- **Python 3.11+**
- **Node.js 20+**
- **Git**

### 1. 克隆项目

```bash
git clone https://github.com/AbelTomato/Multi-Agent-Algorithmic-Arena.git
cd Multi-Agent-Algorithmic-Arena
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入 API Keys：

```env
# LLM API Keys
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
DEEPSEEK_API_KEY=your_deepseek_key

# 数据库配置
DATABASE_URL=postgresql://postgres:password@localhost:5432/arena
REDIS_URL=redis://localhost:6379

# Judge0 配置
JUDGE0_URL=http://localhost:2358
```

### 3. 启动开发环境

```bash
# 一键启动所有服务（PostgreSQL + Redis + Judge0 + 后端 + 前端）
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 4. 初始化数据库

```bash
# 进入后端容器
docker-compose exec backend bash

# 运行迁移
alembic upgrade head

# 导入示例题目（可选）
python scripts/seed_problems.py
```

### 5. 访问应用

- **前端界面**：http://localhost:5173
- **后端 API 文档**：http://localhost:8000/docs
- **Judge0 API**：http://localhost:2358

## 📖 文档

- [📋 实施计划](./docs/实施计划.md) - 分阶段开发计划和里程碑
- [🏗️ 总体设计](./docs/总体设计.md) - 架构设计和技术实现细节
- [🔌 接口设计](./docs/接口设计.md) - API 接口和 WebSocket 事件协议（待补充）
- [💾 数据结构设计](./docs/数据结构设计.md) - 数据库表结构（待补充）

## 🎯 开发路线图

### 阶段一：基础设施 ✅ (规划中)
- [ ] 初始化后端项目结构
- [ ] 初始化前端项目结构
- [ ] 配置 Docker Compose
- [ ] 数据库模型定义

### 阶段二：Agent 系统 (规划中)
- [ ] BaseAgent 抽象接口
- [ ] OpenAI / Anthropic / DeepSeek 适配器
- [ ] Agent Factory 工厂模式
- [ ] 速度限制器

### 阶段三：裁判系统 (规划中)
- [ ] Judge0 集成
- [ ] 评分逻辑实现
- [ ] 裁判 Agent（代码质量评审）
- [ ] 辩驳流程管理器

### 阶段四：比赛引擎 (规划中)
- [ ] 比赛状态机
- [ ] WebSocket 连接管理
- [ ] 多 Agent 并发调度

### 阶段五：前端实现 (规划中)
- [ ] 实时竞赛主界面
- [ ] Agent 思考过程可视化
- [ ] 人类选手代码编辑器
- [ ] 题库管理

### 阶段六：高级功能 (规划中)
- [ ] Codeforces 题目导入
- [ ] 比赛历史回放
- [ ] 统计分析面板

详细计划请查看 [📋 实施计划](./docs/实施计划.md)

## 🤝 贡献指南

欢迎贡献代码、报告问题或提出建议！

### 开发流程

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 提交更改：`git commit -m 'feat: add some feature'`
4. 推送分支：`git push origin feature/your-feature`
5. 提交 Pull Request

### 提交规范

遵循 Conventional Commits：

```
feat: 新功能
fix: 修复 bug
docs: 文档更新
test: 测试相关
refactor: 重构
chore: 构建/依赖更新
```

### 代码风格

- **Python**：遵循 PEP 8，使用 `black` 格式化
- **TypeScript/React**：遵循 Airbnb 风格，使用 `prettier` 格式化

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](./LICENSE) 文件。

## 🙏 致谢

- [FastAPI](https://fastapi.tiangolo.com/) - 现代化的 Python Web 框架
- [Judge0](https://judge0.com/) - 开源的代码执行引擎
- [Shadcn UI](https://ui.shadcn.com/) - 精美的 React 组件库
- [OpenAI](https://openai.com/) / [Anthropic](https://anthropic.com/) / [DeepSeek](https://deepseek.com/) - 强大的 LLM 提供商

## 📧 联系方式

- **作者**：AbelTomato
- **GitHub**：https://github.com/AbelTomato
- **项目主页**：https://github.com/AbelTomato/Multi-Agent-Algorithmic-Arena

---

⭐ 如果这个项目对你有帮助，请给个 Star 支持一下！
