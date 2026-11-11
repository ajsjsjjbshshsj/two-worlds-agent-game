# T04.2 · SQLite 事务与仓储验证

验证日期：2026-11-11。范围仅为演示 SQLite 适配器，不包含 Mongo、身份/房间/存档 API、WebSocket、前端或 AI。

交付：[PR #12](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/12)，分支 `codex/t04-2-sqlite-repository`，实现提交 `926f2b6`。目标 `codex/bootstrap`，等待用户审查，未合并。

## 基线与修改

开发前核实 PR #11 已合并：`2026-11-11T09:37:06Z`，合并提交 `94b4cb8230db86c3b873b065ab2e7f1e63bf3036`。从该远端 `codex/bootstrap` 基线建立 `codex/t04-2-sqlite-repository`。使用隔离工作树 `F:\two-worlds-agent-game\work\pr-t01-1-schema`；主目录原有未提交学习修改未覆盖，也未将其旧本地提交推送。

新增 `storage/sqlite.py`、`tests/storage/conftest.py`、`test_repository_contract.py`、`test_sqlite.py` 和本报告。更新后端 README、任务清单和交接。既有领域模型、Repository Protocol、序列化、内容、旧契约测试和依赖锁均未修改，无新增依赖。

## 数据库结构

| 表 | 权威 JSON 与查询列 | 约束和索引 |
| --- | --- | --- |
| accounts | AccountRecord；account_id、recovery_digest、version | account_id 主键，recovery_digest 唯一 |
| account_sessions | 仅 token_digest 与 account_id；时间从 AccountRecord 恢复 | token_digest 主键且唯一，account_id 外键，按 account_id 索引 |
| pairs | PairRecord；pair_id、invite_digest、member_a、member_b、version | pair_id 主键，invite_digest 唯一，A/B 均引用账户，A 不等于 B，成员查询索引 |
| saves | 完整 SaveRecord；save_id、pair_id、script_id、script_version、version | save_id 主键，pair_id 外键，UNIQUE(pair_id, script_id)，version 在 0～512 |

存档唯一索引也支持按房间/剧本查询。会话索引只存摘要，不写明文 token。回执、对话、GameState、PublicHistory 全部在同一 SaveRecord JSON 内，没有分离的回执写事务；最多 512 条回执，所以按 actor/request 在聚合中查找有明确上界。

数据库读取复用严格 `loads`：拒绝损坏 JSON、重复键、非有限数和不合法模型，重建冻结对象；失败转换为 `CorruptRecord`。另外比对 SQL 查询列与 JSON、会话摘要集合与 AccountRecord，拒绝不一致。写入候选也先完整往返校验，绕过构造的对象不能直接落库。

## 事务与并发

每次仓储操作打开自己的连接，启用 `foreign_keys=ON` 和 5000ms `busy_timeout`。读操作使用 `BEGIN` 一致读取，写操作使用 `BEGIN IMMEDIATE`，事务成功才 commit，任何异常均 rollback 并关闭连接。没有 Python 全局锁或进程锁。

账户 CAS 同时写 JSON/version 并替换会话摘要索引，唯一摘要冲突或索引插入失败会回滚全部内容。有效会话要求 `created_at <= now < expires_at`，不会仅凭索引存在就放行。

创建房间必须保证 B 为空，非空候选在数据库写入前抛 `InvalidRepositoryTransition`。普通 Pair CAS 始终保持 `member_b` 不变，SQL 也不更新该列；空房可以刷新邀请，不能同时填入 B。满员后不能替换成员/邀请。

只有 `join_pair` 能占用 B 位：在写事务内检查邀请、期限、A/B；SQL 同时要求旧 version 与 `member_b IS NULL`。同一 B 携带匹配邀请重试返回已占据房间，包括首次加入已成功后邀请才过期的情况；其他身份不能覆盖 B。已有父账户由外键强制校验。

重复创建同房间同剧本返回原存档，包括原先固定的内容版本，不替换为请求的新 ID/版本。父房间缺失抛 `MissingRecord`。

### Save CAS 的提交顺序

1. 在数据库写事务内读当前聚合；不存在或 `expected_version` 过时返回 False。
2. 现存版本 512 时抛 `ReceiptLimitReached`，保留全部旧回执；调用方必须先查已接受回执，HTTP `SAVE_COMMAND_LIMIT` 映射留 T08。
3. 完整验证候选，要求版本恰好 +1，存档 ID、房间、剧本 ID、内容版本和创建时间不变，更新时间不倒退。
4. 候选回执必须保留旧回执的每个字段，并只追加一条；新回执接受版本等于新存档版本。模型另外要求接受版本完整连续、actor/request 唯一。
5. 执行一条 `UPDATE saves SET version=?,document=? WHERE save_id=? AND version=?`，提交整个聚合。不会先存状态再存回执。

例如 A 和 B 都读到 v0，分别构造 v1 候选。数据库让其中一次写事务先完成，另一连接随后读到 v1，与其 expected v0 不符，返回 False。失败方不能覆盖成功方的状态、历史、对话或回执；上层以后重读并重新判断命令。

唯一冲突转换为 `DuplicateRecord`，父外键失败为 `MissingRecord`，非法转换为 `InvalidRepositoryTransition`，存储解码失败为 `CorruptRecord`。其他 SQLite 错误转换为不含原始数据库内容的 `RepositoryError`，不会伪造成功。锁等待超过 5 秒也属于显式仓储失败。

## 测试方式与结果

环境 Python 3.12.4，pytest 9.0.2，Ruff 0.15.4。共享契约文件不导入 sqlite3 或具体适配器，通过 `repository_factory` 创建实例；未来 T05 可替换该 fixture 运行相同行为。SQLite 特有约束/触发器测试单独保留。

并发采用两个独立 SQLiteRepository 实例，共享真实临时 `.sqlite` 文件，通过两个线程和 Barrier 同时提交。分别验证抢 B、重复建档、同版本 CAS；没有用同一 Python 对象或 mock 数据库证明事务。文件恢复测试先成功写入领域命令产生的聚合，关闭仓储，再构造新实例读取同一路径，逐字段比较完整存档及回执。

故障注入使用真实 SQL 触发器：账户 JSON 更新后，会话插入触发 `RAISE(ABORT)`，验证旧账户和摘要索引全部保留；存档更新的 AFTER 触发器先写 audit 表再失败，验证存档不变、无新回执、audit 也无残留。另测 session 唯一冲突回滚。

| 检查 | 实际结果 |
| --- | --- |
| SQLite 专项 | 11 通过 |
| 共享仓储契约 | 30 通过（含本轮入口修复） |
| 全部 Domain | 308 通过 |
| 全部 Content | 191 通过 |
| 全量 Backend | 578 项：540 通过、38 失败、0 errors、0 skipped，1 条既有 anyio 弃用警告 |
| Ruff check | 通过 |
| Ruff format --check | 48 个 Python 文件均通过 |
| 离线依赖锁检查 | 22 包一致，无依赖变更 |

先写契约并运行时出现 27 个缺 SQLite 模块错误，完成实现后 27 通过；扩展到 35 项，最终加入两个实际存档隔离契约后共 36 项通过。全量测试仍明确返回退出码 1，没有删除原有测试或添加 skip/xfail。

从当前工作树根目录复现（JUnit 与临时数据库只在忽略的 work 下）：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_sqlite.py -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t042-sqlite --junitxml=work/t042-sqlite.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_repository_contract.py -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t042-final-contract --junitxml=work/t042-contract.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t042-domain --junitxml=work/t042-domain.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t042-content --junitxml=work/t042-content.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t042-final-all --junitxml=work/t042-all.xml
.\backend\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/hatch_build.py
.\backend\.venv\Scripts\python.exe -m ruff format --check backend/src backend/tests backend/hatch_build.py
uv lock --project backend --check --offline --cache-dir F:/two-worlds-agent-game/work/uv-cache
```

受限环境的严格内容路径解析曾需已有授权的提升执行；最终上述测试使用相同正确权限运行，未放宽加载器校验。不是 SQLite 测试失败。

## 未完成与学习检查点

T04.2 没有发现待修复的新失败。38 个 HTTP/应用契约仍未通过，不能将仓储测试描述为身份认证、规则 API 或端到端游戏验收。规则执行、权限和玩家投影仍由可信调用方提供；仓储不能直接作为公网授权边界。

仅显式本地演示 SQLite；Mongo、Mongo 真库索引/CAS、生产配置缺库不降级、API 错误码映射、服务进程重启、WebSocket、媒体和真实设备验收尚未完成。当前文件重开测试只证明数据库文件恢复，不等于 HTTP 服务重启。未建立数据库迁移系统，也未重新构建发行包。

学习顺序：`ports/repository.py` → `storage/sqlite.py` 的表结构、`_transaction`、`compare_and_swap_save` → 共享契约中的并发/文件重开用例 → SQLite 触发器回滚测试。运行仓储专项即可观察；当前没有游戏服务地址。

下一阶段建议 T05：替换仓储 fixture，在真实 Mongo 上运行共享契约，并补 Mongo 特有索引、独立客户端竞争及数据库断开行为。当前未执行 T05。交付后停在 T04.2，等待用户审查和学习。

## PR #12 审查修复：B 位唯一占用入口

用户指出 `create_pair` 和空房 `compare_and_swap_pair` 都允许绕过邀请填入 B。先新增真实数据库测试：修复前 3 项失败（预填 B 创建、CAS 填 B、换邀请同时填 B），另外 2 项已有满房保护通过；失败均为应抛异常但未抛出，证实测试命中原问题。

最小修复只改变 SQLite 的房间写入入口：`create_pair` 在执行 INSERT 前拒绝 B 非空；普通 CAS 将 B 纳入不变字段，并移除 UPDATE 的 member_b 赋值。`join_pair` 的邀请/过期/自身身份/已有账户/同 B 重试/第三人拒绝和数据库并发逻辑保持原实现。

新增 5 项共享契约，验证拒绝预填创建（无记录/邀请索引残留，之后能正常创建）、两种空房 CAS 占位尝试（原文档/版本/旧新邀请索引均不变）、满房删除/替换 B。已有正常刷新邀请再加入的测试继续通过。原先“CAS 为不存在 B 触发外键”的用例迁移为“join_pair 为不存在 B 触发外键”：业务拒绝发生在唯一合法加入入口，仍验证真实外键失败及回滚，没有删除或跳过失败测试。

最终 SQLite 11、共享契约 30、领域 308、内容 191 通过；全量 540 通过、38 失败，0 errors/0 skipped。对比修复前 `work/t042-all.xml` 和修复后 `work/pair-entry-all.xml`，38 项失败 ID 与消息逐一相同，均缺 API 入口，无新增失败。Ruff check 与 format --check 均通过，48 文件格式正确。未执行 T05，也未合并 PR。

本轮修改：`storage/sqlite.py`、`tests/storage/test_repository_contract.py`、本报告、后端 README、任务清单和交接。使用原分支更新现有 PR #12；保护主工作区用户改动。

本轮最终复验命令：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_repository_contract.py -q --tb=short -p no:cacheprovider --basetemp=work/pytest-pair-entry-green --junitxml=work/pair-entry-contract.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_sqlite.py -q --tb=short -p no:cacheprovider --basetemp=work/pytest-pair-entry-sqlite --junitxml=work/pair-entry-sqlite.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain -q --tb=short -p no:cacheprovider --basetemp=work/pytest-pair-entry-domain --junitxml=work/pair-entry-domain.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q --tb=short -p no:cacheprovider --basetemp=work/pytest-pair-entry-content --junitxml=work/pair-entry-content.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short -p no:cacheprovider --basetemp=work/pytest-pair-entry-all --junitxml=work/pair-entry-all.xml
.\backend\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/hatch_build.py
.\backend\.venv\Scripts\python.exe -m ruff format --check backend/src backend/tests backend/hatch_build.py
```

## 38 项历史失败逐项比较

比较 PR #11 的 `work/receipt-all.xml`（499 通过、38 失败）与本轮 `work/t042-all.xml`。失败用例集合相同，新增失败 0、消失失败 0。以下每项仍失败，旧消息为缺 `twoworlds.api.app, twoworlds.storage.sqlite`，新消息统一为仅缺 `twoworlds.api.app`；SQLite 模块已实现，旧 API 契约尚未进入业务行为验证。

| 用例（每个参数单独比较） | 基线 → 本轮 |
| --- | --- |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[bad-id]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[boolean]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[client-role]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[extra-arg]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[legacy-value]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[negative]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_commands::test_old_version_retry_confirms_receipt_and_returns_current_snapshot` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[args]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[kind]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[original-version]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_commands::test_same_request_id_is_independent_for_other_actor` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_commands::test_two_application_instances_compete_on_one_database[different]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_commands::test_two_application_instances_compete_on_one_database[identical]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_identity::test_client_cannot_claim_identity_or_role[account_id]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_identity::test_client_cannot_claim_identity_or_role[player_id]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_identity::test_client_cannot_claim_identity_or_role[role]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_identity::test_display_name_does_not_restore_another_account` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_identity::test_logout_revokes_only_the_current_session` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_identity::test_recovery_proves_ownership_and_issues_a_distinct_session` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_demo_npc_is_private_and_cannot_change_game_facts` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[early-dispatch]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[unpowered-repair]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[unscanned-rail]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[wrong-role]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_lighthouse_requires_both_roles_and_agreed_ending[guide_now]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_lighthouse_requires_both_roles_and_agreed_ending[wait_tide]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_only_discovered_owner_can_share_the_designated_clue_text` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_outsider_websocket_never_receives_a_snapshot` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_power_budget_rejects_the_entire_allocation` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_private_projection_and_forbidden_access` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_restart_restores_identity_save_and_receipt` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_room_admits_only_one_partner_across_application_instances` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_scripts_and_pairs_have_independent_saves_and_receipts` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_starline_has_a_distinct_cooperative_solution[rescue_detour]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_starline_has_a_distinct_cooperative_solution[return_station]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_unfilled_room_allows_reading_but_no_game_or_npc_write[game-command]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_unfilled_room_allows_reading_but_no_game_or_npc_write[npc]` | 失败 → 失败，仅缺 API |
| `tests.contracts.test_platform::test_websocket_uses_auth_frame_and_personal_projection_on_reconnect` | 失败 → 失败，仅缺 API |
