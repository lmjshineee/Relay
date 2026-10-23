# 第二批：把脚本模型换成 Responses 适配器

本批提供 OpenAI Responses 适配代码，先通过离线测试学习协议转换。没有进行真实 LLM 调用，不能据此判断模型会不会选择正确的工具或修正错误。第一批脚本演示继续保留。

### 1. 这一层为什么需要存在

Relay 的循环只认识 `tool_call` 和 `finish`。OpenAI 返回的是一组输出项，可能同时包含 reasoning、function_call 和 message。适配器在两种格式之间转换；文件读取仍由原来的 Python 工具执行。

先读 [`openai_model.py`](../relay/openai_model.py) 的 `generate`，再看 `_input`，最后对照 [`test_openai_model.py`](../tests/test_openai_model.py)。核心过程是：

1. 首轮把 Relay 的 system、user 消息转交给 Responses。
2. 收到完整的函数调用后，将它转换成 Relay 的一个 `tool_call`。
3. 循环执行工具，把观察追加到 Relay 对话。
4. 适配器将该观察变成 `function_call_output`，用提供商原始 `call_id` 配对，并带上此前全部原始输出项。
5. 下一轮若收到文本回答，转换成 `finish`；不完整、拒绝或超出当前协议的响应会终止。

Relay 使用 `call-1` 等 ID 关联自己的消息；API 有自己的 `call_id`。两者不必相同。测试故意使用不同的 ID，确保适配器做了正确映射。

### 2. 为什么保留两份历史

Relay 的 `messages` 用来展示本地动作和工具观察。适配器内部的 `_history` 保留 API 原始输出，供下一轮回传，包括加密 reasoning 项。只保存用户看得见的回答文字，会丢掉 API 后续调用所需的上下文。

本批选择 `store=False`，手动回传原始历史，不依赖服务端 response 链。适配器实例只服务一个 run，检查历史是否按预期追加；它没有实现跨进程恢复。原始 API 上下文目前只在内存，报告中的教学消息不足以重新构建它。

### 3. 先跑不用密钥的检查

```bash
python3 -m unittest discover -s tests -v
uv sync --frozen --extra openai
uv run --frozen --extra openai python -m unittest discover -s tests -v
python3 scripts/check_docs.py
```

第一条不依赖 SDK：26 项通过、3 项 SDK 测试明确跳过。安装可选 SDK 后，29 项全部通过。锁文件当前固定 `openai==3.37.0` 及其依赖；Python SDK 测试通过内存 HTTP transport 走真实的序列化与解析流程，没有外网模型请求。

无 SDK 检查在本地 Python 3.14.9 验证；SDK 环境由 uv 使用 Python 3.14.3，29 项通过。Linux / Python 3.11、3.14 的无 SDK 与有 SDK 检查由 CI 执行，结果以该提交的 Actions 为准。

### 4. 做三个小实验

1. 看 `test_three_turns_preserve_earlier_reasoning_and_observations`。第一轮请求一个不存在的文件，第二轮读正确文件。解释第三次请求为何同时带着之前的 reasoning、错误结果与正确结果。这个顺序由模拟响应预写，不能证明真实模型会纠错。
2. 看不完整响应和多工具响应的测试。即使参数字符串看起来已经可解析，只要响应尚未完成，就不能据此分发工具。本切片一轮只接受一个工具。
3. 看 SDK 超时测试。解释为什么只记录一次请求，以及 `usage_status: unknown`、`cost_usd: null` 为什么不能理解成没有费用。

### 5. 真实调用入口，尚未试跑

先在本地环境配置 `OPENAI_API_KEY`，不要写进命令参数或提交到仓库。`ask` 必须显式给出你有权限使用的确切模型 ID；项目不选择默认模型，也不会自动读取 `.env`。

```bash
# 先在环境中设置 OPENAI_API_KEY 与 RELAY_MODEL；下面的命令会请求收费 API。
uv run --frozen --extra openai python -m relay ask \
  --model "$RELAY_MODEL" \
  --workspace examples/read-only \
  --task "阅读 issue.md 与 calculator.py，解释可能的问题，不要修改文件。" \
  --max-steps 3 --max-output-tokens 1024 --timeout 30
```

SDK 自动重试设为 0，步数控制请求次数，每次输出受 token 上限约束。`timeout` 是 SDK 网络超时，不是整个 run 的墙钟限额。这些限制不构成严格美元预算；当前没有价格表或费用预留算法，未知费用保持 `null`。真实试跑仍需先确定具体模型和费用上限。

### 6. 用量与下一步

报告新增 `provider_calls`，每次 API 尝试记录请求模型、返回模型、响应 ID、状态和可获得的 token 用量。缺失用量为 unknown/null；输出截断时仍保留已经返回的用量。报告格式在 `schema_version: 1` 上增加字段，旧字段含义保持不变。

下一步是显式小规模真实试跑：检查模型能否根据观察调整动作，再进入写入和独立验收设计。费用账本、恢复与完整 T06 仍未完成。

### 官方依据

核对日期：2026-10-23。[Function calling](https://developers.openai.com/api/docs/guides/function-calling) 用于核对函数定义、结果配对、strict schema 与关闭并行调用；[Reasoning models](https://developers.openai.com/api/docs/guides/reasoning) 用于核对原始输出项回传；[SDKs and CLI](https://developers.openai.com/api/docs/libraries) 用于核对官方 Python SDK 入口。本文实验与学习建议属于 Relay 实现说明。
