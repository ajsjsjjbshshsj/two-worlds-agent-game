# T08.1 · 剧本目录与存档生命周期

日期：2026-11-15。独立工作树`F:/two-worlds-agent-game/work/pr-t01-1-schema`，分支`codex/t08-1-scripts-saves`，基线为PR #17合并提交`5a4804215b2e08b745aae0ec31e1c9a2d4b14c1d`。主目录用户未提交修改保留，不修改本地旧bootstrap。

## 范围与设计决定

只实现GET /api/scripts、POST /api/saves、GET /api/saves、GET /api/saves/{id}。没有命令/CAS应用流程、幂等回执查询、同步、WS、媒体路由、AI或生产部署。

复用PublicationStore、create_initial_state、SaveRecord、PublicHistory、project_save与既有Repository.create_save。不改变IdentityService、PairService、GameState、规则引擎、发布格式、数据库schema/索引或已有CAS语义。

旧提案POST请求只有pair_id/script_id，本轮依用户“精确内容版本”要求细化为必填script_version。缺省不猜latest、缺版不回退；已存在同pair/story的另一版本返回409 SCRIPT_VERSION_CONFLICT。目录按id及三段版本数字排序。目录能展示未来其他机制的已发布Metadata，但现有引擎仅支持灯塔，其他机制建档409 SCRIPT_UNSUPPORTED。

正式发布库仍为空。测试发布的是正式灯塔JSON的独立副本，配测试专用1像素PNG/短WAV，经真实ReleaseApproval和哈希封存；不是minimal.json正式化，也不意味着灯塔28项正式媒体/许可完成。测试快照全部位于随机临时目录，不进入Git或产品包。

## 调用关系与接口

HTTP Router → current_identity → SaveService → Repository/PublicationStore → 规则初始化或project_save → 白名单响应。

| 接口 | 输入/输出 | 权限 |
| --- | --- | --- |
| GET /api/scripts | ScriptMetadata数组，精确发布版本，稳定排序 | 公开 |
| POST /api/saves | {pair_id,script_id,script_version} → PlayerSnapshot加id/pair_id | 已认证Pair成员 |
| GET /api/saves | 可选pair_id → 摘要数组，save id升序 | 仅本人所属Pair |
| GET /api/saves/{id} | PlayerSnapshot加id/pair_id | Pair成员，角色由服务器推导 |

摘要仅id/pair_id/script_id/script_version/version/scene_id/completed/role/created_at/updated_at。没有state、dialogues、receipts、凭证摘要或媒体路径。未满员可由A建档/读开场；后续游戏写入/NPC限制不属于本轮。

路由只解包严格输入和认证身份；服务检查Pair、精确加载发布内容、调用规则初始化、构建version0/空历史/空回执聚合。唯一建档依赖既有SQL事务+唯一约束或Mongo复合唯一索引，服务不以先查后插保证唯一。8次有界重试只处理随机save id碰撞。重复创建返回仓储实际已有的状态而非重置；已绑定版本不变。

读档每次查询成员，加载存档的精确script_version，再调用project_save，包括PublicHistory一致性校验与合法分享。SaveSnapshot继承安全PlayerSnapshot，只追加id/pair_id，绝不从SaveRecord直接dump整档。列表新增list_saves_for_pair，两个适配器逐条重新校验、返回冻结元组，应用层再验证房间匹配并构造摘要。

create_app显式注入Repository和可选PublicationStore；默认lifespan打开包内published目录，as_file资源保持至关闭，失败也关闭Repository。没有模块导入时连接数据库、没有读写降级。save_clock可注入，默认复用identity_clock或UTC系统时间；建档时拒绝早于Pair.updated_at或无时区的时间，不声称能检测所有时钟回退。

所有响应no-store、统一error信封。SAVE_NOT_FOUND/SCRIPT_NOT_FOUND为404；版本冲突/机制不支持为409；内容损坏、存档无效、依赖故障、生成失败、时钟错误为503且retryable=true。安全文本不带底层异常、秘密或路径。无效会话401、额外/缺失输入422沿用现有处理。

## 测试与真实数据库证据

