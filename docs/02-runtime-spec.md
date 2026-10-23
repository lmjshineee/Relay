# Relay 运行时设计规范

版本：0.1；状态：待实现契约。本文中的“必须”是实现验收要求，“建议”是可通过 ADR 修改的默认选择。

### 1. 术语与标识

Task 是不可变任务定义；Run 是一次执行；Action 是一次逻辑工具动作；Attempt 是一次实际尝试；Event 是已提交事实；Artifact 是按内容哈希引用的文件；Checkpoint 是处于一致边界的工作区和运行状态引用。

`run_id` 全局唯一；`action_id` 在规划时生成并持久化，传输重试不得换 ID；`attempt_id` 标识实际尝试。相同 action ID 携带不同参数必须拒绝。显式重新执行生成新 attempt，回滚后重新规划生成新 action，并引用原动作。

`workspace_generation` 标识执行工作区代次；重建时递增。来自旧代次的迟到回执可以保留用于审计，但不得改变当前工作区状态。

### 2. 状态机

Run 的持久状态：

```text
CREATED → PREPARING → RUNNING → VERIFYING → SUCCEEDED | FAILED
PREPARING | RUNNING | VERIFYING → PAUSED | BLOCKED | CANCELLED | FAILED
PAUSED | BLOCKED → RECOVERING → PREPARING | RUNNING | VERIFYING | BLOCKED | FAILED
```

预算、步数或活动时间耗尽进入 PAUSED，并写明原因；不自动增加限额。用户明确取消进入 CANCELLED，清理完成前保存 `cancel_requested`。SUCCEEDED 只由独立验收通过产生。FAILED 区分候选补丁失败、基础设施故障、模型协议错误等原因。

状态字段与控制进程存活状态分开：进程被强杀时，数据库可能仍显示 RUNNING。inspect 必须同时显示 Controller 是否存活；resume 先获得进程锁，再写恢复事件。对终态运行的重新实验创建新的 run，保留原记录。

Action 状态：

```text
PLANNED → STARTED → SUCCEEDED | FAILED | UNKNOWN
PLANNED → CANCELLED
STARTED → CANCELLED（只有确认进程已终止时）
UNKNOWN → SUCCEEDED | FAILED | CANCELLED（取得可信回执）
UNKNOWN → RECONCILED（文件后置条件成立）
UNKNOWN → ABANDONED（显式回滚且旧进程已停止）
```

FAILED 表示已知执行结束及错误，不表示工作区没有变化。UNKNOWN 表示不能判断执行效果，不允许用普通重试覆盖。RECONCILED 仅证明后置条件成立，不伪造原退出码或 stdout；补给模型的观察必须标明“通过状态核对恢复”。

### 3. 持久化数据契约

| 表或记录 | 最少字段与约束 |
|---|---|
| runs | run_id、task/config hash、base_commit、image_digest、platform、state、reason、generation、created_at、schema_version |
| events | run_id、单调 seq、event_id、type、payload、schema_version、occurred_at、recorded_at；唯一 `(run_id, seq)` |
| actions | action_id、run_id、tool、args_hash、state、generation、checkpoint_before、effect_class |
| attempts | attempt_id、action_id、worker_id、execution_handle、receipt_ref、started_at、finished_at |
| model_calls | call_id、request_hash、provider_request_id、purpose、status、usage、price_version、reserved_cost、actual_cost |
| checkpoints | checkpoint_id、run_id、event_seq、manifest_hash、generation、format_version、status |
| artifacts | hash、size、media_type、relative_location、created_at |
| verifications | run_id、patch_hash、verifier_digest、environment、status、reason、log_ref |

状态转换、对应事件和相关投影更新必须在同一 SQLite 事务提交。外部模型请求、Docker 调用、文件复制不能放进长事务。序号由数据库事务分配，不能依赖墙钟排序。

事件为权威历史，actions/runs 是可重建投影；重建只处理事实，不执行工具。schema 迁移必须有版本和备份，旧事件由版本适配器读取，不能静默重写历史语义。

工件先写临时文件，计算哈希并同步落盘，再原子替换到最终路径，最后提交数据库引用；关键目录项按平台能力同步。崩溃后允许出现无引用工件，不允许已提交记录指向不完整工件。缺失或哈希不符时阻塞恢复并报告损坏。数据库使用 WAL、短事务与显式同步策略；MVP 默认 `synchronous=FULL`，仍只宣称经过测试的进程崩溃恢复边界，不宣称任意硬件故障下零丢失。

