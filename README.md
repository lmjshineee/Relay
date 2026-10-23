# Relay

从一个能运行的小循环开始，学习 coding agent 如何调用工具，逐步构建可恢复、成本可追溯的 Coding Agent Runtime。

Relay starts with a small tool-calling loop for learning agent development. An optional OpenAI Responses adapter is tested offline; live model behavior, recovery, and code repair remain unverified or planned.

**当前状态：第二批，Responses 适配层已实现并离线验证。** `demo` 继续使用预写脚本；`ask` 是显式真实调用入口，尚未试跑真实模型。完整 runtime 仍处于设计阶段；详细状态见 [实现进度](docs/08-project-status.md)。

### 1. 快速开始

需要 Git 和 Python 3.11+。当前演示不需要 API key、Docker 或第三方运行依赖。直接从源码运行：

```bash
git clone https://github.com/lmjshineee/Relay.git
cd Relay
python3 -m relay demo
python3 -m unittest discover -s tests -v
python3 scripts/check_docs.py
```

Windows 可将 `python3` 换成对应的 Python 命令。当前无 SDK 本地验证环境为 macOS、Python 3.14.9；CI 配置在 Linux 上检查 Python 3.11 与 3.14，实际结果以仓库 Actions 为准。

第二批可选 SDK 的安装、离线验证与真实调用入口：

```bash
uv sync --frozen --extra openai
uv run --frozen --extra openai python -m unittest discover -s tests -v
uv run --frozen --extra openai python -m relay ask --help
```

共 29 项测试；安装 SDK 后全部运行，未安装时 3 项 SDK 测试明确跳过。普通检查使用模拟客户端，不请求收费 API。`ask` 的实际运行会发送工作区读取结果并产生费用，需要本地 `OPENAI_API_KEY` 和明确的 `--model`；详见 [第二批学习指南](docs/10-second-batch-responses.md)。

演示读取 `examples/read-only/issue.md` 和 `calculator.py`，返回 JSON。关键字段如下，完整输出还包含对话与工具结果：

```json
{
  "schema_version": 1,
  "status": "completed",
  "model_calls": 3,
  "answer": "预写演示结论……",
  "verification": "not_run"
}
```

`completed` 只表示对话结束；`not_run` 表示没有独立验收；`model_calls` 是脚本响应次数，真实 API 请求为零。示例里的平均数缺陷故意保留。工具错误也可能出现在一段最终结束的对话中，检查具体 `events`，不要只看结束状态。

试着让循环提前停止：

```bash
python3 -m relay demo --max-steps 1
```

预期 `status: step_limit`、`answer: null`，退出码为 1。完整参数、状态和错误含义见 [CLI 与工具参考](docs/09-cli-and-tools.md)。

### 2. 现在有哪些能力

| 已实现并测试 | 后续计划 |
|---|---|
| `read_file` 及参数、路径、大小检查 | 真实模型行为与用量的实测、费用账本 |
| 工具请求、观察回传、对话配对 | 文件修改、命令执行与执行隔离 |
| 步数限制、错误分类和 JSON 轨迹 | 候选补丁与独立验收 |
| Responses 适配器、可选 SDK 与 29 项测试 | SQLite 事件、Worker、检查点与恢复 |

路径检查适用于静态本地 fixture，不是操作系统沙箱；当前没有跨运行持久化或自动恢复。

### 3. 怎样用这个项目学习

1. 运行演示，找到同一个 `tool_call_id` 对应的请求和结果。
2. 按 [`tools.py`](relay/tools.py) → [`models.py`](relay/models.py) → [`loop.py`](relay/loop.py) 的顺序阅读，解释模型与 Python 各做了什么。
3. 完成 [第一批学习指南](docs/06-first-batch-learning.md) 中的四个实验，先预测再观察。
4. 需要课程补充时参考 [CS146S 学习搭配](docs/07-cs146s-learning-route.md)。
5. 继续读 [第二批学习指南](docs/10-second-batch-responses.md)，理解 API 原始上下文与本地工具观察如何配对。

### 4. 项目结构

```text
relay/          工具、模型边界、循环和命令入口
examples/       只读教学 fixture，含故意保留的缺陷
tests/          工具边界、消息回传、停止与 CLI 行为测试
scripts/        文档链接和代码围栏检查
docs/           学习指南、当前状态、完整 runtime 设计
.github/        持续集成配置
```

### 5. 文档导航

1. [开发方案](docs/01-development-plan.md)：项目目标、范围、架构、技术选择和阶段验收。
2. [运行时设计规范](docs/02-runtime-spec.md)：状态机、持久化、动作恢复、检查点、上下文和预算。
3. [开发实施指南](docs/03-implementation-guide.md)：目录、接口、纵向开发切片、日常工作流程。
4. [工程与评测规范](docs/04-engineering-and-evaluation.md)：必须遵守的约束、故障矩阵、实验协议和交付标准。
5. [设计依据与待定决策](docs/05-decisions-and-sources.md)：原对话需求、默认决策、参考资料和未验证假设。
6. [第一批学习指南](docs/06-first-batch-learning.md)：代码阅读与动手实验。
7. [CS146S 学习搭配](docs/07-cs146s-learning-route.md)：课程参考与项目练习。
8. [实现进度](docs/08-project-status.md)：已有能力、验证证据与下一步。
9. [CLI 与工具参考](docs/09-cli-and-tools.md)：参数、消息格式、错误和结果解释。
10. [第二批学习指南](docs/10-second-batch-responses.md)：Responses 适配、用量记录与 SDK 离线测试。

文档 01–05 主要定义未来完整 runtime。实际可执行命令以本 README 和 CLI 参考为准，`relay run/resume/evaluate` 等仍是待实现契约。

### 6. 后续方向与参与

下一步选择具体模型与费用上限，显式试跑 Responses，检验模型能否根据工具观察调整动作。之后完成代码修复与独立验收，再增加持久化、动作对账、检查点和上下文实验。长期研究问题是恢复和上下文策略对成功率、费用与延迟的影响，当前没有相关性能结论。

开发检查与问题反馈见 [贡献指南](CONTRIBUTING.md)，每批变更见 [更新记录](CHANGELOG.md)。
