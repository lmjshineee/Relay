import tempfile
import unittest
from pathlib import Path

from relay.tools import MAX_FILE_BYTES, execute_tool


class ReadFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "note.txt").write_text("第一行\nsecond\nthird\n", encoding="utf-8")

    def read(self, **arguments):
        return execute_tool(self.root, "read_file", arguments)

    def test_reads_utf8_without_changing_file(self):
        before = (self.root / "note.txt").read_bytes()
        result = self.read(path="note.txt", start_line=2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["content"], "second\nthird\n")
        self.assertEqual(result["lines_returned"], 2)
        self.assertFalse(result["has_more"])
        self.assertEqual((self.root / "note.txt").read_bytes(), before)

    def test_pagination_can_retrieve_remaining_lines(self):
        (self.root / "long.txt").write_text("x\n" * 201, encoding="utf-8")
        first = self.read(path="long.txt")
        second = self.read(path="long.txt", start_line=201)
        self.assertEqual(first["lines_returned"], 200)
        self.assertTrue(first["has_more"])
        self.assertEqual(second["content"], "x\n")
        self.assertFalse(second["has_more"])

    def test_empty_file_and_start_past_eof(self):
        (self.root / "empty.txt").touch()
        for arguments in ({"path": "empty.txt"}, {"path": "note.txt", "start_line": 99}):
            with self.subTest(arguments=arguments):
                result = self.read(**arguments)
                self.assertTrue(result["ok"])
                self.assertEqual(result["content"], "")
                self.assertEqual(result["lines_returned"], 0)

    def test_missing_and_directory_are_errors(self):
        self.assertEqual(self.read(path="missing")["error"]["code"], "not_found")
        self.assertEqual(self.read(path=".")["error"]["code"], "not_a_file")

    def test_invalid_arguments_are_rejected(self):
        for arguments in (
            {}, {"path": ""}, {"path": 3}, {"path": "note.txt", "extra": 1},
            *({"path": "note.txt", "start_line": value} for value in (True, 0, -1, "1", 1.5)),
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.read(**arguments)["error"]["code"], "invalid_arguments")
        self.assertEqual(
            execute_tool(self.root, "read_file", "note.txt")["error"]["code"],
            "invalid_arguments",
        )

    def test_unknown_tool_cannot_execute(self):
        result = execute_tool(self.root, "shell", {"command": "touch unexpected"})
        self.assertEqual(result["error"]["code"], "unknown_tool")
        self.assertFalse((self.root / "unexpected").exists())

    def test_traversal_absolute_and_sibling_prefix_are_rejected(self):
        for path in ("../outside.txt", str(self.root / "note.txt"), f"../{self.root.name}-other/file"):
            with self.subTest(path=path):
                self.assertEqual(self.read(path=path)["error"]["code"], "outside_workspace")

    def test_symlink_outside_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / "secret.txt"
            secret.write_text("outside data", encoding="utf-8")
            (self.root / "link").symlink_to(secret)
            result = self.read(path="link")
            self.assertEqual(result["error"]["code"], "outside_workspace")
            self.assertNotIn("outside data", str(result))

    def test_large_and_non_utf8_files_are_rejected(self):
        (self.root / "large").write_bytes(b"a" * (MAX_FILE_BYTES + 1))
        (self.root / "binary").write_bytes(b"\xff\xfe")
        self.assertEqual(self.read(path="large")["error"]["code"], "file_too_large")
        self.assertEqual(self.read(path="binary")["error"]["code"], "invalid_utf8")


if __name__ == "__main__":
    unittest.main()
