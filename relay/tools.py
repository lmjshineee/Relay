"""工具由 Python 执行。模型只能提出名称与参数。"""

from pathlib import Path
from typing import Any


READ_FILE_TOOL = {
    "name": "read_file",
    "description": "读取工作区中的 UTF-8 文本，可指定起始行，最多返回 200 行。",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "start_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}
MAX_FILE_BYTES = 64 * 1024
MAX_LINES = 200


def failure(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def execute_tool(workspace: Path, name: str, arguments: Any) -> dict[str, Any]:
    """验证工具名、参数、路径边界，再执行；schema 本身不会强制权限。"""
    if name != "read_file":
        return failure("unknown_tool", "可用工具只有 read_file。")
    if not isinstance(arguments, dict):
        return failure("invalid_arguments", "参数必须是 JSON 对象。")
    if set(arguments) - {"path", "start_line"}:
        return failure("invalid_arguments", "出现未声明的参数。")
    path = arguments.get("path")
    start_line = arguments.get("start_line", 1)
    if not isinstance(path, str) or not path.strip():
        return failure("invalid_arguments", "path 必须是非空字符串。")
    # bool 是 Python int 的子类，但不是工具协议中的整数。
    if type(start_line) is not int or start_line < 1:
        return failure("invalid_arguments", "start_line 必须是正整数。")
    if Path(path).is_absolute():
        return failure("outside_workspace", "path 必须是工作区相对路径。")
    try:
        root = workspace.resolve(strict=True)
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            return failure("outside_workspace", "路径或符号链接指向工作区外。")
        if not target.exists():
            return failure("not_found", "文件不存在。")
        if not target.is_file():
            return failure("not_a_file", "目标不是普通文件。")
        with target.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            return failure("file_too_large", "教学版只读取不超过 64 KiB 的文件。")
        lines = raw.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return failure("invalid_utf8", "文件不是有效 UTF-8 文本。")
    except (OSError, ValueError, RuntimeError):
        return failure("read_error", "无法读取文件或解析路径。")

    selected = lines[start_line - 1 : start_line - 1 + MAX_LINES]
    return {
        "ok": True,
        "path": path,
        "start_line": start_line,
        "lines_returned": len(selected),
        "has_more": start_line - 1 + len(selected) < len(lines),
        "content": "".join(selected),
    }
