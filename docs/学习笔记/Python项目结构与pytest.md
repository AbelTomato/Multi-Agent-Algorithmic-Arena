# Python 项目结构与 pytest

本文档记录本项目后端从 Python 工程角度的基础结构，以及 `pyproject.toml`、`requirements.txt`、`pytest` 分别承担的职责。

参考文件：

- `backend/pyproject.toml`
- `backend/requirements.txt`
- `backend/tests/test_health.py`

---

## 一、一个 Python 项目通常由什么组成

现代 Python 项目通常不是只有 `.py` 文件，而是由以下几层组成：

```text
backend/
├── app/                  # 业务代码，也就是应用本体
│   ├── __init__.py
│   ├── main.py           # FastAPI 入口
│   └── ...
├── tests/                # 测试代码
│   └── test_health.py
├── requirements.txt      # 依赖清单，告诉 pip 要安装哪些第三方包
├── pyproject.toml        # 项目元信息 + 工具配置
├── .env.example          # 环境变量示例，可以提交 Git
└── .env                  # 本机真实环境变量，不应提交 Git
```

从 Python 的视角，可以分成五层：

| 层级       | 作用                         | 本项目示例         |
| ---------- | ---------------------------- | ------------------ |
| 代码层     | 真正的业务代码               | `backend/app/`     |
| 测试层     | 验证代码是否正确             | `backend/tests/`   |
| 依赖层     | 声明项目依赖哪些包           | `requirements.txt` |
| 工具配置层 | 配置测试、格式化、Python版本 | `pyproject.toml`   |
| 运行环境层 | 环境变量、虚拟环境、数据库等 | `.env`、`.venv`    |

核心心智模型：

```text
requirements.txt 管“安装什么包”。
pyproject.toml 管“项目和工具怎么工作”。
pytest 管“怎么验证代码是否正确”。
```

---

## 二、`pyproject.toml` 是什么

`pyproject.toml` 是现代 Python 项目的项目配置中心。

它可以配置：

- 项目名称、版本、Python 版本要求；
- pytest 测试行为；
- ruff 代码检查规则；
- black 格式化规则；
- mypy 类型检查规则；
- poetry、hatch、uv 等构建或包管理工具。

本项目当前配置如下：

```toml
[project]
name = "multi-agent-algorithmic-arena-backend"
version = "0.1.0"
description = "FastAPI backend for Multi-Agent Algorithmic Arena"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"

[tool.ruff]
line-length = 100
target-version = "py311"
```

---

## 三、`[project]`：项目元信息

```toml
[project]
name = "multi-agent-algorithmic-arena-backend"
version = "0.1.0"
description = "FastAPI backend for Multi-Agent Algorithmic Arena"
requires-python = ">=3.11"
```

这一段描述这个 Python 项目本身。

### `name`

项目名。

如果以后执行：

```bash
pip install -e .
```

这个名称会成为 Python 包项目名。

### `version`

项目版本。

常见格式是语义化版本：

```text
主版本.次版本.修订版本
major.minor.patch
```

例如：

```text
0.1.0   初始开发阶段
1.0.0   第一个稳定版本
1.1.0   增加功能
1.1.1   修复 bug
```

### `description`

项目描述。

### `requires-python`

```toml
requires-python = ">=3.11"
```

表示本项目要求 Python 版本至少为 3.11。

这很重要，因为不同 Python 版本支持的语法、标准库能力和性能不同。

---

## 四、`[tool.pytest.ini_options]`：pytest 配置

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

这一段告诉 pytest：运行测试时应该如何找测试、如何处理导入、如何处理异步测试。

### `testpaths = ["tests"]`

表示 pytest 默认只在 `tests/` 目录下查找测试。

因此当你在 `backend/` 目录执行：

```bash
pytest
```

pytest 会主要扫描：

```text
backend/tests/
```

这样可以避免 pytest 在整个项目里乱扫，提高速度，也减少误识别。

### `pythonpath = ["."]`

这个配置非常关键。

当前测试文件 `backend/tests/test_health.py` 中有：

```python
from app.main import app
```

这要求 Python 能从当前目录找到 `app` 包。

如果你在 `backend/` 目录运行 pytest，那么：

```text
.
```

就是：

```text
backend/
```

所以：

```toml
pythonpath = ["."]
```

等价于告诉 pytest：

```text
运行测试时，把 backend/ 加入 Python 的模块搜索路径。
```

否则可能会出现：

