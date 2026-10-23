"""先用固定回复学习协议；之后只替换 generate 即可接入真实模型。"""

from collections.abc import Sequence
from typing import Any, Protocol


class Model(Protocol):
    def generate(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]: ...


class ScriptedModel:
    """按顺序交出预写响应，不做推理，也不会根据读取结果诊断缺陷。"""

    def __init__(self, responses: Sequence[dict[str, Any]]) -> None:
        self.responses = iter(responses)

    def generate(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        try:
            return next(self.responses)
        except StopIteration as exc:
            raise RuntimeError("脚本响应已用完；请补充 finish 或增加响应。") from exc


def demo_model() -> ScriptedModel:
    return ScriptedModel(
        [
            {"type": "tool_call", "name": "read_file", "arguments": {"path": "issue.md"}},
            {
                "type": "tool_call",
                "name": "read_file",
                "arguments": {"path": "calculator.py"},
            },
            {
                "type": "finish",
                "content": (
                    "预写演示结论：average 的分母 len(values) + 1 可疑，"
                    "空列表行为也需要明确。尚未修改文件或运行验收。"
                ),
            },
        ]
    )
