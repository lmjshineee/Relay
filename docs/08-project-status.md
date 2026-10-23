# 实现进度

更新日期：2026-10-23。这里记录实际能力；完整 runtime 的目标见 [开发方案](01-development-plan.md)。

### 1. 已交付的前置教学切片

| 组件 | 行为 | 验证入口 |
|---|---|---|
| `read_file` | UTF-8 文件读取、起始行、行数与字节上限 | `tests/test_tools.py` |
| 参数与路径检查 | 拒绝未知工具、错误参数、绝对路径、越界路径与指向外部的符号链接 | `tests/test_tools.py` |
| 循环 | 单轮一个请求，追加匹配的工具观察，结束或达到步数限制 | `tests/test_loop.py` |
| 错误处理 | 工具错误回传，模型异常和非法响应终止 | `tests/test_loop.py` |
| 命令行 | `python3 -m relay demo` 输出 JSON，区分正常、运行未完成和配置错误退出码 | `tests/test_loop.py` |
| 文档检查 | 检查本地 Markdown 链接和代码围栏 | `scripts/check_docs.py` |
| Responses 适配 | 原始上下文回传、双层 call ID 配对、单动作解析 | `tests/test_openai_model.py` |
| 请求用量 | 每次尝试保留 token 与未知用量；不估算费用 | `tests/test_openai_model.py` |
| 可选 SDK | 锁定依赖，真实 SDK 通过内存 HTTP transport 运行 | `tests/test_openai_sdk.py` |

演示使用固定脚本依次读取两个文件，再给出预写结论。测试中的观察模型根据实际工具返回生成回答，用于检查信息流；它也不是外部 LLM。

### 2. 验证与证据边界

第一批在 macOS / Python 3.14.9 的 17 项测试、干净 Git 副本和 Linux CI 已通过。第二批共 29 项测试：无 SDK 环境 Python 3.14.9 中 26 项通过、3 项明确跳过；SDK 环境 Python 3.14.3 中全部通过，包含 SDK 的内存 HTTP 协议测试。离线演示继续通过。GitHub CI 检查 Linux 上 Python 3.11 与 3.14 的无 SDK、有 SDK 环境，实际运行状态见对应提交的 Actions。

这些检查证明当前代码在对应环境中的行为。它们没有证明真实模型能修复代码，没有生成独立验收补丁，也没有测量费用、恢复正确率或性能收益。Python 其他版本、Windows 与 Linux 以实际检查记录为准。

### 3. 仍在计划中的能力

- Responses 的真实模型试跑、用量实测和费用核对；适配代码与用量字段已离线验证。
- 专用写入工具、受控命令、隔离工作区、候选补丁和独立验收。
- SQLite 事件与投影、独立 Worker、持久回执、检查点、恢复和回滚。
- 上下文策略、故障注入、冻结任务清单与正式评测。

当前 `messages` 和 `events` 是内存中的记录，JSON 可手动导出；没有数据库、run 排他锁或跨进程去重。`call-1` 只关联一次调用内的消息。当前切片没有完成 M0 或 T01，不将文档中的 `relay resume` 等计划命令算作现有功能。

### 4. 下一批验收目标

已按用户选择实现 OpenAI Responses 适配层。下一步确定具体模型和费用上限，至少观察一次正常读取和一次缺失路径反馈，记录模型是否据此调整动作；真实试跑显式启用，不让普通测试产生费用。第二批实现和练习见 [Responses 学习指南](10-second-batch-responses.md)。

完成这一小步后，再设计写入和代码修复闭环。M0–M5 的长期顺序仍以 [开发实施指南](03-implementation-guide.md) 为准。
