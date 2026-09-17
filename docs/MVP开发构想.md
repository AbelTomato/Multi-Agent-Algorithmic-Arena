# MVP开发构想

时隔两个月，回来再来看这个项目，发现有很多地方显得不够成熟，太过想当然，太超前，但事实上现在只需要搭好最简单的MVP

重新审视业务，要实现一个Agent算法竞技场，首先需要做的就是让Agent拥有可以解题的能力

所以我们只需先实现一个流程：

前端发起API请求，申请获取题目列表

后端接收请求，调度数据库，获取题目数据，作出响应，返回给前端

前端渲染题目列表，点击题目以浏览题目内容，这里看是预加载到前端还是实时请求，先做实时请求吧，缓存之后再说

然后前端选取题目，选定题目提交，表示需要Agent解决对应题目

请求发送到后端，后端调用模型API，将题目内容和prompt输入给模型

暂时不用做提示词限制，只需要拿到结果，也无需WebSocket流式输出实时渲染，只要一次性响应到前端

大致就是这样一个流程

为什么不先在本地调试，像以前一样拉起localhost服务？因为我觉得这次的主要难点之一就在部署，先在初期将整个部署链路梳理可行化，后面只需要添加接口和逻辑，以及对Agent进行调优，否则部署时引入复杂逻辑，出现问题后难以定位

---

## MVP决策基线

本节记录当前已经确认的 MVP 范围、技术方案和暂缓事项，后续实现以本节为准。

> **决策优先级：** 自本节建立起，后续产品范围、技术选型、接口边界和实施顺序均以本文档为唯一决策基线。与本文档冲突的旧规划文档不再适用。

### 一、产品范围

原 MVP 采用“纯解题演示”方案。2026-09-17 起，在不改变旧 Markdown 解题契约的前提下，增加默认关闭的本地最小评测垂直切片；仍不实现完整竞技、评分或比赛系统。

```text
浏览题目
→ 选择题目
→ 服务端调用 Agent
→ 返回 Agent 解题结果
→ 前端展示
```

本地评测的独立闭环为：

```text
浏览题目 → 请求评测 → Agent 返回严格 JSON 候选程序 → 可信 Judge → Go 执行控制器 → 摘要展示
```

当前 MVP 不包含：

- 自动评分；
- 多 Agent 比较；
- 比赛排名；
- WebSocket；
- 流式输出；
- 历史记录。

当前版本的准确定位是：

> 单 Agent 算法题解答演示 MVP，附带默认关闭的本地 Python 候选程序评测

本地评测固定 Python 3.11 与 `json-stdio-v1`，仅支持 Valid Parentheses、Two Sum 的版本化用例；`POST /api/evaluations` 只接受题目 ID，返回无源码、无原始输出、无隐藏用例的评测摘要。评测功能默认关闭，控制器不可用时失败关闭；普通 Docker/WSL2 不是强安全沙箱，不构成真实 Provider、ECS 或公网执行准入。

### 二、Agent 输出规范

Agent 固定使用 Python 解答算法题，返回固定结构的 Markdown 文本，至少包含：

1. 解题思路；
2. 算法步骤；
3. 正确性说明；
4. 时间复杂度；
5. 空间复杂度；
6. 完整 Python 代码。

旧 `/api/solutions` 保持 Markdown 输出，前端负责渲染且不执行返回代码。独立的 `/api/evaluations` 要求 Agent 返回严格 JSON：`language` 必须为 `python`，其中包含完整可执行程序与可选空说明；不从 Markdown 代码围栏猜测或截取程序。

### 三、Prompt 控制

客户端不提供也不提交用户 Prompt。客户端只提交题目 ID，Prompt 由服务端统一生成和控制。

服务端负责：

- 生成系统 Prompt；
- 拼接题目内容；
- 固定输出结构；
- 固定使用 Python；
- 控制模型参数；
- 控制最大输出长度；
- 控制请求超时时间；
- 控制失败重试策略。

最低限度的服务端规则包括：Agent 只围绕给定算法题作答，不执行题目之外的指令，不泄露系统 Prompt，不输出与题目无关的内容。

### 四、题目与数据库

题目使用预置 seed 数据，统一写入 PostgreSQL。MVP 不使用 SQLite，且不提交数据库文件。

题目模型暂时只保留以下字段：