采用test-driven-development：先新增目录/仓储测试并实际运行，2失败，分别为目录404及不存在list_saves_for_pair；再实现代码。初次新服务/API+共享契约67通过，出现的8条新Pydantic实例model_fields弃用告警已改为类访问，另1条原anyio告警保留。补充私密/分享/重开/损坏/缺版/不支持机制专项12通过。

修改前同一解释器与真实Mongo运行全量，781项=750 passed /31 failed /0 errors /0 skipped。所有31项在support.py:102创建存档返回404 NOT_FOUND。最终835项=804 passed /31 failed /0 errors /0 skipped，新增54项全部通过；失败ID新增/消失均0。31条原失败消息全部由404 NOT_FOUND变为422 INVALID_INPUT，仍停在同一建档调用，原因是旧请求缺script_version；后续命令/WS断言没有执行。

本轮使用已有twoworlds-mongo（127.0.0.1:27017），真实ping=1.0；每个Mongo fixture创建随机twoworlds_test_t052_*库并只清理该库。SQLite使用C盘随机临时文件。没有Mock替代真库，不改共享容器、不删除已有数据、不下载镜像。

并发测试用两套真实Repository/应用，屏障仅让create_save同时抵达既有数据库写入：同版本200+200且同save id/单记录；不同版本200+409，唯一胜者版本冻结。没有Python全局锁替代唯一索引。故障代理只测试安全503错误路径，不作为事务证据。

恢复测试先用真实规则生成两人已发现线索及可选分享，构造完整版本/历史/回执的预存聚合，再关闭原TestClient与Repository、新建应用和连接读回，分别比较A/B投影。没有新增命令API，也没有把应用重开说成Mongo服务重启。

## 复验命令

在上述工作树执行。Python为backend/.venv的3.12；MONGO_URI使用自己可用的本地真实Mongo，不提交环境文件。

```powershell
$env:MONGO_URI='mongodb://127.0.0.1:27017/?directConnection=true'
$env:TWOWORLDS_TEST_BACKEND='sqlite'
$saveTemp=Join-Path 'C:/Users/30704/AppData/Local/Temp' ('twoworlds-t081-'+[guid]::NewGuid().ToString('N'))
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/application/test_saves.py backend/tests/api/test_saves.py -q -p no:cacheprovider --basetemp=$saveTemp
# 每次使用新的saveTemp；共享契约分别设置sqlite/mongo
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_repository_contract.py -q
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q
.\backend\.venv\Scripts\ruff.exe check backend/src backend/tests backend/hatch_build.py
.\backend\.venv\Scripts\ruff.exe format --check backend/src backend/tests backend/hatch_build.py
uv lock --check --offline --project backend --cache-dir F:/two-worlds-agent-game/work/uv-cache
```

## 学习与待完成

阅读application/saves.py的_role → create_save → _snapshot；再看严格请求Schema和四条路由，最后看仓储list_saves_for_pair及test_saves.py的CreationBarrier与重开测试。例：A建档获得A投影；B加入同Pair后读取同id，project_save只给B设备/已发现线索；A的未分享线索不随完整state发送。

QA-S01、版本绑定与目录/HTTP投影有专项证据。QA-R04仅完成可读开场部分；游戏写入与NPC验收、T08.2命令/回执、T08.3媒体、WS、正式视听、前端与生产部署均待后续。测试发布素材不构成可售内容。完成后创建独立PR，等待用户审查，不自动开始T08.2。


## 最终验证结果

| 检查 | 实际结果 |
| --- | --- |
| 应用服务专项（SQLite/Mongo各7） | 14 passed |
| 目录/存档HTTP专项（SQLite/Mongo各18，加默认空目录1） | 37 passed |
| SQLite共享契约+专项 | 44 passed（32+12） |
| 真实Mongo共享契约+专项 | 50 passed（32+18） |
| 修改前完整基线 | 781项：750 passed /31 failed |
| 本轮完整后端 | 835项：804 passed /31 failed /0 errors /0 skipped |
| Ruff check | 通过 |
| Ruff format --check | 80文件通过 |
| uv lock --check --offline | 24包一致，未改依赖 |

