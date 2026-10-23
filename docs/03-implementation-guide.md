# Relay 开发实施指南

状态：完整 runtime 的开发前指南。以下目录、接口和命令仍为计划；已落地的前置教学切片及实际命令见 [第一批学习指南](06-first-batch-learning.md)，不等同于 T01–T06 或 M0 已完成。

### 1. 按纵向切片推进

先让一次修复从输入走到独立验收，再逐步替换运行环节。每个切片应同时包含行为、验证和可检查产物，避免先搭建所有抽象接口却没有完整运行路径。

开始 M0 时验证 Python、依赖管理器、Docker daemon、容器 CPU 架构和可用磁盘。建立一个小型 Python fixture：给出缺陷描述和公开测试，另存一份隐藏验收。离线脚本模型固定输出读取、修改、测试和完成动作；这样无需 API 费用就能开发恢复协议。

### 2. 建议目录

```text
Relay/
  pyproject.toml
  uv.lock
  src/relay/
    cli.py
    domain/          # TaskSpec、Run、Action、Event、错误类型
    runtime/         # controller、状态转换、recovery、budget
    storage/         # SQLite、迁移、artifact、checkpoint
    models/          # gateway、provider adapter、scripted adapter
    context/         # append、periodic、threshold、消息校验
    execution/       # worker、receipt、process、docker、tools
    evaluation/      # task loader、verifier、suite、metrics
  tests/
    unit/
    integration/
    fault/
    e2e/
    fixtures/
  configs/           # 非敏感的版本化配置
  benchmarks/        # 固定 task ID 与镜像/资源清单
  scripts/           # 环境探测、演示、报告重算
  docs/
```

运行产物放在用户选定的本地 run 根目录，不写入源码树；默认可使用项目下被忽略的 `.relay/`。每个 run 包含 SQLite 引用、manifest、spool、工件、patch 和报告。共享内容寻址工件库需维护引用关系，首版不做自动垃圾回收。

domain 不依赖 Docker、CLI 或提供商 SDK；runtime 依赖协议；adapter 实现协议。避免通用插件系统、抽象工厂层级或分布式服务先行。

### 3. 先冻结最小接口

以下是语义草图，所有 Request/Result 类型在实现时用版本化模型定义；不直接复制成未定义类型的可运行代码。

```python
class ModelGateway(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResult: ...

class WorkerClient(Protocol):
    async def submit(self, action: ActionIntent) -> ActionHandle: ...
    async def inspect(self, handle: ActionHandle) -> ActionObservation: ...
    async def cancel(self, handle: ActionHandle) -> CancelResult: ...

class ContextStrategy(Protocol):
    async def build(self, source: ContextSource, limits: ContextLimits) -> ContextResult: ...

class Verifier(Protocol):
    async def verify(self, candidate: CandidatePatch, spec: VerificationSpec) -> VerificationResult: ...
```

Store 需提供原子的 `transition(expected_state, event, updates)`，而不是让业务代码依次调用“插入日志”和“更新状态”。Worker 的 submit 必须具备稳定 action ID 的重复提交语义。ContextStrategy 需要摘要时，应通过受预算管理的模型调用服务发起，不能自行绕过费用账本。

### 4. 配置与 CLI 契约

任务定义分成 agent 可见内容和控制面专用验收内容。下面仅展示字段；占位值不可直接用于执行。

```yaml
schema_version: 1
task_id: fixture-boundary-001
source:
  repo: /absolute/path/to/fixture
  commit: <full-commit-sha>
agent:
  issue_file: issue.md
  public_test_argv: [python, -m, pytest, tests/public]
environment:
  image: <image@sha256:digest>
  platform: linux/arm64
  cpus: 2
  memory_mb: 4096
  network: disabled
verification:
  spec_ref: <host-only-verifier-spec>
limits:
  max_model_calls: 40
  max_tool_actions: 80
  max_active_seconds: 1800
  max_action_seconds: 120
  budget_usd: "2.00"
```

上述资源和费用值是 fixture 的示例默认值，真实任务需试跑后调整。模型配置另存，包含 provider、精确模型标识、采样参数、最大输出、价格版本、prompt/策略版本及密钥环境变量名；不存密钥值。启动后冻结有效配置并保存 hash，resume 默认使用原配置。

