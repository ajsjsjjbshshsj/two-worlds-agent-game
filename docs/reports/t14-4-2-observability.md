# T14.4.2 · AI 可选观测适配器

基线为已包含 [PR #47](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/47) 的 `codex/bootstrap@0fba85a937317475c574a5d21ffabb093332a5f2`。本轮验收 QA-A07 的本地观测、隐私与游戏故障隔离边界。

## 已实现

- 复用 `NarrativeRun.record()` 和 Python 本地日志类别 `twoworlds.ai.graph`。日志级别允许 `INFO` 时，生成 `npc_workflow` 技术记录。禁用该级别时跳过投递。应用默认 Demo，外部观测始终禁用。
- 图在独立的 `Context` 中执行，图和 Provider 线程均明确关闭 LangSmith 追踪并断开追踪父节点。继承的 LangChain 回调无法获得 NPC 图输入。NPC HTTP 输运范围内屏蔽 HTTPX 和现有异步 HTTP core 原始日志，同一进程中其他输运的日志继续生效。
- 日志白名单仅包含随机 UUID4 `trace_id`、Prompt 版本、Provider 类型和名称、模型、耗时、调用次数、Fallback、固定错误分类、处理状态、可信 usage、价格版本与金额。耗时衡量模型工作流，预检拒绝时记录预检耗时。随机 ID 不取自账号、存档、业务请求、预算预留或会话，也不回写游戏。问题、回复、Prompt 内容、完整上下文、原始 HTTP 响应和异常均留在业务处理边界内。
- 游戏保存服务先决定命令结果，再投递本地记录。单个后台线程处理最多 64 条排队消息，队列满时丢弃新指标。日志处理器等待或抛异常时，命令路径不等待日志完成；提交、回执和后续 CAS 仍由原有游戏逻辑裁定。预检或账务拒绝也使用同一个非阻塞投递入口。

### 用量与费用字段

| 字段 | 含义 |
| --- | --- |
| `usage` | 已通过响应校验的 token 计数。缺失或无效时为 `unknown`，输入预检估算不纳入该字段 |
| `reserved_usd_micros` | 本地预算原始预留金额，单位为微美元。尚无预留时为 `unknown`。该字段记录原始预留，账本负责体现释放后的净预算 |
| `charged_usd_micros` | 可信 usage 按已配置的价格计算且已写入本地账本的结算金额。未确认结算时为 `unknown` |
| `final_cost_usd_micros` | 服务商最终账单当前不可用，因此为 `unknown` |

例如，固定 Mock 回复返回输入 17、输出 3 个 token。按测试价格，日志记录原始预留 2,304 微美元和已结算 15 微美元，最终账单仍为 `unknown`。如果请求超时且没有 usage，预留保留，结算和最终费用均为 `unknown`。示例为测试账本数据，本轮真实费用为 USD 0。

## 已自动测试

- 开启 `LANGSMITH_TRACING=true` 并套用激活的追踪上下文及继承回调，用 Mock 检查追踪入口与 HTTP 请求均未触发。默认关闭本地 INFO 指标时，Demo HTTP 命令照常提交。
- 使用真实游戏状态生成私人线索和历史，并对观测记录的完整字段集合、随机 trace ID、Cookie、假密钥、账号/房间/存档标识、原始输入输出逐项断言。模拟输运异常、超时、HTTP 错误和缺失 usage 检查固定错误、Fallback 与未知费用。测试也检查 NPC HTTP 原始错误与地址受到屏蔽，普通输运日志继续可见。
- 用 Fake Observer 阻塞并抛错。A 的命令在处理器仍卡住时完成，只推进一个版本并写入一个回执。重复 UUID 复用回执。对下一条命令，在 A 进入数据库 CAS 后让 B 先赢得竞争，A 即使碰到相同的观测故障仍收到 409，无额外写入或成功回执。测试读取真实 SQLite 和 MongoDB 聚合记录，并验证模型调用次数。
- 原有观测回归保留全部断言，在读取异步日志前等待指定事件。

## 已验证

从 `backend/` 执行，`MONGO_URI` 指向专用的真实 MongoDB 测试库，镜像为 `mongo:7.0.48`。完整套件用 SQLite 作为默认仓储，并执行参数化的真 MongoDB 用例。仓储专项使用 `TWOWORLDS_TEST_BACKEND=mongo`。

AI 专项 **156 通过**，其中新增观测测试 17 项。NPC 对话 27 项、角色上下文与存档隔离 129 项、真实 MongoDB 仓储专项 61 项均通过。Ruff lint、Ruff format、离线 uv lock 和 `git diff --check` 均通过。

本地后端全量 **1680 通过、0 失败、0 跳过**，其中包括启用真实 SQLite 和 MongoDB 的观测测试。全量报告有一条 Starlette/AnyIO 弃用警告。GitHub Actions 的实际结论记录在本任务 PR。

```bash
uv run --locked --offline pytest tests/ai -ra --tb=short
uv run --locked --offline pytest tests/api/test_dialogue.py tests/api/test_narrative_isolation.py tests/api/test_save_isolation.py -ra --tb=short
TWOWORLDS_TEST_BACKEND=sqlite uv run --locked --offline pytest -ra --tb=short
TWOWORLDS_TEST_BACKEND=mongo uv run --locked --offline pytest tests/storage/test_mongo_contract.py tests/storage/test_repository_contract.py -ra --tb=short
uv run --locked --offline ruff check .
uv run --locked --offline ruff format --check .
uv lock --check --offline
git diff --check
```

## 未验证

当前验证使用 Demo、Fake Observer、本地日志和 Mock HTTP。真实追踪服务、外部模型连通性、生产日志收集链路和服务商账单均未验收。长时间阻塞、堆积或进程退出时，本地指标可能丢失。游戏回执的持久性由存档仓储提供。

## 后续待授权

第三方追踪接入、数据留存策略和真实模型与账单验证需分别确认授权。当前停在本任务 PR 人工审查。

## 阅读顺序

1. [工作流 Prepare/Generate 与 `NarrativeRun.record`](../../backend/src/twoworlds/ai/graph.py) 和 [SaveService 的最终状态](../../backend/src/twoworlds/application/saves.py)展示指标何时进入投递。
2. [本地观测](../../backend/src/twoworlds/ai/observation.py)与 [HTTP Provider](../../backend/src/twoworlds/ai/providers/openai_compatible.py)展示白名单、后台写入和输运日志的范围。
3. [Provider 网关](../../backend/src/twoworlds/application/narrative_gateway.py)展示预算预留、结算和拒绝。
4. [观测回归](../../backend/tests/ai/test_observation.py)展示追踪守卫、模拟输运和两个真实数据库中的故障注入。