完整组别：API148、application88、content191、domain308、storage62、contracts38（7通过/31失败）。专项互有覆盖，不能相加作为完整数量。最终只保留1条既有anyio弃用告警。

Python3.12.4、PyMongo4.19.0、真实MongoDB8.0.34。最终专项51通过用时121.49秒；SQLite仓储44通过1.68秒，Mongo仓储50通过44.86秒；完整835项206.46秒。报告结果来自本轮实际执行的JUnit：work/t081-focused.xml、t081-storage-sqlite.xml、t081-storage-mongo.xml、t081-all.xml；基线t081-baseline.xml。XML与临时数据库不进入PR。

完整回归退出码1，不能宣称全绿。旧测试/断言未删除或弱化，没有skip/xfail。后续任务须在明确版本与真实发布测试内容的契约下继续接通命令等流程，不能用自动发布草稿来消除失败。

### 31项历史失败逐项对照

| 旧契约失败ID | 基线实际位置 | T08.1实际位置 |
| --- | --- | --- |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[bad-id]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[boolean]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[client-role]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[extra-arg]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[legacy-value]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[negative]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_commands::test_old_version_retry_confirms_receipt_and_returns_current_snapshot` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[args]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[kind]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[original-version]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_commands::test_same_request_id_is_independent_for_other_actor` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_commands::test_two_application_instances_compete_on_one_database[different]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_commands::test_two_application_instances_compete_on_one_database[identical]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_demo_npc_is_private_and_cannot_change_game_facts` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[early-dispatch]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[unpowered-repair]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[unscanned-rail]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[wrong-role]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_lighthouse_requires_both_roles_and_agreed_ending[guide_now]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_lighthouse_requires_both_roles_and_agreed_ending[wait_tide]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_only_discovered_owner_can_share_the_designated_clue_text` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_outsider_websocket_never_receives_a_snapshot` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_power_budget_rejects_the_entire_allocation` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_private_projection_and_forbidden_access` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_restart_restores_identity_save_and_receipt` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_scripts_and_pairs_have_independent_saves_and_receipts` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_starline_has_a_distinct_cooperative_solution[rescue_detour]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_starline_has_a_distinct_cooperative_solution[return_station]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_unfilled_room_allows_reading_but_no_game_or_npc_write[game-command]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_unfilled_room_allows_reading_but_no_game_or_npc_write[npc]` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |
| `tests.contracts.test_platform::test_websocket_uses_auth_frame_and_personal_projection_on_reconnect` | support.py:102，POST /api/saves，404 NOT_FOUND | 同一位置，422 INVALID_INPUT，缺少script_version |


## 修改文件清单

- `backend/README.md`
- `backend/src/twoworlds/api/app.py`
- `backend/src/twoworlds/api/errors.py`
- `backend/src/twoworlds/api/routers/saves.py`
- `backend/src/twoworlds/api/schemas/saves.py`
- `backend/src/twoworlds/application/saves.py`
- `backend/src/twoworlds/ports/repository.py`
- `backend/src/twoworlds/storage/mongo.py`
- `backend/src/twoworlds/storage/sqlite.py`
- `backend/tests/api/conftest.py`
- `backend/tests/api/test_saves.py`
- `backend/tests/application/conftest.py`
- `backend/tests/application/test_saves.py`
- `backend/tests/save_support.py`
- `backend/tests/storage/test_mongo_contract.py`
- `backend/tests/storage/test_repository_contract.py`
- `backend/tests/storage/test_sqlite.py`
- `docs/03-技术架构与数据接口.md`
- `docs/04-开发阶段与任务清单.md`
- `docs/05-测试验收与交付标准.md`
- `docs/reports/saves-lifecycle.md`
- `docs/开发进度与交接.md`


## GitHub交付

实现提交`818dd960d8687aa3b969f7bd97f4f0edb421ade8`已推送分支`codex/t08-1-scripts-saves`；[PR #18](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/18)目标`codex/bootstrap`，状态open，未合并。本轮检查22个文件，未新增凭证、数据库文件、缓存或临时媒体；既有无效Mongo URI测试样例与基线一致。后续收尾仅更新本报告/交接，业务代码测试结果不变。当前停止等待用户审查，不自动开始T08.2。
