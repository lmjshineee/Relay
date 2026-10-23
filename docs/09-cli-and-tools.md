# CLI 与工具参考

适用于当前 0.1.0 教学代码。所有命令从仓库根目录执行。

### 1. 命令行

```bash
python3 -m relay demo --help
python3 -m relay demo
python3 -m relay demo --workspace examples/read-only --max-steps 5
```

| 参数 | 默认值 | 含义 |
|---|---|---|
| `demo` | 必填 | 当前唯一子命令，使用脚本模型 |
| `--workspace` | `examples/read-only` | 已存在的目录；相对路径以进程运行目录解析 |
| `--max-steps` | `5` | 正整数，每轮调用一次 `generate`，最多执行一个工具 |

演示脚本始终请求 `issue.md` 和 `calculator.py`；换工作区不会改变脚本。缺少这些文件时工具返回 `not_found`，脚本仍可能给出预写结论，因此不能把演示结束当作文件读取或诊断成功。

stdout 输出一个 JSON 报告，配置错误写 stderr。退出码：0 表示 `completed`；1 表示步数限制、模型异常或响应格式错误；2 表示命令参数或工作区配置错误。CLI 不会自动写报告文件。

### 2. 报告

| 字段 | 含义 |
|---|---|
| `schema_version` | 当前报告版本为 `1` |
| `status` | `completed`、`step_limit`、`model_error` 或 `invalid_response` |
| `model_calls` | 已尝试的 `generate` 次数，包含异常轮次；脚本演示没有 API 调用 |
| `answer` | finish 的文本；其他终止状态为 `null` |
| `verification` | 当前固定为 `not_run` |
| `messages` | system / user / assistant / tool 对话，tool 的 `content` 是 JSON 字符串 |
| `events` | 工具结果、模型错误类型、格式错误或结束事件 |

报告不包含费用、token、耗时或恢复证明。`schema_version` 只描述当前教学格式，不代表已有 schema 迁移机制。

### 3. 内部模型协议

`Model.generate(messages, tools)` 返回一个工具请求或结束响应：

```json
{"type": "tool_call", "name": "read_file", "arguments": {"path": "issue.md"}}
```

```json
{"type": "finish", "content": "回答文本"}
```

这不是提供商专属协议。未来适配器负责格式转换、网络请求和用量提取。当前每轮只支持一个工具请求；未知响应类型、缺字段、额外字段和错误字段类型会终止为 `invalid_response`。工具名或工具参数的业务错误则作为观察回传，下一轮仍可继续。

### 4. `read_file`

参数 `path` 是非空的工作区相对路径，`start_line` 是从 1 开始的正整数，默认 1；不接受其他参数。绝对路径和解析后越过工作区边界的路径被拒绝。

成功返回 `ok`、`path`、`start_line`、`lines_returned`、`has_more` 和原始文本 `content`。最多读取 64 KiB 的文件，每次最多返回 200 行；`has_more` 为真时，可将 `start_line` 增加 `lines_returned` 继续读取。空文件或起始行超出末尾返回空文本，不报错。

失败返回：

```json
{"ok": false, "error": {"code": "not_found", "message": "文件不存在。"}}
```

错误码包括 `unknown_tool`、`invalid_arguments`、`outside_workspace`、`not_found`、`not_a_file`、`file_too_large`、`invalid_utf8` 和 `read_error`。其中 `unknown_tool` 由分发器产生。

路径校验不会隐藏工作区内部文件，也没有防止其他进程同时替换路径的系统级隔离。当前只将随仓库提供的静态 fixture 作为演示工作区；执行不可信代码的隔离是后续切片。
