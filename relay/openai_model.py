"""Responses API 适配层：保留原始上下文，将一个动作交给 Relay 执行。"""

import copy
import json
import math
import os
from typing import Any


class ProviderProtocolError(RuntimeError):
    """响应不能安全地转换成当前单动作协议。"""


class IncompleteResponse(ProviderProtocolError):
    """包括输出截断；不执行未完成响应中的工具。"""


class RefusedResponse(ProviderProtocolError):
    """提供商拒绝回答；不能转成成功的 finish。"""


def positive_int(value: Any, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} 必须是正整数。")


def token_count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


class OpenAIResponsesModel:
    """一个实例只服务一个 run；API 原始历史与 Relay 教学消息分别保存。"""

    def __init__(self, client: Any, model: str, *, max_output_tokens: int = 1024):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model 必须是明确的非空模型 ID。")
        positive_int(max_output_tokens, "max_output_tokens")
        self.client = client
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.call_records: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []
        self._seen: list[dict[str, Any]] = []
        self._pending_call_id: str | None = None
        self._last_action: dict[str, Any] | None = None

    def _input(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self._seen:
            if [m.get("role") for m in messages] != ["system", "user"]:
                raise ProviderProtocolError("首轮必须是 system 与 user 消息。")
            return copy.deepcopy(messages)
        if (
            not self._pending_call_id
            or len(messages) != len(self._seen) + 2
            or messages[: len(self._seen)] != self._seen
        ):
            raise ProviderProtocolError("适配器只能接收同一 run 的追加消息。")
        call, observation = messages[-2:]
        action = {k: v for k, v in call.items() if k not in {"role", "tool_call_id"}}
        if (
            call.get("role") != "assistant"
            or action != self._last_action
            or observation.get("role") != "tool"
            or not isinstance(call.get("tool_call_id"), str)
            or call["tool_call_id"] != observation.get("tool_call_id")
            or not isinstance(observation.get("content"), str)
        ):
            raise ProviderProtocolError("工具结果没有与上一轮请求配对。")
        return [
            *copy.deepcopy(self._history),
            {
                "type": "function_call_output",
                "call_id": self._pending_call_id,
                "output": observation["content"],
            },
        ]

    def generate(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        api_input = self._input(messages)
        api_tools = []
        for tool in tools:
            parameters = copy.deepcopy(tool["parameters"])
            # strict 模式要求所有 properties 出现在 required 中。
            # 因而模型显式提供 start_line=1，本地工具仍保留默认值。
            parameters["required"] = list(parameters["properties"])
            api_tools.append({"type": "function", **tool, "parameters": parameters, "strict": True})

        record = {
            "call_index": len(self.call_records) + 1,
            "provider": "openai",
            "model_requested": self.model,
            "model_returned": None,
            "max_output_tokens": self.max_output_tokens,
            "response_id": None,
            "status": "requesting",
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cached_input_tokens": None,
            "reasoning_output_tokens": None,
            "usage_status": "unknown",
            "cost_usd": None,
        }
        self.call_records.append(record)
        try:
            response = self.client.responses.create(
                model=self.model,
                input=api_input,
                tools=api_tools,
                parallel_tool_calls=False,
                max_output_tokens=self.max_output_tokens,
                store=False,
                include=["reasoning.encrypted_content"],
            )
            data = response.model_dump(mode="json", exclude_none=True)
        except Exception as exc:
            record.update(status="request_error", error_type=type(exc).__name__)
            raise

        record.update(
            response_id=data.get("id"), status=data.get("status"),
            model_returned=data.get("model"),
        )
        usage = data.get("usage") or {}
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            record[field] = token_count(usage.get(field))
        record["cached_input_tokens"] = token_count(
            (usage.get("input_tokens_details") or {}).get("cached_tokens")
        )
        record["reasoning_output_tokens"] = token_count(
            (usage.get("output_tokens_details") or {}).get("reasoning_tokens")
        )
        if all(record[k] is not None for k in ("input_tokens", "output_tokens", "total_tokens")):
            record["usage_status"] = "reported"
        if data.get("status") != "completed":
            raise IncompleteResponse("响应没有完成，不分发其中的工具。")

        output = data.get("output", [])
        if not isinstance(output, list) or any(not isinstance(item, dict) for item in output):
            raise ProviderProtocolError("output 必须是输出项列表。")
        if any(item.get("status") in {"in_progress", "incomplete"} for item in output):
            raise IncompleteResponse("输出项没有完成，不分发其中的工具。")
        if any(item.get("type") not in {"reasoning", "function_call", "message"} for item in output):
            raise ProviderProtocolError("当前只支持文本与专用函数工具。")
        calls = [item for item in output if item.get("type") == "function_call"]
        parts = [part for item in output if item.get("type") == "message"
                 for part in item.get("content", [])]
        if any(part.get("type") == "refusal" for part in parts):
            raise RefusedResponse("模型拒绝回答。")
        if len(calls) > 1:
            raise ProviderProtocolError("每轮只允许一个工具请求。")
        if calls:
            call = calls[0]
            if not isinstance(call.get("call_id"), str) or not call["call_id"]:
                raise ProviderProtocolError("缺少提供商 call_id。")
            try:
                arguments = json.loads(call["arguments"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderProtocolError("工具参数不是有效 JSON。") from exc
            if not isinstance(arguments, dict) or not isinstance(call.get("name"), str):
                raise ProviderProtocolError("工具请求必须包含名称和参数对象。")
            action = {"type": "tool_call", "name": call["name"], "arguments": arguments}
            self._pending_call_id = call["call_id"]
        else:
            text = "".join(part["text"] for part in parts if part.get("type") == "output_text")
            if not text.strip():
                raise ProviderProtocolError("响应既没有工具请求，也没有回答。")
            action = {"type": "finish", "content": text}
            self._pending_call_id = None

        # 保留全部 output，包括 reasoning 和 function_call 原始项。
        self._history = [*api_input, *copy.deepcopy(output)]
        self._seen = copy.deepcopy(messages)
        self._last_action = copy.deepcopy(action)
        return action

    def close(self) -> None:
        self.client.close()


def create_openai_model(
    model: str, *, max_output_tokens: int = 1024, timeout: float = 30.0
) -> OpenAIResponsesModel:
    """只在显式 ask 命令中加载 SDK；不记录或自动加载密钥文件。"""
    if not isinstance(model, str) or not model.strip():
        raise ValueError("必须指定 --model。")
    positive_int(max_output_tokens, "max_output_tokens")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout 必须是有限正数。")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key.strip():
        raise ValueError("未设置 OPENAI_API_KEY；请在本地环境中配置。")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ValueError("请先运行 uv sync --frozen --extra openai。") from exc
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.openai.com/v1",
        timeout=timeout,
        max_retries=0,
    )
    return OpenAIResponsesModel(client, model, max_output_tokens=max_output_tokens)
