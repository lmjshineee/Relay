"""通过内存 HTTP transport 测试真实 SDK；不连接任何外部地址。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from relay.loop import run
from relay.openai_model import OpenAIResponsesModel, create_openai_model

try:
    import httpx2
    from openai import OpenAI
except ImportError:
    httpx2 = None
    OpenAI = None


@unittest.skipIf(OpenAI is None, "可选 SDK 未安装；用 uv sync --frozen --extra openai 启用")
class OpenAISDKTests(unittest.TestCase):
    def test_sdk_serializes_tool_result_and_parses_response_without_network(self):
        requests = []

        def transport(request):
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 1:
                output = [{"type": "function_call", "id": "fc-sdk", "call_id": "sdk-call",
                           "name": "read_file", "arguments": '{"path":"note.txt","start_line":1}'}]
            else:
                observed = json.loads(body["input"][-1]["output"])["content"]
                output = [{"type": "message", "id": "msg-sdk", "role": "assistant",
                           "status": "completed", "content": [{"type": "output_text",
                           "text": observed, "annotations": []}]}]
            return httpx2.Response(200, json={
                "id": "resp-sdk", "object": "response", "created_at": 1,
                "model": "test-model", "status": "completed", "output": output,
                "parallel_tool_calls": False, "tools": body["tools"], "tool_choice": "auto",
                "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14,
                          "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens_details": {"reasoning_tokens": 0}},
            })

        with tempfile.TemporaryDirectory() as temp, httpx2.Client(
            transport=httpx2.MockTransport(transport), trust_env=False
        ) as http_client, OpenAI(api_key="test-only", http_client=http_client, max_retries=0) as client:
            (Path(temp) / "note.txt").write_text("from SDK transport", encoding="utf-8")
            result = run(OpenAIResponsesModel(client, "test-model"), Path(temp), "read")
        self.assertEqual(result["answer"], "from SDK transport")
        self.assertEqual(requests[1]["input"][-1]["call_id"], "sdk-call")
        self.assertEqual(len(requests), 2)
        self.assertEqual(result["provider_calls"][0]["total_tokens"], 14)

    def test_factory_disables_sdk_retries_and_pins_official_endpoint(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}):
            model = create_openai_model("test-model")
        try:
            self.assertEqual(model.client.max_retries, 0)
            self.assertEqual(str(model.client.base_url), "https://api.openai.com/v1/")
        finally:
            model.close()

    def test_sdk_timeout_is_one_attempt_with_unknown_usage(self):
        requests = []

        def transport(request):
            requests.append(request)
            raise httpx2.ReadTimeout("private", request=request)

        with httpx2.Client(transport=httpx2.MockTransport(transport), trust_env=False) as http_client, \
             OpenAI(api_key="test-only", http_client=http_client, max_retries=0) as client:
            result = run(OpenAIResponsesModel(client, "test-model"), Path.cwd(), "read")
        self.assertEqual(len(requests), 1)
        self.assertEqual(result["status"], "model_error")
        self.assertEqual(result["provider_calls"][0]["usage_status"], "unknown")


if __name__ == "__main__":
    unittest.main()
