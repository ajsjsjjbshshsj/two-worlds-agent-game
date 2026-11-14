# T06.1 · 身份服务与会话管理

日期：2026-11-14。范围只含身份核心业务，不含 HTTP、限频、no-store、认证中间件、WS、OAuth、密码登录或前端。

交付：[PR #15](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/15)，分支 `codex/t06-1-identity-service`，主要提交 `828417d`；目标 codex/bootstrap，未合并。

## 基线和正式契约

PR #14 已合并，最新远端 codex/bootstrap 为 `11b7656239ad3f8be0ace5651bc8f32f727a2670`。从该基线建立 `codex/t06-1-identity-service`，在 `F:\two-worlds-agent-game\work\pr-t01-1-schema` 开发。主目录用户未提交学习修改和旧本地历史未覆盖、未推送。

文档03规定恢复密钥和会话各256位、会话7天、保留最新5个，登出端点要求已认证，失效凭证统一401。服务遵循该要求：重复撤销已经失效的token返回UNAUTHENTICATED，不再次写库；效果幂等不代表未知/无效token也返回成功。没有发现本轮业务要求与正式文档冲突。T06原先包含HTTP的任务清单拆为T06.1核心和T06.2通道，后者未执行。

## 文件与接口

- security/credentials.py：new_secret、digest_secret，统一生成和摘要；security/__init__.py为包说明。
- application/identity.py：IdentityService、固定错误码IdentityError、仅必要信息的冻结响应。
- tests/application/conftest.py：复用原SQLite/Mongo临时库fixtures；test_identity.py：同一组身份行为在两个真实适配器上执行。
- 本报告及 backend/README.md、任务清单、开发交接同步更新。仓储、Protocol、领域模型、依赖锁和旧测试未改。

| 接口 | 输入和输出 |
| --- | --- |
| create_account(display_name) | 新建账号和初始会话；返回AccountCreated(account: AccountInfo, expires_at, token, recovery_key) |
| recover(recovery_key) | 返回同一账号的SessionIssued(account, expires_at, token)，不再返回恢复密钥 |
| authenticate(token) | 仅有效会话返回内部AccountRecord；此完整模型不是未来HTTP响应 |
| revoke(token) | 撤销当前会话，返回None；失效凭证统一拒绝 |

AccountInfo只含id、display_name。两个签发响应的明文秘密字段repr=False，普通repr不输出凭证；显式业务响应依然包含必要明文，未来HTTP必须白名单序列化和禁止缓存，不能任意记录响应正文。

## 凭证与流程

生产默认使用secrets.token_urlsafe(32)，随机部分有256位熵。恢复密钥前缀tw_recovery_、会话前缀tw_session_，分别独立生成并隔离用途。account_id用独立secrets.token_hex(16)生成。摘要统一为完整凭证的SHA-256十六进制；高熵服务端随机秘密不是用户密码，不加入bcrypt等密码方案。只存摘要，无明文列、日志输出或异常输入回显。

创建：校验昵称 → 独立生成恢复/会话 → 创建版本0 AccountRecord和7天SessionRecord → Repository一次创建 → 成功后才返回明文。唯一冲突有限重试，不能未持久化就签发成功。

恢复：校验恢复凭证格式/用途 → 按摘要查询 → 获取时钟 → 丢弃过期会话 → 新建7天会话 → 按created_at稳定排序保留最新5个 → 完整验证candidate、version+1 → CAS。失败重读并重新计算整个候选，不把旧数组覆盖新数组。相同时间按既有接纳顺序排序，新会话排同时间最后；超限只移除最早会话。时钟回退或未来会话会显式CLOCK_ERROR，不返回无法存活的新token。

验证：校验session格式 → 摘要查询 → 再次明确检查created_at <= now < expires_at。创建瞬间有效、到期瞬间失效。account_id、昵称、恢复密钥不能作为日常token，未知、过期、撤销、淘汰凭证统一拒绝。

撤销：按同一个操作时间验证token → 从最新Account仅移除该摘要 → version+1 CAS。冲突重读并重新验证；不影响其他设备。并发恢复/撤销交错也合并最新会话集。操作仅修改Account，不修改Pair或Save。

## 并发和错误

默认最多8次尝试，可配置1～32。没有全局锁或进程锁。恢复和撤销只有CAS确认后返回成功；冲突耗尽报CONCURRENT_UPDATE，存储失败映射DEPENDENCY_UNAVAILABLE而不伪装认证失败/成功。随机源异常或不符合格式报GENERATION_FAILED；昵称错误INVALID_INPUT；时钟问题CLOCK_ERROR。错误只带固定说明，不携带参数或存储原始错误。

时钟及凭证随机部分生成器允许注入；默认时钟UTC、安全随机源不会因测试而降低安全。测试用的弱生成器会被拒绝。注入点仅供可信装配代码，不能向HTTP客户端开放。

并发测试在首次CAS前放Barrier，让两个服务确实基于同版本竞争；转发器仍调用真实数据库CAS并记录至少一次False，没有伪造成功。恢复/恢复、撤销/撤销、恢复/撤销均检查最终会话和版本。另用只返回False的代理单独测试有限重试耗尽，该代理不作为数据库并发正确性的证据。

## 验证记录

先运行测试复现缺身份模块失败；初次命令还缺MONGO_URI，正式真库验证均显式设置环境变量。初查Docker未运行，启动已有Desktop后沿用健康的MongoDB 8.0.34；PyMongo4.19.0/Python3.12.4。没有安装或升级依赖。

| 检查 | 实际结果 |
| --- | --- |
| 身份专项，SQLite/Mongo | 40通过（各20） |
| SQLite专项及共享契约 | 41通过 |
| Mongo专项及共享契约 | 47通过（17+30） |
| Domain / Content | 308 / 191通过 |
| 全量Backend | 635项：597通过、38失败，0 errors/0 skipped，1条既有anyio警告；退出码1 |
| Ruff check / format --check | 通过，56个Python文件 |
| uv lock --check --offline | 24包一致，依赖未改 |

比较T05.2的work/t052-all.xml与本轮work/t061-all.xml：新增失败0、消失失败0，原38项的ID和消息完全相同（缺twoworlds.api.app）。新安全测试无失败。原始失败没有删除、skip或xfail。首轮身份30通过，补时钟和淘汰边界至34通过，再覆盖共享仓储对象及独立客户端两种并发组合后40通过。

真实并发共12项：两种数据库 × 同仓储对象/独立仓储同库 × 恢复/撤销/交错。每次都观察到实际CAS冲突，最终版本和会话断言通过。

实际命令（从交付工作树运行）：

```powershell
$env:MONGO_URI='mongodb://127.0.0.1:27017/?directConnection=true'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/application -q --tb=short -p no:cacheprovider --basetemp=work/t061-identity-final --junitxml=work/t061-identity.xml
$env:TWOWORLDS_TEST_BACKEND='sqlite'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_sqlite.py backend/tests/storage/test_repository_contract.py -q --basetemp=work/t061-sqlite --junitxml=work/t061-sqlite.xml
$env:TWOWORLDS_TEST_BACKEND='mongo'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_mongo_contract.py backend/tests/storage/test_repository_contract.py -q --basetemp=work/t061-mongo --junitxml=work/t061-mongo.xml
$env:TWOWORLDS_TEST_BACKEND='sqlite'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain -q --basetemp=work/t061-domain --junitxml=work/t061-domain.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q --basetemp=work/t061-content --junitxml=work/t061-content.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short -p no:cacheprovider --basetemp=work/t061-all-final --junitxml=work/t061-all.xml
.\backend\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/hatch_build.py
.\backend\.venv\Scripts\python.exe -m ruff format --check backend/src backend/tests backend/hatch_build.py
uv lock --project backend --check --offline --cache-dir F:/two-worlds-agent-game/work/uv-cache
```


## 学习检查点

先读 Repository Protocol 和 Account/SessionRecord，再看 credentials.py 的生成/摘要、identity.py 的响应及create/recover/authenticate/revoke，最后看测试的真实CAS Barrier、边界时间和淘汰断言。无HTTP运行入口。

QA-I01～I04仅取得服务层证据。HTTP字段白名单/401映射、no-store、限频、WS过期、日志策略集成和实际跨设备UI均未实现或验证。下一步建议T06.2实现HTTP身份接口和相关安全策略；本轮完成后停止，等待审查。

## 既有失败核对

| 用例 | 与T05.2比较 |
| --- | --- |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[bad-id]` | 同一失败消息 |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[boolean]` | 同一失败消息 |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[client-role]` | 同一失败消息 |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[extra-arg]` | 同一失败消息 |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[legacy-value]` | 同一失败消息 |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[negative]` | 同一失败消息 |
| `tests.contracts.test_commands::test_old_version_retry_confirms_receipt_and_returns_current_snapshot` | 同一失败消息 |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[args]` | 同一失败消息 |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[kind]` | 同一失败消息 |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[original-version]` | 同一失败消息 |
| `tests.contracts.test_commands::test_same_request_id_is_independent_for_other_actor` | 同一失败消息 |
| `tests.contracts.test_commands::test_two_application_instances_compete_on_one_database[different]` | 同一失败消息 |
| `tests.contracts.test_commands::test_two_application_instances_compete_on_one_database[identical]` | 同一失败消息 |
| `tests.contracts.test_identity::test_client_cannot_claim_identity_or_role[account_id]` | 同一失败消息 |
| `tests.contracts.test_identity::test_client_cannot_claim_identity_or_role[player_id]` | 同一失败消息 |
| `tests.contracts.test_identity::test_client_cannot_claim_identity_or_role[role]` | 同一失败消息 |
| `tests.contracts.test_identity::test_display_name_does_not_restore_another_account` | 同一失败消息 |
| `tests.contracts.test_identity::test_logout_revokes_only_the_current_session` | 同一失败消息 |
| `tests.contracts.test_identity::test_recovery_proves_ownership_and_issues_a_distinct_session` | 同一失败消息 |
| `tests.contracts.test_platform::test_demo_npc_is_private_and_cannot_change_game_facts` | 同一失败消息 |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[early-dispatch]` | 同一失败消息 |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[unpowered-repair]` | 同一失败消息 |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[unscanned-rail]` | 同一失败消息 |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[wrong-role]` | 同一失败消息 |
| `tests.contracts.test_platform::test_lighthouse_requires_both_roles_and_agreed_ending[guide_now]` | 同一失败消息 |
| `tests.contracts.test_platform::test_lighthouse_requires_both_roles_and_agreed_ending[wait_tide]` | 同一失败消息 |
| `tests.contracts.test_platform::test_only_discovered_owner_can_share_the_designated_clue_text` | 同一失败消息 |
| `tests.contracts.test_platform::test_outsider_websocket_never_receives_a_snapshot` | 同一失败消息 |
| `tests.contracts.test_platform::test_power_budget_rejects_the_entire_allocation` | 同一失败消息 |
| `tests.contracts.test_platform::test_private_projection_and_forbidden_access` | 同一失败消息 |
| `tests.contracts.test_platform::test_restart_restores_identity_save_and_receipt` | 同一失败消息 |
| `tests.contracts.test_platform::test_room_admits_only_one_partner_across_application_instances` | 同一失败消息 |
| `tests.contracts.test_platform::test_scripts_and_pairs_have_independent_saves_and_receipts` | 同一失败消息 |
| `tests.contracts.test_platform::test_starline_has_a_distinct_cooperative_solution[rescue_detour]` | 同一失败消息 |
| `tests.contracts.test_platform::test_starline_has_a_distinct_cooperative_solution[return_station]` | 同一失败消息 |
| `tests.contracts.test_platform::test_unfilled_room_allows_reading_but_no_game_or_npc_write[game-command]` | 同一失败消息 |
| `tests.contracts.test_platform::test_unfilled_room_allows_reading_but_no_game_or_npc_write[npc]` | 同一失败消息 |
| `tests.contracts.test_platform::test_websocket_uses_auth_frame_and_personal_projection_on_reconnect` | 同一失败消息 |