```text
ModuleNotFoundError: No module named 'app'
```

### `asyncio_mode = "auto"`

FastAPI 后续会大量使用异步代码，例如：

```python
async def get_contest():
    ...
```

pytest 本身需要配合 `pytest-asyncio` 才能方便地运行异步测试。

```toml
asyncio_mode = "auto"
```

表示 pytest-asyncio 自动识别和处理异步测试。

后续可以写：

```python
import pytest


@pytest.mark.asyncio
async def test_something_async():
    result = await some_async_function()
    assert result == "ok"
```

### `asyncio_default_fixture_loop_scope = "function"`

表示异步测试的 fixture 默认使用函数级别作用域。

简单理解：每个测试函数尽量有独立的异步上下文，减少测试之间的状态污染。

这对后续测试数据库、WebSocket、异步 Agent 很有帮助。

---

## 五、`[tool.ruff]`：代码检查配置

```toml
[tool.ruff]
line-length = 100
target-version = "py311"
```

Ruff 是一个很快的 Python 代码检查和格式化工具。

它可以检查：

- 未使用的 import；
- 变量命名问题；
- 代码风格问题；
- 一些潜在 bug；
- import 排序；
- 复杂度问题。

### `line-length = 100`

表示建议一行代码不要超过 100 个字符。

### `target-version = "py311"`

表示 Ruff 按 Python 3.11 的语法能力检查代码。

---

## 六、`pyproject.toml` 和 `requirements.txt` 的区别

本项目同时有：

```text
backend/pyproject.toml
backend/requirements.txt
```

它们职责不同。

| 文件               | 主要作用       | 主要给谁用               |
| ------------------ | -------------- | ------------------------ |
| `requirements.txt` | 依赖安装清单   | `pip`                    |
| `pyproject.toml`   | 项目和工具配置 | pytest、ruff、构建工具等 |

当前 `requirements.txt` 内容：

```txt
fastapi==0.115.6
uvicorn[standard]==0.34.0
sqlalchemy[asyncio]==2.0.36
aiosqlite==0.20.0
alembic==1.14.0
pydantic-settings==2.7.1
python-dotenv==1.0.1
pytest==8.3.4
pytest-asyncio==0.25.2
httpx==0.28.1
```

它回答的问题是：

```text
这个项目运行和测试需要安装哪些第三方库？
```

执行：

```bash
pip install -r requirements.txt
```

pip 就会根据这个文件安装依赖。

而 `pyproject.toml` 回答的是：

```text
这个项目叫什么？
要求什么 Python 版本？
pytest 怎么运行？
ruff 怎么检查？
构建工具怎么工作？
```

---

## 七、pytest 是什么

`pytest` 是 Python 最常用的测试框架之一。

它的作用是：

```text
自动发现测试文件，运行测试函数，报告哪些通过、哪些失败。
```

当前测试文件：

```python
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_returns_api_message() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Multi-Agent Algorithmic Arena API"}


def test_health_check_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

这说明本项目已经有一个很好的起点：健康检查测试。

---

## 八、pytest 如何发现测试

pytest 默认会查找：

```text
test_*.py
*_test.py
```

并运行其中以 `test_` 开头的函数。

所以这个文件会被发现：

```text
backend/tests/test_health.py
```

这两个函数也会被运行：

```python
def test_root_returns_api_message() -> None:
    ...


def test_health_check_returns_ok() -> None:
    ...
```

因为它们都以 `test_` 开头。

---

## 九、pytest 如何判断测试是否通过

pytest 主要看 `assert`。

例如：

```python
assert response.status_code == 200
```

如果实际结果是 200，测试通过。

如果实际结果是 404，pytest 会报告失败，并告诉你类似：

```text
assert 404 == 200
```

这就是测试的价值：

```text
把“我感觉接口能用”变成“自动验证接口确实符合预期”。
```

---

## 十、当前 `test_health.py` 在测什么

### 10.1 根路径接口

```python
def test_root_returns_api_message() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Multi-Agent Algorithmic Arena API"}
```

它验证：

```text
GET /
```

应该返回：

```json
{"message": "Multi-Agent Algorithmic Arena API"}
```

并且 HTTP 状态码是 200。

### 10.2 健康检查接口

```python
def test_health_check_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

它验证：

```text
GET /health
```

应该返回：

```json
{"status": "ok"}
```

这类接口叫健康检查接口，通常用于确认服务是否还活着。

---

## 十一、从 Python 视角搭建一个项目的标准步骤

