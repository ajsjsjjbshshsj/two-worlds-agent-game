# 修复两项历史后端测试失败 · JSON 错误分类与演示 NPC 契约

2026-11-19。任务基线为 `codex/bootstrap` 的 `62fe1dd`（PR #34 合并提交），任务分支 `codex/fix-historical-backend-contracts`。目标：解决 [T06.3.4 报告](t06-3-4-identity-cleanup-acceptance.md)记录的 1383 passed / 3 failed 中除 Mongo CLI 超时（独立复验已通过）外的两项历史失败。本轮只处理这两个问题及其必要回归测试，不改前端、不改账号认证协议、不开始 T12.2。

## 一、深层 JSON 错误分类

### 复现与根因

历史失败用例：`tests/content/test_loader.py::test_json_parser_recursion_failure_is_reported_without_a_raw_traceback`，写入 3000 层嵌套数组，期待 `CONTENT_INVALID_JSON`，云端实际报 `CONTENT_INVALID_SCHEMA`。

本机（Windows / Python 3.12.4）该用例反而通过——探针证实分类取决于平台解析器递归上限：

| 嵌套深度 | 本机 json.loads | 修复前 loader 分类 |
| --- | --- | --- |
| 300 / 800 / 1400 | 解析成功 | CONTENT_INVALID_SCHEMA（错误） |
| 3000 | RecursionError | CONTENT_INVALID_JSON（碰巧正确） |

根因：解析阶段没有显式深度边界。深层嵌套在递归上限较高的平台（云端 Linux）被解析成功后落进 Pydantic 校验，按 Schema 失败分类；在递归上限较低的平台解析失败按 JSON 分类。同一份输入的分类随平台漂移，违反"按实际失败阶段分类"的契约。

### 修复

`content/loader.py`：

- 新增 `MAX_JSON_DEPTH = 64`：深度与重复键、非标准常量、1MiB 大小一样属于解析阶段输入约束。解码后、`json.loads` 前用线性扫描计算数组/对象嵌套深度（字符串内括号不计、转义引号不结束字符串），超限按 `CONTENT_INVALID_JSON` 拒绝。64 层远高于两套正式剧本的实际结构深度，远低于任何平台的解析器递归上限与 Pydantic 递归保护。
- 解析阶段保留 `(UnicodeError, ValueError, RecursionError)` → `CONTENT_INVALID_JSON`。
- Schema 阶段新增 `RecursionError` 捕获 → `CONTENT_INVALID_SCHEMA`：即使未来出现校验阶段递归失败，也不允许裸露 RecursionError，且按实际失败阶段分类。
- 错误消息仍为固定文案，不含原始 JSON、私有内容、绝对路径或 Python 原始异常；`from None` 抑制异常链。

### 新增边界测试（tests/content/test_loader.py）

- 65 / 200 / 800 / 1400 / 3000 / 10000 层数组：一律 `CONTENT_INVALID_JSON`（修复前 65–1400 红）。
- 3000 层对象嵌套：`CONTENT_INVALID_JSON`。
- 深度恰为 `MAX_JSON_DEPTH` 的顶层数组：解析成功、模型不符 → `CONTENT_INVALID_SCHEMA`，证明按阶段分类而非按深度一刀切。
- 深度 `MAX_JSON_DEPTH + 1`：`CONTENT_INVALID_JSON`。
- monkeypatch 使 `ScriptVersion.model_validate` 抛 RecursionError：收敛为 `CONTENT_INVALID_SCHEMA`，消息不含私有细节，异常链被抑制（修复前红）。
- 字符串字段内含 1800 个括号字符：正常加载，证明扫描不误伤字符串内容。

无效编码（含 BOM）、非法常量（NaN/±Infinity）、顶层与嵌套重复键由既有 `test_invalid_json_never_reaches_schema`、`test_duplicate_json_keys_are_rejected_instead_of_last_value_winning` 覆盖，本轮保留未改。文件大小、UTF-8、路径边界等既有安全限制全部保留。

## 二、演示 NPC 私密对话契约

### 契约核实

demo NPC 仍属首版产品契约，未废弃：

