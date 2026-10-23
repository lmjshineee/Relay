# CLI 与工具参考

适用于当前 0.2.0 教学代码。所有命令从仓库根目录执行。

### 1. 命令行

```bash
python3 -m relay demo --help
python3 -m relay demo
python3 -m relay demo --workspace examples/read-only --max-steps 5
```

| 参数 | 默认值 | 含义 |
|---|---|---|
| `demo` / `ask` | 必选一个 | 离线脚本 / 显式 OpenAI Responses 调用 |
| `--workspace` | `examples/read-only` | 已存在的目录；相对路径以进程运行目录解析 |
| `--max-steps` | `5` | 正整数，每轮调用一次 `generate`，最多执行一个工具 |

`ask` 另外接受以下参数；需要安装 `openai` 可选依赖和本地 `OPENAI_API_KEY`：

| 参数 | 默认值 | 含义 |
|---|---|---|
| `--model` | 必填 | 确切模型 ID，不自动选择 |
| `--task` | 读取示例缺陷与代码 | 传给模型的任务描述 |
| `--max-output-tokens` | `1024` | 每次响应的输出 token 上限 |
| `--timeout` | `30` | SDK 网络超时秒数，须为有限正数 |

真实调用示例见 [第二批指南](10-second-batch-responses.md)。SDK 不自动重试；步数、输出上限和网络超时不等于严格美元预算。`ask` 尚未真实试跑。

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
| `provider_calls` | 0.2.0 新增，每次 API 尝试的状态与 token；脚本模型为空列表 |

`provider_calls` 保留请求模型、返回模型、响应 ID、输出上限、输入/输出/缓存/推理 token。`usage_status: reported` 表示 API 报出了输入、输出和总 token；细分项仍可能缺失。超时或缺少用量时为 unknown/null。`cost_usd` 当前始终为 null，不能当作零费用。报告不包含耗时、严格费用账本或恢复证明。`schema_version` 保持 1，本批只新增字段，不代表已有 schema 迁移机制。

### 3. 内部模型协议

`Model.generate(messages, tools)` 返回一个工具请求或结束响应：

```json
{"type": "tool_call", "name": "read_file", "arguments": {"path": "issue.md"}}
```

```json
{"type": "finish", "content": "回答文本"}
```

这不是提供商专属协议。Responses 适配器负责格式转换、网络请求和用量提取。当前每轮只支持一个工具请求；内部协议的未知响应类型、缺字段、额外字段和错误字段类型会终止为 `invalid_response`。提供商响应不完整、拒绝、多工具或无法解析时以 `model_error` 终止。工具名或工具参数的业务错误则作为观察回传，下一轮仍可继续。

### 4. `read_file`

参数 `path` 是非空的工作区相对路径，`start_line` 是从 1 开始的正整数，默认 1；不接受其他参数。绝对路径和解析后越过工作区边界的路径被拒绝。

成功返回 `ok`、`path`、`start_line`、`lines_returned`、`has_more` 和原始文本 `content`。最多读取 64 KiB 的文件，每次最多返回 200 行；`has_more` 为真时，可将 `start_line` 增加 `lines_returned` 继续读取。空文件或起始行超出末尾返回空文本，不报错。

失败返回：

```json
{"ok": false, "error": {"code": "not_found", "message": "文件不存在。"}}
```

错误码包括 `unknown_tool`、`invalid_arguments`、`outside_workspace`、`not_found`、`not_a_file`、`file_too_large`、`invalid_utf8` 和 `read_error`。其中 `unknown_tool` 由分发器产生。

路径校验不会隐藏工作区内部文件，也没有防止其他进程同时替换路径的系统级隔离。当前只将随仓库提供的静态 fixture 作为演示工作区；执行不可信代码的隔离是后续切片。