```bash
# 设计中的命令，尚未实现
relay run --task tasks/fixture.yaml --config configs/dev.yaml
relay inspect <run-id> --json
relay resume <run-id>
relay resume <run-id> --rollback-to <checkpoint-id>
relay cancel <run-id>
relay replay <run-id>
relay evaluate --suite benchmarks/frozen.yaml --config configs/eval.yaml
relay report <suite-id> --output reports/result.json
```

`run --task` 以 TaskSpec 中的 repo/commit 为唯一来源，减少相互冲突的 CLI 参数。预算提升必须使用显式选项并写入事件；暂停后的默认 resume 不自动抬高限额。inspect/replay 不产生推理费用。CLI stdout 的 JSON 必须稳定可解析，诊断信息写 stderr。

退出码建议：0 成功；1 执行或验收失败；2 输入/配置错误；3 暂停或阻塞；130 用户中断。机器消费仍以报告中的结构化状态为准，不通过解析自然语言判断。

### 5. 可直接领取的开发切片

| ID | 依赖 | 工作内容 | 必须交付的验证 |
|---|---|---|---|
| T01 | 无 | Python 工程、锁文件、环境探测、TaskSpec | 缺少 Docker/错误 commit/架构不匹配有明确错误 |
| T02 | T01 | 容器与独立仓库、资源限制、命令执行 | 输出大于缓冲区不死锁；超时清理子进程；原仓库不变 |
| T03 | T01 | 领域模型、SQLite 事务、事件投影 | 状态与事件原子提交；重复事件不破坏投影 |
| T04 | T02,T03 | 脚本模型、最小 Controller、基础预算 | 一个 fixture 从读取到候选 patch，预算不足不发请求 |
| T05 | T04 | 导出补丁、干净环境验收、报告 | 新文件进入补丁；隐藏测试不能被候选覆盖 |
| T06 | T05 | 一个真实提供商适配器、费用账本 | 一个真实调用的用量能核对；断连用量标为未知 |
| T07 | T03,T04 | 独立 Worker、持久 spool、动作去重 | 杀掉 Controller 后 Worker 仍能落回执；重复 submit 不重做 |
| T08 | T07 | 专用文件写入、恢复对账、run 排他锁 | 写后回执前崩溃能核对；双 resume 被拒绝 |
| T09 | T08 | 静止检查点、回滚、generation | 新增/删除文件可恢复；旧 Worker 回执不能污染新工作区 |
| T10 | T06,T09 | 三种上下文策略、工件按需读 | 工具序列合法；摘要失败不丢原文；摘要费用计入 |
| T11 | T05,T09 | 故障注入与固定评测清单 | 可按注入位置重现故障；所有任务有终态或明确缺失原因 |
| T12 | T10,T11 | 消融、指标重算、演示与报告 | 清单与版本固定，报告能由原始记录重新生成 |

T03 与 T02 的实现可顺序安排，表中的无依赖只表示设计依赖，不要求启动多个开发 agent。

### 6. 每个切片的工作流程

1. 写清输入、输出、失败窗口和验收条件；改变状态或持久格式时先更新设计记录。
2. 用最小 fixture 实现端到端行为，先跑离线模型。
3. 对有副作用的代码注入真正的进程中断，确认恢复结果；不能只 mock 返回异常。
4. 完成必要的类型、格式、单元和集成检查，再进行与该切片有关的真实服务试跑。
5. 保存证据位置、命令、版本与结果；更新已实现状态和已知限制。

建议未来统一检查入口如下，具体在工程初始化时落地：

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest tests/unit tests/integration
uv run pytest tests/fault tests/e2e
```

Docker 测试需要显式环境；真实模型测试单独标记并显式启用，普通检查不得自动产生 API 费用。集成环境缺失时报告 skipped 和原因，不把跳过视为通过。

### 7. 调试与演示

调试记录统一采用“位置 → 原因 → 修复 → 验证”。先记录 run/action/attempt ID、generation、最后提交事件和 Worker 回执，再判断故障发生在模型、控制器、执行器还是验收环境。

最终演示使用固定 fixture、脚本模型和可重复故障注入点，证明恢复机制；另附真实模型修复案例证明实用性。两类证据分别报告。

演示步骤：启动 run → 到 `file_replaced_before_receipt` 注入点阻塞 → 强杀 Controller 和目标 Worker → resume → 通过文件后置条件恢复 → 生成 patch → 独立验收 → 查看完整账本。另做“Controller 死亡但 Worker 存活”案例，证明可重新导入回执。

注入点通过测试专用配置启用；正常用户命令不默认注入故障。演示脚本必须能重复执行并为每次演示生成新的 run ID。
