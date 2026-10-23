"""运行方式：在项目根目录执行 python3 -m relay demo。"""

import argparse
import json
import sys
from pathlib import Path

from relay.loop import run
from relay.models import demo_model


def main() -> int:
    parser = argparse.ArgumentParser(description="Relay 离线工具调用教学演示")
    parser.add_argument("command", choices=["demo"])
    parser.add_argument("--workspace", type=Path, default=Path("examples/read-only"))
    parser.add_argument("--max-steps", type=int, default=5)
    args = parser.parse_args()
    try:
        result = run(
            demo_model(), args.workspace,
            "阅读 issue.md 和 calculator.py，指出需要检查的问题。",
            max_steps=args.max_steps,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