### 11.1 确定项目边界

大项目中，前后端通常分离：

```text
project-root/
├── backend/
├── frontend/
└── docs/
```

这说明 Python 后端是整个系统中的一个子项目。

### 11.2 创建业务代码目录

```text
backend/app/
```

`app` 通常是 FastAPI 项目的应用包。

`__init__.py` 表示该目录是一个 Python package。

### 11.3 创建入口文件

FastAPI 常见入口：

```text
backend/app/main.py
```

示例：

```python
from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def root():
    return {"message": "Multi-Agent Algorithmic Arena API"}
```

启动命令：

```bash
uvicorn app.main:app --reload
```

其中：

```text
app.main  -> Python 模块路径，即 backend/app/main.py
app       -> 这个模块里面的 FastAPI 实例变量名
```

### 11.4 创建虚拟环境

```bash
python -m venv .venv
```

虚拟环境用于隔离不同项目的依赖。

否则可能出现：

```text
项目 A 需要 fastapi==0.115
项目 B 需要 fastapi==0.100
```

二者互相冲突。

### 11.5 声明依赖

当前项目使用：

```text
requirements.txt
```

安装依赖：

```bash
pip install -r requirements.txt
```

### 11.6 编写 `pyproject.toml`

用于声明：

- 项目名；
- Python 版本；
- pytest 配置；
- ruff 配置；
- 后续可能还有 mypy、black、coverage 等。

### 11.7 编写测试

创建：

```text
backend/tests/test_health.py
```

优先测试 `/health` 是很好的起点，因为它可以验证：

- FastAPI app 可以导入；
- 路由注册正常；
- 测试客户端可用；
- pytest 配置可用。

### 11.8 运行测试

在 `backend/` 目录下执行：

```bash
pytest
```

pytest 会：

1. 找 `backend/tests/`；
2. 找 `test_*.py`；
3. 导入 `app.main`；
4. 执行测试函数；
5. 输出结果。

---

## 十二、当前项目已经具备什么

当前后端已经具备：

```text
backend/pyproject.toml       ✅ 项目和工具配置
backend/requirements.txt     ✅ 依赖清单
backend/.env.example         ✅ 环境变量模板
backend/.env                 ✅ 本地环境文件
backend/app/                 ✅ 应用代码目录
backend/tests/test_health.py ✅ 基础健康检查测试
```

也就是说，Python 后端的最小工程骨架已经基本具备。

---

## 十三、常见问题

### 13.1 `ModuleNotFoundError: No module named 'app'`

常见原因：

- 不在 `backend/` 目录运行 pytest；
- `pyproject.toml` 中缺少 `pythonpath = ["."]`；
- `app/` 目录不存在或结构不对。

解决思路：

```bash
cd backend
pytest
```

并确认 `backend/pyproject.toml` 中有：

```toml
pythonpath = ["."]
```

### 13.2 `pytest` 命令找不到

常见原因：

- 没有激活虚拟环境；
- 没有安装依赖；
- 安装到了系统 Python，而不是项目 `.venv`。

解决思路：

```bash
cd backend
.venv\Scripts\activate
pip install -r requirements.txt
pytest
```

### 13.3 Python 版本不符合要求

项目要求：

```toml
requires-python = ">=3.11"
```

可以检查：

```bash
python --version
```

如果版本过低，需要安装 Python 3.11+。

---

## 十四、后续学习路线

建议分四个阶段学习。

### 第一阶段：项目能跑

掌握：

- `.venv`；
- `requirements.txt`；
- `pyproject.toml` 中 pytest 配置；
- pytest 发现规则；
- `uvicorn app.main:app --reload`。

### 第二阶段：项目能测

掌握：

- fixture；
- mock；
- 异步测试；
- 测试数据库；
- FastAPI dependency override。

### 第三阶段：项目能维护

掌握：

- ruff；
- mypy；
- coverage；
- pre-commit；
- CI。

### 第四阶段：项目能发布

掌握：

- Python package build；
- wheel；
- editable install；
- Poetry / uv / Hatch；
- Docker 镜像构建。

---

## 十五、当前建议的练习

在 `backend/` 目录中依次执行：

```bash
pytest
uvicorn app.main:app --reload
```

然后回答三个问题：

1. pytest 是从哪个目录发现测试的？
2. `from app.main import app` 为什么能成功？
3. `uvicorn app.main:app --reload` 中两个 `app` 分别是什么意思？
