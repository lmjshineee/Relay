import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from relay.loop import run
from relay.models import ScriptedModel, demo_model


def read(path):
    return {"type": "tool_call", "name": "read_file", "arguments": {"path": path}}


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "note.txt").write_text("hello", encoding="utf-8")

    def test_next_model_request_sees_matching_tool_result(self):
        observed = []

        class ObservingModel:
            def generate(self, messages, tools):
                if len(messages) == 2:
                    observed.append(tools[0]["name"])
                    return read("note.txt")
                call, result = messages[-2:]
                observed.append((call["tool_call_id"], result["tool_call_id"]))
                content = json.loads(result["content"])["content"]
                return {"type": "finish", "content": content}

        result = run(ObservingModel(), self.root, "Read note")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["answer"], "hello")
        self.assertEqual(result["verification"], "not_run")
        self.assertEqual(observed, ["read_file", ("call-1", "call-1")])

    def test_tool_error_is_observed_and_next_action_can_run(self):
        model = ScriptedModel([
            read("missing.txt"), read("note.txt"), {"type": "finish", "content": "done"}
        ])
        result = run(model, self.root, "Read note")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["events"][0]["result"]["error"]["code"], "not_found")
        self.assertEqual(result["events"][1]["result"]["content"], "hello")

    def test_step_limit_stops_before_requesting_another_response(self):
        model = ScriptedModel([read("note.txt"), {"type": "finish", "content": "late"}])
        result = run(model, self.root, "Read note", max_steps=1)
        self.assertEqual(result["status"], "step_limit")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["model_calls"], 1)
        self.assertEqual(next(model.responses)["content"], "late")

    def test_invalid_response_does_not_dispatch_tools(self):
        for response in (None, {}, {"type": "finish", "content": 2},
                         {**read("note.txt"), "extra": True}):
            with self.subTest(response=response):
                result = run(ScriptedModel([response]), self.root, "task")
                self.assertEqual(result["status"], "invalid_response")
                self.assertEqual(len(result["messages"]), 2)

    def test_model_exception_ends_run_and_omits_exception_text(self):
        class FailingModel:
            def generate(self, messages, tools):
                raise ConnectionError("potentially private provider response")

        result = run(FailingModel(), self.root, "task")
        self.assertEqual(result["status"], "model_error")
        self.assertEqual(result["model_calls"], 1)
        self.assertNotIn("private provider", json.dumps(result))

    def test_invalid_config_fails_before_model_call(self):
        for steps in (0, -1, True):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                run(ScriptedModel([]), self.root, "task", max_steps=steps)
        with self.assertRaises(ValueError):
            run(ScriptedModel([]), self.root / "missing", "task")

    def test_demo_is_read_only_and_reports_unverified_completion(self):
        workspace = Path(__file__).resolve().parents[1] / "examples" / "read-only"
        before = {p.name: p.read_bytes() for p in workspace.iterdir()}
        result = run(demo_model(), workspace, "demo")
        after = {p.name: p.read_bytes() for p in workspace.iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(result["model_calls"], 3)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["verification"], "not_run")

    def test_cli_json_and_exit_codes(self):
        project = Path(__file__).resolve().parents[1]
        for extra, expected_code in (([], 0), (["--max-steps", "1"], 1),
                                     (["--max-steps", "0"], 2)):
            with self.subTest(extra=extra):
                process = subprocess.run(
                    [sys.executable, "-m", "relay", "demo", *extra],
                    cwd=project, capture_output=True, text=True, check=False,
                )
                self.assertEqual(process.returncode, expected_code, process.stderr)
                if expected_code != 2:
                    self.assertEqual(json.loads(process.stdout)["schema_version"], 1)
                else:
                    self.assertEqual(process.stdout, "")


if __name__ == "__main__":
    unittest.main()
