"""检查项目 Markdown 的本地文件链接和围栏；不请求外网。"""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    files = [root / name for name in ("README.md", "CONTRIBUTING.md", "CHANGELOG.md")]
    files.extend(sorted((root / "docs").glob("*.md")))
    errors = []
    for file in files:
        fence = None
        for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
            if match:
                marker = match[1]
                if fence is None:
                    fence = marker
                elif marker[0] == fence[0] and len(marker) >= len(fence):
                    fence = None
                continue
            if fence is not None:
                continue
            for link in re.finditer(r"\]\(([^)]+)\)", line):
                target = link[1].strip().strip("<>")
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                if not (file.parent / unquote(parsed.path)).exists():
                    errors.append(f"{file.relative_to(root)}:{number}: missing {target}")
        if fence is not None:
            errors.append(f"{file.relative_to(root)}: unclosed code fence")
    for error in errors:
        print(error)
    if not errors:
        print(f"PASS: {len(files)} Markdown files; local links and code fences")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
