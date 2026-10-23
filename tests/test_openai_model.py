import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from relay.__main__ import main
from relay.loop import run
from relay.openai_model import OpenAIResponsesModel, ProviderProtocolError, create_openai_model
from relay.tools import READ_FILE_TOOL


def response(output, **overrides):
    return {
        "id": "resp-test",
        "object": "response",
        "created_at": 1,
        "model": "test-model",
        "status": "completed",
        "output": output,
        "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25,
                  "input_tokens_details": {"cached_tokens": 3},
                  "output_tokens_details": {"reasoning_tokens": 2}},
        **overrides,
    }


def tool(path="note.txt", call_id="external-call"):
    return {"type": "function_call", "id": "fc-test", "call_id": call_id,
            "name": "read_file", "arguments": json.dumps({"path": path, "start_line": 1})}


def text(value="done"):
    return {"type": "message", "id": "msg-test", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": value, "annotations": []}]}


class FakeClient:
    def __init__(self, results):
        self.results = iter(results)
        self.requests = []
        self.responses = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(model_dump=lambda **kwargs: copy.deepcopy(result))

    def close(self):
        pass


class OpenAIModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "note.txt").write_text("observation", encoding="utf-8")

    def test_full_loop_preserves_output_items_and_maps_call_ids(self):
        reasoning = {"type": "reasoning", "id": "rs-test", "summary": [],
                     "encrypted_content": "opaque-test-context"}
        client = FakeClient([response([reasoning, tool()]), response([text("observed")])])
        model = OpenAIResponsesModel(client, "test-model", max_output_tokens=512)
        result = run(model, self.root, "read")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["answer"], "observed")
        self.assertEqual(result["verification"], "not_run")
        followup = client.requests[1]["input"]
        self.assertEqual(followup[2:4], [reasoning, tool()])
        self.assertEqual(followup[-1]["type"], "function_call_output")
        self.assertEqual(followup[-1]["call_id"], "external-call")
        self.assertEqual(json.loads(followup[-1]["output"])["content"], "observation")
        self.assertEqual(client.requests[0]["input"][0]["role"], "system")
        self.assertFalse(client.requests[0]["store"])
        self.assertFalse(client.requests[0]["parallel_tool_calls"])
        self.assertEqual(client.requests[0]["max_output_tokens"], 512)
        self.assertTrue(client.requests[0]["tools"][0]["strict"])
        self.assertEqual(client.requests[0]["tools"][0]["parameters"]["required"],
                         ["path", "start_line"])
        self.assertEqual(READ_FILE_TOOL["parameters"]["required"], ["path"])
        self.assertEqual(result["provider_calls"][0]["input_tokens"], 20)
        self.assertEqual(result["provider_calls"][0]["cached_input_tokens"], 3)
        self.assertEqual(result["provider_calls"][0]["reasoning_output_tokens"], 2)
        self.assertIsNone(result["provider_calls"][0]["cost_usd"])

    def test_three_turns_preserve_earlier_reasoning_and_observations(self):
        reasoning = {"type": "reasoning", "id": "rs-one", "summary": [], "encrypted_content": "x"}
        client = FakeClient([response([reasoning, tool("missing", "one")]),
                             response([tool("note.txt", "two")]), response([text()])])
        result = run(OpenAIResponsesModel(client, "test-model"), self.root, "read")
        history = client.requests[2]["input"]
        self.assertIn(reasoning, history)
        observations = [item for item in history if item.get("type") == "function_call_output"]
        self.assertEqual([item["call_id"] for item in observations], ["one", "two"])
        self.assertEqual(json.loads(observations[0]["output"])["error"]["code"], "not_found")
        self.assertEqual(json.loads(observations[1]["output"])["content"], "observation")
        self.assertEqual(result["model_calls"], 3)

    def test_incomplete_refusal_multiple_calls_and_bad_json_never_dispatch(self):
        refusal = text()
        refusal["content"] = [{"type": "refusal", "refusal": "no"}]
        bad_call = {**tool(), "arguments": "{"}
        for payload, error in (
            (response([tool()], status="incomplete"), "IncompleteResponse"),
            (response([{**tool(), "status": "incomplete"}]), "IncompleteResponse"),
            (response([refusal, tool()]), "RefusedResponse"),
            (response([tool(), tool(call_id="second")]), "ProviderProtocolError"),
            (response([bad_call]), "ProviderProtocolError"),
            (response([]), "ProviderProtocolError"),
            (response([{"type": "web_search_call"}]), "ProviderProtocolError"),
        ):
            with self.subTest(error=error, payload=payload):
                result = run(OpenAIResponsesModel(FakeClient([payload]), "test-model"), self.root, "read")
                self.assertEqual(result["status"], "model_error")
                self.assertEqual(result["events"][0]["error_type"], error)
                self.assertEqual(len(result["messages"]), 2)
                self.assertEqual(len(result["provider_calls"]), 1)

    def test_missing_usage_and_timeout_remain_unknown(self):
        for result_or_error in (response([text()], usage=None), TimeoutError("private request")):
            with self.subTest(result=result_or_error):
                client = FakeClient([result_or_error])
                result = run(OpenAIResponsesModel(client, "test-model"), self.root, "read")
                record = result["provider_calls"][0]
                self.assertEqual(record["usage_status"], "unknown")
                self.assertIsNone(record["total_tokens"])
                self.assertIsNone(record["cost_usd"])
                self.assertNotIn("private request", json.dumps(result))
                self.assertEqual(len(client.requests), 1)

    def test_step_limit_sends_only_one_api_request(self):
        client = FakeClient([response([tool()]), response([text()])])
        result = run(OpenAIResponsesModel(client, "test-model"), self.root, "read", max_steps=1)
        self.assertEqual(result["status"], "step_limit")
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(len(result["provider_calls"]), 1)

    def test_reuse_or_mismatched_tool_history_is_rejected_before_request(self):
        initial = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
        for mismatched in (True, False):
            client = FakeClient([response([tool()])])
            model = OpenAIResponsesModel(client, "test-model")
            action = model.generate(initial, [READ_FILE_TOOL])
            messages = [*initial, {"role": "assistant", "tool_call_id": "one", **action},
                        {"role": "tool", "tool_call_id": "wrong", "content": "{}"}]
            with self.assertRaises(ProviderProtocolError):
                model.generate(messages if mismatched else initial, [READ_FILE_TOOL])
            self.assertEqual(len(client.requests), 1)

    def test_missing_key_and_bad_config_fail_without_network(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            create_openai_model("test-model")
        for kwargs in ({"model": ""}, {"model": "x", "max_output_tokens": 0},
                       {"model": "x", "timeout": float("nan")}, {"model": "x", "timeout": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                create_openai_model(**kwargs)

    def test_cli_rejects_bad_run_config_before_constructing_client(self):
        for extra in (["--max-steps", "0"], ["--workspace", str(self.root / "absent")]):
            with self.subTest(extra=extra), patch("sys.argv", ["relay", "ask", "--model", "x", *extra]), \
                 patch("relay.__main__.create_openai_model") as factory, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exit_info:
                    main()
                self.assertEqual(exit_info.exception.code, 2)
                factory.assert_not_called()

    def test_cli_ask_runs_injected_client_and_closes_it(self):
        model = OpenAIResponsesModel(FakeClient([response([text()])]), "test-model")
        output = io.StringIO()
        with patch("sys.argv", ["relay", "ask", "--model", "test-model"]), \
             patch("relay.__main__.create_openai_model", return_value=model), \
             patch.object(model, "close") as close, redirect_stdout(output):
            self.assertEqual(main(), 0)
        close.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())["provider_calls"][0]["provider"], "openai")


if __name__ == "__main__":
    unittest.main()