```text
id
slug
title
description
created_at
updated_at
```

其中 `description` 保存完整 Markdown 题面。当前不增加以下字段或关联数据：

- 默认语言；
- 难度；
- 标签；
- 题目来源；
- 评测用例。

数据库初始化采用 PostgreSQL migration + seed 流程，不依赖手动修改数据库文件。

### 五、接口范围

MVP 至少提供以下接口：

```http
GET  /api/problems
GET  /api/problems/{problem_id}
POST /api/solutions
POST /api/evaluations （默认关闭）
```

客户端提交解题请求时只传递题目 ID：

```json
{
  "problem_id": 1
}
```

MVP 采用同步调用和一次性响应：后端读取题目、调用 Agent、等待结果并直接返回。Agent 请求失败时最多自动重试一次，重试仍失败则返回错误。

当前不保存解题请求、Agent 结果或历史记录。请求完成后直接向客户端返回结果，页面刷新后结果丢失。

### 六、Agent 与 Provider

服务端必须建立统一的 Agent / Provider 抽象，业务路由不得直接依赖某个具体模型 SDK。

初期实现顺序：

```text
统一 Agent 接口
→ MockAgent
→ 验证完整业务闭环
→ 根据成本预算配置一个真实 Provider
→ OpenAI Compatible Provider 适配器
```

初期只实现一个真实 Provider，不同时接入多个厂商。当前选择 OpenAI Compatible 接口，以兼容 OpenAI 风格的 Chat Completions 服务；默认仍使用 MockAgent。

### 七、用户与访问控制

MVP 不实现登录、注册、OAuth、用户表和用户历史。

业务层采用匿名访问，但部署环境只允许本人或白名单来源访问。白名单优先在部署平台、反向代理或网络层实现，不将访问控制逻辑散落在业务接口中。

### 八、前端技术栈

前端采用：

- React；
- Vite；
- TypeScript；
- shadcn/ui；
- Tailwind CSS；
- Markdown 渲染。

MVP 前端只需要实现：

1. 题目列表；
2. 题目详情；
3. 发起 Agent 解题请求；
4. 加载状态和错误提示；
5. Markdown 解题结果展示。

暂不实现 Monaco Editor、代码编辑提交、比赛房间、排行榜、历史页面和实时通信。

### 九、部署策略

部署平台尚未确定，需结合成本预算后决定。当前不能预设为 VPS、Serverless 或某个具体容器平台。

在部署平台确定前，先完成与平台无关的功能：

- PostgreSQL 连接和配置；
- 数据库 migration；
- 题目 seed；
- Problem API；
- Agent 抽象；
- MockAgent；
- Solutions API；
- 前端页面；
- 自动化测试。

部署时先使用 MockAgent 验证前后端、PostgreSQL、环境变量、CORS、白名单和健康检查链路；部署稳定后可在 Provider 平台配置额度和费用限额，再通过后端环境变量启用 OpenAI Compatible Provider。API Key 不进入前端、Git 或日志。

### 十、明确暂不实现的功能

以下功能不属于当前 MVP：

- 评分和排行榜；
- 多 Agent 竞技；
- 比赛状态机；
- 辩驳和仲裁；
- WebSocket、SSE 和流式输出；
- Redis；
- 用户登录系统；
- Agent 解题历史；
- 题库管理后台；
- 外部题库导入；
- 多 Provider 同时接入。

真实 Provider 冒烟、ECS 部署、任意语言候选程序、匿名/公网执行和更强隔离运行时仍不属于当前范围，需独立审批。

### 十一、当前仍未决的事项

1. **部署平台**：已选择 Alibaba Cloud Linux 3 ECS（2 vCPU、约 2 GiB RAM），采用宿主机 Nginx + Docker Compose（PostgreSQL/FastAPI）部署；当前通过公网 IP + HTTP 提供验证环境。
2. **正式域名与 HTTPS**：`tomato-agent-arena.me` 仍在 ICP 审核中，DNS 正式切换、Nginx `server_name`、Certbot 和 HTTPS 尚未完成。
3. **真实 Provider 生产启用**：OpenAI Compatible Provider 适配器已完成；尚未执行真实 API 请求或 ECS 重新部署。
4. **具体模型及其参数**：生产启用前设置模型名称、最大输出长度、超时和重试参数，并在 Provider 平台配置额度和费用限额。