### 4. 动作执行协议

1. Controller 校验工具参数、预算、工作区代次，并在事务中写入 PLANNED 和动作意图。
2. Controller 把稳定 action ID、参数哈希、generation 传给独立 Worker。
3. Worker 在自己的持久 spool 中以 action ID 排他登记；已存在动作只返回既有状态，不重新执行。登记后、启动前也可能崩溃，此时必须对账，不能由重复请求擅自启动。
4. Worker 记录执行句柄，发布 STARTED 回执，然后执行。句柄至少包括容器 ID、Worker 启动身份、进程开始时间；不能只使用可能复用的 PID。
5. Worker 持续排空 stdout/stderr，执行超时和输出上限，完成后先持久化结果工件，再原子写最终回执。
6. Controller 导入回执，验证 ID、参数、代次和工件哈希，事务更新状态。重复导入无副作用，矛盾回执触发错误。

MVP 同一 run 只允许一个动作在途；同一工作区只允许一个写者。Controller 通过宿主机进程级排他锁防止双重 resume；Worker 自己维护动作排他登记。控制器锁的释放不代表旧 Worker 已停止，恢复前仍需对账。

### 5. 恢复决策

resume 首先验证配置、数据库和工件完整性，再核对 Worker、容器与动作回执；确认没有旧写者后才能写文件、回滚或建立新容器。

| 情况 | 必须采用的行为 |
|---|---|
| 最终回执已落盘，Controller 未导入 | 导入既有结果，不重复执行 |
| Worker 与动作仍运行 | 重新连接并等待，沿用原截止时间 |
| Worker 不在，但执行进程仍在 | 接管可验证句柄；不能接管则先终止并等待确认 |
| 读取工具未完成 | 确认 generation 和输入版本后可建立新 attempt |
| 专用文件替换没有回执 | 检查前/后哈希，按下述协议核对 |
| shell 执行效果不明 | 进入 UNKNOWN/BLOCKED；检查证据或显式回滚 |
| 已知失败但工作区发生变化 | 保存失败和变化；交给下一步规划，不默默重试 |
| 容器丢失 | 从最近完整 checkpoint 创建新 generation；只恢复声明覆盖的状态 |
| 模型请求返回前断连 | 保留未知计费；按预算策略决定是否创建新请求，不假装同一次响应可重现 |

专用文件写入 MVP 限制为单个普通文件，参数包含 relative_path、before_hash（不存在用显式标记）、after_hash、目标内容引用和模式位。执行前核对 before_hash，再在同目录临时写入并原子替换。恢复时：当前哈希等于 after_hash → RECONCILED；等于 before_hash 且确认原写者终止 → 可重试；二者都不同 → BLOCKED。删除动作以存在性和哈希核对。路径穿越、越界 symlink、特殊设备文件必须拒绝。

多文件修改按多个动作顺序进行，不宣称跨文件原子性。任意 shell、测试和编译均可能写文件；首版统一归入 `workspace_mutating`。只有专用 read/search 工具被实现与约束证明为只读时，才使用只读重试策略。

### 6. 检查点与回滚

快照必须在无在途写动作、所有受控子进程已退出的静止边界创建。测试产生的后台进程必须纳入清理；确认不了静止状态则快照失败。

manifest 覆盖声明的源码根目录下所有普通文件，包括未跟踪文件和默认被 Git 忽略的文件，记录路径、内容哈希、模式位、删除状态及允许的内部符号链接目标。排除 `.git`、运行时 spool、密钥、明确配置的构建缓存和虚拟环境；排除清单写入 manifest。恢复依赖被排除文件的任务必须调整覆盖范围或归为不支持，不能静默假设状态完整。

检查点还引用 base commit、镜像 digest、环境配置 hash、事件序号、上下文摘要引用和进度。快照不保存内存、存活进程、网络连接、外部数据库。

创建顺序为：停止写者 → 收集并校验文件 → 持久化所有 blob → 写 manifest → 事务提交 checkpoint。未提交快照不能作为恢复起点。恢复到新目录后核对完整 manifest，再切换 generation。

回滚只回滚工作区和 agent 的逻辑继续位置；历史事件、已发生的模型费用、失败动作和累计活动时间全部保留。追加 `workspace_rolled_back` 事件，标注废弃分支，使 ContextBuilder 不把已撤销写入当成当前事实。

