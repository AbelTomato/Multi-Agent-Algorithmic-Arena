class MockAgent:
    """不依赖外部模型服务的固定 Agent 实现。"""

    async def generate(self, prompt: str) -> str:
        """返回固定结构的 Markdown，用于验证业务闭环。"""

        return """## 解题思路

这是 MockAgent 返回的示例解题思路。实际 Agent 将根据服务端提供的题目 Prompt 生成内容。

## 算法步骤

1. 读取题目输入。
2. 按题目要求执行算法。
3. 返回符合题意的结果。

## 正确性说明

该示例结果用于验证接口和 Markdown 展示链路，不代表具体题目的正式解法。

## 时间复杂度

时间复杂度：`O(n)`。

## 空间复杂度

空间复杂度：`O(n)`。

## Python 代码

```python
def solve() -> None:
    "MockAgent 示例代码。"

    pass
```
"""