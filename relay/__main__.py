"""运行方式：在项目根目录执行 python3 -m relay demo。"""

import argparse
import json
import sys
from pathlib import Path

from relay.loop import run, validate_run_config
from relay.models import demo_model
from relay.openai_model import create_openai_model


def main() -> int:
    parser = argparse.ArgumentParser(description="Relay 工具调用学习循环")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workspace", type=Path, default=Path("examples/read-only"))
    common.add_argument("--max-steps", type=int, default=5)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", parents=[common], help="预写脚本演示，不请求 API")
    ask = commands.add_parser("ask", parents=[common], help="显式请求 OpenAI API，会产生费用")
    ask.add_argument("--model", required=True, help="可用的确切模型 ID，不设默认值")
    ask.add_argument("--task", default="阅读 issue.md 和 calculator.py，指出需要检查的问题。")
    ask.add_argument("--max-output-tokens", type=int, default=1024)
    ask.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    model = None
    try:
        validate_run_config(args.workspace, args.max_steps)
        model = (
            demo_model() if args.command == "demo" else create_openai_model(
                args.model, max_output_tokens=args.max_output_tokens, timeout=args.timeout
            )
        )
        result = run(
            model, args.workspace,
            "阅读 issue.md 和 calculator.py，指出需要检查的问题。"
            if args.command == "demo" else args.task,
            max_steps=args.max_steps,
        )
    except ValueError as exc:
        parser.error(str(exc))
    finally:
        if args.command == "ask" and model is not None:
            model.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