MVP 对未知 shell 的默认处理为 BLOCKED。CLI 可以显式选择最近 checkpoint 回滚；只有事先配置并记录的 `rollback_on_unknown` 策略允许自动回滚。两者都必须先确认旧进程退出。

### 7. 模型调用与预算

Gateway 返回统一的模型输出、工具调用、结束原因、用量和延迟。每次请求发送前持久化 request hash 与费用预留；响应持久化成功后，才允许执行其中的工具调用。部分流响应不能用于执行工具。

预算准入条件为：`已结算费用 + 所有未结算预留 + 新请求保守上界 <= 限额`。新请求上界由输入计价与最大输出 token 计算；价格版本、币种、缓存计费口径和模型 ID 固定记录，金额使用 Decimal 或整数微单位。

模型超时可能已经计费。无法查询的调用保留 `usage_unknown` 和预留，不将其记为零；可以在保守预算仍足够时新建调用，报告中区分已知费用、预留上界和未知次数。无可靠价格/输出上界时，仅能承诺 token、步数和时间限制，不能承诺严格美元封顶。

重试、摘要和格式修复均属于收费请求；适配器关闭不可观测的 SDK 自动重试，或将其显式展开为可计数 attempt。仅对可重试的瞬时错误使用有上限的退避；鉴权、参数错误直接终止。每次重试再次检查预算和取消信号。

配置同时限制模型调用数、工具动作数、单动作超时和 run 累计活动时间。resume 不重置计数；离线停机时间单列，活动时间按已持久化时段累计。取消先停止新调度，再终止并回收受控进程，无法确认结束时保留未知动作。

### 8. 上下文契约

完整事件与模型可见上下文分离。持久层保留全部轨迹；每次构建记录 strategy/version、来源事件范围、摘要 hash、工件引用和最终请求 hash。

建议布局：稳定系统规则与工具定义 → 不变任务说明 → 版本化摘要 → 近期完整轮次 → 当前观察。可变时间戳不得进入固定前缀。前缀稳定只能作为策略意图，缓存命中与收益必须由观测确认。

| 策略 | 明确定义 |
|---|---|
| append | 保留历史直到输入预算不足，返回 context_limit；不偷偷启用摘要 |
| periodic | 每固定 N 个已完成轮次压缩旧的完整轮次，保留最近 K 轮 |
| threshold | 日志外置、稳定前缀；估算输入超过阈值才摘要，保留最近 K 轮 |

阈值、N、K、单次最大输出和输入安全余量写入实验配置。输入容量必须扣除输出预留和工具 schema 开销。所有策略共用相同工具能力与安全输出上限。

摘要包含任务约束、已验证事实、失败尝试、当前文件版本、未解决事项和引用事件。摘要不能覆盖原任务要求，不能覆盖当前真实文件状态。工具调用与结果作为完整单元处理，不留下孤立 tool message。被压缩的完整日志通过受限 `read_artifact` 按范围读取。

摘要失败时，若原上下文仍可容纳则继续使用原文，否则以 context_limit 暂停；不得静默丢弃信息。模型摘要自身也进入账本，其成本计入策略开销。

### 9. 补丁与独立验收

导出相对于 base commit 的补丁，必须包含新增、删除、模式变化和允许的二进制变化；不能仅依赖漏掉未跟踪文件的普通 diff。先在干净副本中验证可应用性和结果树 hash。

Verifier 使用独立容器，从固定基线应用候选补丁，随后加载不对 agent 暴露的验收测试。评分器和隐藏测试目录由宿主控制面维护，不能被候选补丁覆盖。任务公开测试与隐藏验收的权限边界应在 TaskSpec 中分开。

最终报告至少包含 `passed / failed / infrastructure_error / not_run`、退出码、超时原因、日志引用、patch hash 和 verifier 版本。Agent 声称完成只触发 VERIFYING；不直接写 SUCCEEDED。MVP 默认只进行一次最终隐藏验收，失败即记录终态，避免通过反复反馈泄露隐藏测试。

### 10. 回放与恢复

`replay` 只读取事件和工件，不调用模型、不执行工具、不改变工作区。`resume` 会继续真实执行，因此后续模型输出可以不同。二者使用独立命令和测试；文档不得把它们描述为确定性模型重现或任意 shell 的 exactly-once。
