# T05.2 · MongoRepository 与真实数据库契约

验证日期：2026-11-11。本轮仅实现 Mongo 仓储、索引和真实测试；没有身份/房间/存档 API、WebSocket、前端、AI 或 T06。

交付：[PR #14](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/14)，分支 `codex/t05-2-mongo-repository`，主要提交 `32afa3b`；目标 `codex/bootstrap`，未合并。

## 基线与文件

PR #13 已在 UTC 11:32:50 合并，最新远端 `codex/bootstrap` 为 `7fdcfc27a06a5180960624cddeafd7cd5416fc19`。从该提交建立 `codex/t05-2-mongo-repository`。交付位于独立工作树 `F:\two-worlds-agent-game\work\pr-t01-1-schema`；主目录用户修改及旧本地提交未覆盖、未推送。

新增 `storage/mongo.py`、`storage/indexes.py`、`tests/storage/test_mongo_contract.py` 和本报告。更新测试 fixture、SQLite 专项的适配器 fixture、后端 README、任务清单、交接及 T05.1 报告合并状态。没有改领域模型、Repository Protocol、SQLite 实现、依赖或锁文件。

## 环境与集合

使用 T05.1 的真实本机 MongoDB **8.0.34**，PyMongo **4.19.0**，Python **3.12.4**。连接通过环境变量 `MONGO_URI` 传给构造函数；本次无凭证地址为 `mongodb://127.0.0.1:27017/?directConnection=true`。专用 `twoworlds-mongo` 是 standalone mongod，没有改成副本集，也没有停止它来测试断连。

| 集合 | 文档结构 | 保存方式 |
| --- | --- | --- |
| accounts | AccountRecord，含有界 sessions 数组 | id 映射为 _id，账户与所有会话一次替换 |
| pairs | PairRecord，含 A/B、邀请摘要/期限和 version | 创建 B 必须为空；仅 join_pair 可以占 B |
| saves | SaveRecord，嵌入 state、public_history、dialogues、receipts | 完整聚合一次替换，version 和回执同步 |

时间统一存为 UTC ISO 字符串，例如 `2026-11-11T12:00:00.123456Z`，固定六位微秒。这样不会被 BSON Date 的毫秒精度截断，字符串排序也与时间排序一致。转换递归覆盖会话、对话、回执及顶层时间；UUID 存标准字符串。专项测试验证嵌套微秒、中文和跨秒排序。

候选通过已有 `dumps/loads` 完整重验后才生成 BSON 文档。读取时只将 `_id` 映射回 `id`，严格 JSON/完整模型重验并检查规范化结果与原文档一致。不会静默丢弃未知字段或冲突的 id 别名；未知嵌套字段、原生 BSON 日期、NaN、超大文档均作为 `CorruptRecord` 拒绝。返回冻结模型，不向调用方暴露原始可变 BSON。

## 稳定索引

各集合另有 Mongo 自动建立的 `_id_` 唯一索引。

| 集合 | 稳定名称 | 字段顺序 | 唯一性/用途 |
| --- | --- | --- | --- |
| accounts | accounts_recovery_unique | recovery_digest 升序 | 唯一，恢复摘要查询 |
| accounts | accounts_session_unique | sessions.token_digest 升序 | 唯一多键，会话跨账户唯一 |
| pairs | pairs_invite_unique | invite_digest 升序 | 唯一，邀请查询 |
| pairs | pairs_member_a | member_a 升序 | 成员 A 查询 |
| pairs | pairs_member_b | member_b 升序 | 成员 B 查询 |
| saves | saves_pair_script_unique | pair_id、script_id 升序 | 唯一，防重复建档 |
| saves | saves_pair_updated | pair_id 升序、updated_at 降序 | 房间存档按更新时间查询 |

会话索引使用 `partialFilterExpression={"sessions.token_digest":{"$type":"string"}}`，空会话数组不参与唯一 null 键竞争。一个 Account 内重复摘要仍由模型拒绝，不能指望唯一多键索引发现单文档内重复。没有 Account TTL 索引，显式判断 `created_at <= now < expires_at`。

`ensure_indexes` 使用稳定名称加建索引，重复初始化不产生副本。配置冲突必须使启动失败，不捕获后继续，不删除/替换既有索引。专项通过真实 `index_information` 和重复插入确认名称、键、唯一性及无 TTL，而非只检查代码声明。

## Repository 方法

构造要求显式 URI/数据库名，初始化 Ping 并建索引。每个实例新建自己的同步 MongoClient；server selection/connect 超时 2 秒、socket 3 秒、整体操作 5 秒，确认写入 `w=1` 与 `journal=True`，不使用不确认写入或自动 SQLite 降级。方法签名与端口的 16 个方法逐项核对一致。

| 方法 | 实现 |
| --- | --- |
| create_account | 完整校验后单次 insert，摘要唯一冲突拒绝 |
| get_account / get_account_by_recovery_digest | 索引查文档，完整重验 |
| get_account_by_session_digest | 多键索引查账户，重验并显式判会话时间 |
| compare_and_swap_account | 校验账户身份/恢复摘要/创建时间不变、version+1，条件 replace 整个含 sessions 的文档 |
| create_pair | 拒绝预填 B，检查 A 账户存在，再 insert |
| get_pair / get_pair_by_invite_digest | 按 _id/唯一邀请摘要查询并重验 |
| join_pair | 校验邀请、时间、自占位和 B 账户存在，按空 B/旧 version/匹配邀请/未到期条件原子 replace；相同 B 重试返回已有房间 |
| compare_and_swap_pair | B 始终不变，满员后邀请不变；空房仍能刷新邀请，旧 version 条件替换 |
| create_save | 检查父 Pair，已有 pair/script 返回原档；并发唯一冲突后重读并返回胜者存档，不篡改固定内容版本 |
| get_save / get_save_for_pair_script | 主键/复合唯一索引读取并重验 |
| get_receipt | 先定位 save_id 聚合，再匹配 actor_id + request_id；最多512条 |
| compare_and_swap_save | 见下一节，单文档提交整个聚合 |
| close | 幂等关闭客户端；关闭后全部仓储操作拒绝 |

查询键必须是字符串，不能把查询操作符字典作为 ID 或摘要传入。父对象存在性由仓储显式读取检查，Mongo 不提供 SQL 外键。当前 Protocol 没有删除父账户/房间接口，因此不需要跨聚合删除事务；管理员越过仓储直接删除父文档不属于本轮一致性保证。未来增加删除/解绑必须重新设计生命周期边界。

## 单文档 CAS

Save 写入顺序：读取并校验当前文档 → expected_version 不符返回 False → 当前512抛 ReceiptLimitReached → 完整重验候选 → version 恰好 +1、身份/房间/剧本/创建时间不变、更新时间不倒退 → 旧回执内容完整保留且只追加一条 → 新回执版本等于新存档版本 → `replace_one({_id,version:expected_version}, entire_document)`。

使用 matched_count 判断提交是否成功；不将 modified_count 当作版本匹配依据。两个客户端都基于 v0 提交 v1 时，最多一次替换能匹配 v0；另一方返回 False，不覆盖胜者。状态、公共历史、私聊和回执嵌在同一文档中，不会先写状态再写回执。达到512仍可查询旧回执，先查已接受请求的应用流程和 HTTP 错误码映射留后续。

Account 会话、Pair B 位、Save 游戏聚合都分别在单文档内变化，所以 standalone 单节点已能执行本轮原子更新，不需要多文档事务或副本集。本实现没有 Python 全局锁/进程锁或 start_transaction 调用。

[Mongo 单文档原子性说明](https://www.mongodb.com/docs/manual/core/write-operations-atomicity/)、[replace_one 及 matched_count](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/replace/)、[唯一多键索引说明](https://www.mongodb.com/docs/manual/core/index-unique/) 是相关行为依据。

## 异常与真实故障验证

DuplicateKeyError 映射 DuplicateRecord；读取模型/格式损坏为 CorruptRecord；非法候选或转换为 InvalidRepositoryTransition；父对象缺失为 MissingRecord；512满额为 ReceiptLimitReached；其他驱动/数据库故障为 RepositoryError。对外异常使用固定说明且抑制原始异常上下文，不打印 URI、密码或原始文档。

数据库不可达测试占用一个仅 bind、未 listen 的随机本机端口，URI 带合成测试密码，验证初始化确实失败且异常不泄露密码。已建立连接后的真实断连则新建独立临时 Docker mongod：随机容器名、独立临时端口、tmpfs 数据、任务标签，先写 Account，再核验完整容器 ID 和标签后停止它。读和 CAS 均抛 RepositoryError，不伪装 None、False 或成功；最后仅清理该临时容器/匿名卷。共享 T05.1 容器始终保持运行。

另在本轮随机测试库使用真实 Mongo validator 拒绝候选版本，验证 Save 全聚合和回执都没有变化；真实唯一索引拒绝会话摘要冲突时，旧账户和会话均保留。没有 mock 数据库事务或驱动失败。

## 共享契约与隔离

`test_repository_contract.py` 的 30 项内容不变。共享 fixture 默认 SQLite；`TWOWORLDS_TEST_BACKEND=mongo` 时切换到 MongoRepository。Mongo 每个测试随机新数据库，同一测试内每次 factory 调用使用新的 MongoClient；先核对库名未存在再登记清理权限，结束仅 drop 自己生成的库并关闭客户端。

两个适配器各运行同一份30项契约，包括独立实例/客户端 + ThreadPoolExecutor/Barrier 抢 B、同版本 CAS 和重复建档。结果分别要求唯一 B、CAS `[False,True]`、同一原存档，最终完整聚合和回执与胜者一致。

SQLite/Mongo 专项各自覆盖 repository_factory，避免全局选择变量让 SQL 专项误连 Mongo。Mongo 专项不因缺数据库而 skip；MONGO_URI 缺失会明确失败。完整测试现在包含真实 Mongo 专项，需要本机 Docker、可用 Mongo 与缓存的测试镜像；没有新增不显式声明的全局依赖。

## 验证记录

首先测试缺少实现，出现 3 failed / 44 errors。初实现曾因 PyMongo 4.19 不支持 MongoClient 的 j 参数别名而失败；已改为 journal=True，不修改测试来掩盖失败。首轮真实47项随后通过。最终扩大嵌套微秒断言并隔离专项 fixture 后：

| 检查 | 真实结果 |
| --- | --- |
| Mongo 专项 | 17 通过 |
| 共享契约，真实 Mongo | 30 通过 |
| SQLite 专项及同一共享契约 | 41 通过（11+30） |
| Domain | 308 通过 |
| Content | 191 通过 |
| 全量 Backend | 595 项：557 通过、38 失败，0 errors/0 skipped，1 条既有 anyio 弃用警告；退出码 1 |
| Ruff / 格式 / uv 离线锁 | 全部通过，51 个 Python 文件格式正确，24 包锁一致 |

逐项比较 T05.1 的 work/t051-all.xml 与本轮 work/t052-all.xml：新增失败 0、消失失败 0；38 个失败用例 ID 与消息完全一致，均缺 twoworlds.api.app。另用 git diff 确认 T05.1 头提交 efd8014 与已合并的 7fdcfc2 后端代码树一致，原 JUnit 对应同一后端基线。通过数从540增加至557，新增17项 Mongo 专项；真实 Mongo 的共享30项另行运行，不在全量中重复计数。没有删除原测试或增加 skip/xfail。

最终复核：本轮随机前缀的临时数据库剩余 0 个，临时断连容器剩余 0 个；共享 twoworlds-mongo 仍 healthy，真实 Ping 通过，版本 8.0.34。

从本交付工作树根目录复验：

```powershell
$env:MONGO_URI='mongodb://127.0.0.1:27017/?directConnection=true'
$env:TWOWORLDS_TEST_BACKEND='mongo'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_mongo_contract.py -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t052-mongo --junitxml=work/t052-mongo.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_repository_contract.py -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t052-shared-mongo --junitxml=work/t052-shared-mongo.xml
$env:TWOWORLDS_TEST_BACKEND='sqlite'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_sqlite.py backend/tests/storage/test_repository_contract.py -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t052-sqlite --junitxml=work/t052-sqlite.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t052-domain --junitxml=work/t052-domain.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t052-content --junitxml=work/t052-content.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t052-all --junitxml=work/t052-all.xml
.\backend\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/hatch_build.py
.\backend\.venv\Scripts\python.exe -m ruff format --check backend/src backend/tests backend/hatch_build.py
uv lock --project backend --check --offline --cache-dir F:/two-worlds-agent-game/work/uv-cache
```

Mongo 专项的真实断连测试需要 Docker 和本机缓存的官方镜像，默认 mongodb/mongodb-atlas-local:8.0，可通过 TWOWORLDS_TEST_MONGO_IMAGE 指定已准备镜像；测试不会自动拉取。临时容器和数据库使用随机名并在归属校验后清理，不停止共享数据库。


## 学习与未验证项

先看 ports/repository.py，接着 indexes.ensure_indexes 与 mongo.py 的编码/解码、_operation、_replace，再读 create_pair/join_pair/compare_and_swap_save。最后看 conftest 的后端选择、未修改的共享契约、Mongo 专项中的真实 validator 和隔离断连实例。

只证明当前单节点 Mongo 的仓储行为。生产认证/TLS、复制集/主从切换、分片、备份恢复、跨聚合删除、应用/API/WS、实际部署均未验证，不把本机通过描述成生产已上线。下一步建议 T06 身份与会话应用流程，必须等用户审查并另行授权；本轮交付后停止。

## 历史失败逐项核对

下列每项均保持失败，且修复前后消息相同（缺 API 入口）：

| 用例 | T05.1 → T05.2 |
| --- | --- |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[bad-id]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[boolean]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[client-role]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[extra-arg]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[legacy-value]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[negative]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_commands::test_old_version_retry_confirms_receipt_and_returns_current_snapshot` | 同一消息，失败 → 失败 |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[args]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[kind]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[original-version]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_commands::test_same_request_id_is_independent_for_other_actor` | 同一消息，失败 → 失败 |
| `tests.contracts.test_commands::test_two_application_instances_compete_on_one_database[different]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_commands::test_two_application_instances_compete_on_one_database[identical]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_identity::test_client_cannot_claim_identity_or_role[account_id]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_identity::test_client_cannot_claim_identity_or_role[player_id]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_identity::test_client_cannot_claim_identity_or_role[role]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_identity::test_display_name_does_not_restore_another_account` | 同一消息，失败 → 失败 |
| `tests.contracts.test_identity::test_logout_revokes_only_the_current_session` | 同一消息，失败 → 失败 |
| `tests.contracts.test_identity::test_recovery_proves_ownership_and_issues_a_distinct_session` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_demo_npc_is_private_and_cannot_change_game_facts` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[early-dispatch]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[unpowered-repair]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[unscanned-rail]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[wrong-role]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_lighthouse_requires_both_roles_and_agreed_ending[guide_now]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_lighthouse_requires_both_roles_and_agreed_ending[wait_tide]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_only_discovered_owner_can_share_the_designated_clue_text` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_outsider_websocket_never_receives_a_snapshot` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_power_budget_rejects_the_entire_allocation` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_private_projection_and_forbidden_access` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_restart_restores_identity_save_and_receipt` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_room_admits_only_one_partner_across_application_instances` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_scripts_and_pairs_have_independent_saves_and_receipts` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_starline_has_a_distinct_cooperative_solution[rescue_detour]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_starline_has_a_distinct_cooperative_solution[return_station]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_unfilled_room_allows_reading_but_no_game_or_npc_write[game-command]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_unfilled_room_allows_reading_but_no_game_or_npc_write[npc]` | 同一消息，失败 → 失败 |
| `tests.contracts.test_platform::test_websocket_uses_auth_frame_and_personal_projection_on_reconnect` | 同一消息，失败 → 失败 |