- docs/01 FR-12（本人上下文、模式标识、无规则写入权限）、§10 NPC 与提示、沟通栏"NPC 私聊"。
- docs/03 §10.1 通用动作固定 `talk {question}`；§8 "首版 NPC 回复仅保存到当前角色的私人文本"；§12 语音未配置时 `enabled=false`；接口清单 `GET /api/saves/{id}/voice`。
- docs/05 QA-P04（A 提问不进入 B 私聊）、验收流程"示例模式明确"、性能表"示例 NPC 本地示例，无付费网络"。
- AGENTS.md 边界 1（AI 无修改游戏事实的工具）、边界 3（私密隔离）。

失败用例 `tests/contracts/test_platform.py::test_demo_npc_is_private_and_cannot_change_game_facts` 复现为 422 `UNKNOWN_ACTION`：`SaveService.submit_command` 把 talk 直通规则引擎，引擎按设计拒绝未注册动作（`tests/domain/test_lighthouse.py` 仍要求引擎拒绝 talk，该边界保留）。

### 修复

- 新增 `application/dialogue.py`：`TalkArgs`（question 复用持久层 Question 约束：strip 后 1–1000 字符、严格字符串、禁止多余字段）；固定模板 `DEMO_ANSWER`（不回显提问、不触及谜底/搭档秘密、不调用任何外部服务）；`append_demo_turn` 追加本人轮次并按每角色最近 20 轮裁剪（只裁本角色最旧轮次）。
- `application/saves.py`：talk 在应用层处理——校验参数（失败 422 `INVALID_COMMAND`）、写入 `DialogueTurn(mode="demo")`、版本水位与存档/状态/历史三方一致地 +1（SaveRecord 契约），但不产生任何公共事件/里程碑，全部游戏事实原样保留。幂等回执、CAS 竞争、容量 512、未满员 `PAIR_NOT_READY` 守卫沿用原命令流程。新增 `voice_status`：成员边界与读档一致（外人 404），恒返回 `enabled=false, capabilities=[]`。
- `domain/projection.py`：`PersonalView.dialogue` 从恒空改为 `DialogueView` 元组；`project_save` 新增可选 `dialogues` 参数，按 `turn.role == role` 过滤——HTTP、WS（复用 read_save）、命令响应共用同一投影策略，伙伴投影不含提问原文。默认空参保持纯领域调用方不变。
- `api/routers/saves.py`：新增 `GET /api/saves/{save_id}/voice`。
- `api/app.py`：`ai_mode != "demo"` 在装配时显式 ValueError——真实 NarrativeProvider/LangGraph 未接入，不静默退回 demo。

### 完成后对话的契约冲突（未解决，留待 T14）

docs/01 §9"NPC 在完成后可继续围绕已完成事实对话"与现有领域冻结冲突：`recap._timeline` 要求 `game_completed` 里程碑版本等于历史水位，`append_public_history` 拒绝完成后追加，SaveRecord 要求存档/状态/水位三方一致——完成档实际上对所有新命令只读（既有测试守护）。本轮不放宽这些被测试守护的领域不变量：完成档 talk 与其他新命令一致返回 422 `SAVE_COMPLETED`，旧回执仍可确认。冲突与取舍记录于此，待 T14 完整 NPC 设计时裁决（需要新的对话存储/版本语义，而非简单放宽 recap 校验）。

### 新增回归测试（tests/api/test_dialogue.py，SQLite/Mongo 双适配器）

- talk 返回 mode=demo 私密对话；提问标记不出现在 B 的任何投影；双方 completed/scene/public/actions/devices/clues 不变；存档事实逐字段（除版本）不变；公共事件/里程碑不变；版本三方一致 +1。
- 完成档 talk 拒绝 `SAVE_COMPLETED`，存档与回执完全不变。
- talk 后规则命令继续版本链（receipts [1,2]，水位连续）。
- 同 request_id 重发：duplicate=true、原 accepted_version、对话不重复追加、聚合不变。
- 非法参数 7 组（缺失/空/全空白/超 1000/非字符串/多余字段/错字段名）：422 `INVALID_COMMAND`，无副作用、无回执。
- A 22 轮 + B 3 轮：A 保留最近 20 轮、B 3 轮不受影响；双方投影互不含对方提问。
- voice：成员 200 `enabled=false`、no-store；外人 404。
- `ai_mode="provider"` 装配拒绝。

原有测试未删除、未 skip/xfail、未弱化断言。

## 三、验证

### 单次完整后端运行（不拼接多次结果）

命令（backend 目录）：`MONGO_URI="mongodb://127.0.0.1:27017" .venv/Scripts/python.exe -m pytest -q --basetemp=work/basetemp-full`

- 时间：2026-11-19 15:25:29Z → 15:50:00Z，1469.68 秒。
- 结果：**1424 项 = 1422 通过 / 2 失败 / 0 装配错误 / 0 跳过**，1 条既有 anyio 弃用警告。
- 环境：Windows / Python 3.12.4，真实 MongoDB（twoworlds-mongo 容器，127.0.0.1:27017）与 SQLite 双适配器；每例随机临时库并清理。
- 2 项失败：`tests/api/test_websocket.py::test_dev_launcher_serves_real_websocket_over_loopback[sqlite]` 与 `[mongo]`，均为 `httpx.ConnectTimeout`（环回 TCP 连接超时，非业务断言失败）。

### 两项 WS 环回失败的归因（非本轮新增）

- 独立复验（无并行负载）：仍 2 失败。
- **干净基线对照**：在另一工作树的 `62fe1dd`（不含本轮任何改动）同步依赖后运行同一用例，同样失败——证明是本机 pytest 子进程环回网络的既有环境问题，不是本轮修复引入的回归。
- 手动以相同启动器代码在固定端口与临时端口范围启动真实 TCP 服务，`/api/scripts` 均返回 200；`test_real_cli_tcp_startup` 双适配器通过。
- PR #34 的完整运行在云端工作区执行，该两项当时通过；本机环境差异未在本轮修复范围内处理。
- 诚实声明：单次全量就是 1422/2，不把独立复验通过拼成全绿。

### 与 PR #34 历史结果对比

PR #34：1386 项，1383 通过 / 3 失败（Mongo CLI 注册超时、深层 JSON 分类、demo NPC）。

| 历史失败 | 本轮单次全量 | 单独复验 |
| --- | --- | --- |
| 深层 JSON 分类（test_json_parser_recursion_failure…） | 通过 | 通过 |
| demo NPC（test_demo_npc_is_private_and_cannot_change_game_facts） | 通过 | 通过 |
| Mongo CLI 注册超时（test_real_cli_tcp_startup[mongo]） | 通过 | 通过（sqlite/mongo 各 1） |

- 用例数：1386 + 38 新增（loader 边界 11 + dialogue 双适配器 27）= 1424；移除 0。
- 两项历史目标失败全部解决；未发现可归因于本轮改动的新失败（WS 环回 2 项经基线复现为既有环境问题）。
- 单独复验批（最终代码）：JSON 1 + NPC 契约 1 + CLI 启动 2 + dialogue 27 = **31 通过**。全量运行后仅修改一处注释（行为无关），复验批在最终代码上执行。

### 静态与锁检查

- `ruff check .`：All checks passed。
- `ruff format --check .`：117 文件全部已格式化。
- `uv lock --check --offline`：一致（31 包）。
- `git diff --check`：通过。

### 专项套件（全量中的分组证据）

- 内容 213 通过（基线 202 + 11 项新边界）；dialogue 27 通过（SQLite/Mongo）；NPC 契约 1 通过。
- Domain、Application、API、SQLite 真实仓储、MongoDB 真实仓储均包含在单次全量中，除上述 2 项环境失败外全部通过。

## 四、代码阅读顺序

1. `content/loader.py` 的 `MAX_JSON_DEPTH` / `_check_nesting_depth` 与两阶段 except——理解"解析阶段输入约束"与"按实际失败阶段分类"。
2. `tests/content/test_loader.py` 新增边界用例——65 层与 64 层的分类差异是核心。
3. `application/dialogue.py`——demo 表达与 20 轮裁剪。
4. `application/saves.py` 的 talk 分支与 `voice_status`——版本三方一致、事实不动。
5. `domain/projection.py` 的 `DialogueView` 与角色过滤——单一投影策略。
6. `tests/api/test_dialogue.py` 与 `tests/contracts/test_platform.py` 的 NPC 用例。

## 五、限制

- demo 回复是固定模板：三级提示、场景感知、真实模型与降级标识属 T14。
- 完成档 NPC 对话受领域冻结拒绝，冲突见上。
- voice 恒 disabled；场景音效/环境音/预制叙事音频不受影响（由内容与前端播放器提供）。
- 本轮未改前端；前端 NPC 界面与 WS 对话推送未接通。