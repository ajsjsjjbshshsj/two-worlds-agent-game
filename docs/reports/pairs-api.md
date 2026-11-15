# T07 · 双人房间与邀请

日期：2026-11-15。当前交付：PairService30、房间HTTP55、共享契约各31、并发10通过；完整750通过/31项未实现存档API的历史失败。仅T07，不实现T08存档/命令、WS、前端、AI或部署。

## 已核实基线与执行计划

远端codex/bootstrap为f0df72548808cc8ca387533edac6d98cd841fbdd（PR #16合并）。独立工作树F:/two-worlds-agent-game/work/pr-t01-1-schema初始干净，创建codex/t07-pairs-invite；主目录用户未提交修改保留。

本轮按现有设计直接实现，使用writing-plans整理以下检查点；用户已明确授权，无额外审批或新功能设计环节。

- [x] 先记录合并基线完整测试；环境缺失如实保留，再恢复已有开发服务。
- [x] 新增共享仓储成员查询行为测试，SQLite参数化查询/Mongo成员OR查询返回完整重验的冻结记录，按id升序确定顺序。
- [x] 先写双适配器PairService测试，再实现独立invite凭证命名空间、24小时期限、创建/刷新有限重试和join_pair入口。
- [x] 先写HTTP/双独立应用竞争测试，再增加严格空请求/邀请模型、白名单响应、PairError映射与应用装配。
- [x] 验证两人抢B、刷新与旧邀请加入竞争；使用独立真实仓储，屏障仅对齐真实数据库操作，不替代数据库CAS。
- [x] 运行专项、双适配器共享契约、完整后端、Ruff与锁检查；逐项对比历史失败，更新正式文档并提交PR。

## 本轮具体设计

PairService只依赖Repository Protocol。邀请使用独立tw_invite_命名空间、secrets.token_urlsafe(32)和SHA-256；只在创建/刷新成功后返回明文。刷新以完整PairRecord候选version+1 CAS，唯一摘要冲突或版本冲突有限重试。加入必须走join_pair；已加入B使用同一邀请重试可恢复原结果，即使该邀请后来过期；第三人不能据此获得访问权限。

HTTP以已认证Account推导角色。POST创建/刷新只接受无正文、null或空对象，任何成员/角色字段拒绝；join只接受invite_token。GET列表直接返回数组，每项仅{id,role,member_count}，不返回邀请、摘要、恢复密钥或会话。列表按id升序；所有响应no-store。

QA-R01～R03在本轮验证；QA-R04关于开场、游戏写入和NPC调用的完整HTTP验收依赖T08及后续，不标通过。


## 实现、接口与错误

新增application/pairs.py的PairService(repository, clock, credential_generator, max_attempts=8)，业务接口create_pair(actor_id)、refresh_invite(actor_id,pair_id)、join_pair(actor_id,invite_token)、list_pairs(actor_id)。actor_id仅供可信内部调用，HTTP只从current_identity取得，不接受客户端自报身份。返回冻结InvitationIssued/PairInfo，邀请repr=False；没有再次定义PairRecord或改GameState。

| HTTP | 200返回 | 主要拒绝条件 |
| --- | --- | --- |
| POST /api/pairs | {id,role:a,invite_token,invite_expires_at} | 无有效Bearer401，额外输入422 |
| POST /api/pairs/{id}/invite | 同上，新24小时邀请 | 非A/不存在404；满员409 |
| POST /api/pairs/join | {id,role:b} | 不存在/过期/刷新旧凭证/自己加入404；第三人满员409 |
| GET /api/pairs | [{id,role,member_count}] | 未认证401；非本人房间不返回 |

四接口全部no-store。创建/刷新允许无正文、null或空对象；加入仅接受严格字符串invite_token，1～128字符，额外成员/角色字段拒绝。专用响应Schema逐字段构造，不dump PairRecord，不返回邀请摘要、恢复密钥、会话摘要、其他设备信息。列表按id升序，member_count仅1或2；不会在客户端收到内部成员数据后再隐藏。

PairError固定安全文本：INVITE_INVALID/PAIR_NOT_FOUND→404且retryable=false，PAIR_FULL→409且false，CONCURRENT_UPDATE→409且true，DEPENDENCY_UNAVAILABLE/GENERATION_FAILED/CLOCK_ERROR→503且true。请求模型沿用既有INVALID_INPUT 422；无泄密的默认detail。IdentityService、其错误语义、16KiB正文防护、CORS/Allow处理均保留。

security/credentials.py只增加invite前缀，沿用secrets.token_urlsafe(32)、43字符随机部分与统一SHA-256；显式kind校验禁止session/recovery作邀请，也禁止邀请作Bearer。数据库仅存摘要，只有创建/刷新成功响应返回明文，普通日志/响应白名单/repr均有测试。

所有时刻经UTCDateTime规范化，now==invite_expires_at时不允许首次加入。刷新以当前时间重新计算24小时，即使旧邀请已过期也可由A刷新。检测now早于Pair.updated_at以及无时区/溢出时间，返回CLOCK_ERROR；不宣称可检测所有时钟回退。

## 数据库与并发

Repository增加list_pairs_for_member(member_id)->tuple[PairRecord,...]。SQLite在读事务内参数化member_a/member_b OR查询并ORDER BY pair_id，Mongo使用同等$or与_id升序，均逐条完整解码校验，复用已有成员索引。无新表/索引/迁移。原join_pair与compare_and_swap_pair实现未改。

创建唯一键冲突最多尝试8次，重新生成pair_id与邀请；耗尽GENERATION_FAILED。刷新保证新摘要不同于当前，完整模型候选version+1后CAS；唯一冲突重新生成，版本冲突重读。若加入已经赢，重读后PAIR_FULL，不返回未提交邀请。仅生成冲突耗尽GENERATION_FAILED，实际CAS竞争耗尽CONCURRENT_UPDATE。

首次加入调用原join_pair条件占位，失败后重查原邀请。若刷新先赢则摘要不再匹配、INVITE_INVALID；若其他身份先赢则PAIR_FULL。A不能占自己的B。已加入B的同一邀请重放直接恢复原房间、不递增版本；即使原邀请已到期也是读取已确认成员关系，不能给第三人授权。

竞争测试WriteBarrier只在两个独立Repository真实写入之前对齐，随后调用原数据库方法，既不伪造成功也不用进程锁替代CAS。两应用抢同一B得到200+409；同一B并发重试得到200+200且version=1。刷新/加入分别指定join先写、refresh先写，再自由竞争：结果仅200+409（B满员）或200+404（旧邀请失效、B空），胜者写后Pair.version=1；刷新胜后又验证旧邀请不能加入、新邀请可以加入。有限重试耗尽另用只返回False的代理测错误控制流，该代理不作为数据库并发证明。

## 环境检查与真实验证的限制

项目Python3.12.4、PyMongo4.19.0、uv0.11.2，24包依赖版本/锁未改。开始Docker引擎未运行，首次基线因真Mongo不可用而中断；启动已有Docker Desktop（隐藏窗口）后共享twoworlds-mongo恢复。初次完整基线为662 passed/32 failed/1 error，错误是原身份测试Mongo初始化；原用例单独复验1 passed。

共享容器重启后探针仍出现NetworkTimeout和WTimeoutError（code50），未放宽既有驱动超时。只读磁盘指标当时F盘PercentDiskTime=173，空间充足；SQLite也受影响。此现象支持宿主I/O瓶颈判断，不能据此断言所有超时的唯一根因。保留共享容器和命名数据卷，未删除数据。

用已缓存mongodb/mongodb-atlas-local:8.0镜像（服务端8.0.34），随机名twoworlds-t07-...、标签com.twoworlds.test=T07、仅127.0.0.1动态端口、tmpfs /data/db、entrypoint mongod启动本轮独立真库。Ping=1.0，初始化探针约0.046秒；它是实际mongod，不是Mock，原仓储/写关注/CAS实现未变。该真库用于业务行为、条件提交和索引验证；tmpfs不证明生产磁盘持久化或重启恢复。

当时TEMP/TMP也指向F:/developer/temp。第一次导出纯基线仅含backend，遗漏根.gitattributes，造成1项内容测试FileNotFoundError；另1项旧限频测试在负载下Retry-After实为58而非60。该次661 passed/34 failed记录保留；缺根文件是本轮验证副本错误，不是产品缺陷。补回原文件，随后显式C:/Users/30704/AppData/Local/Temp新建随机目录，完整导出f0df725的backend和.gitattributes，核实导入路径后串行运行。C盘SQLite探针5次写入约0.015秒；纯基线最终663 passed/32 failed，未改任何旧测试或断言。

当前T07完整测试同样使用显式C盘新目录与独立真Mongo，750 passed/31 failed。临时源码、环境JSON和JUnit均为本地验证产物，不进入PR；被中断的F盘运行不计作通过。没有安装全局依赖、下载镜像、调用AI或部署公网服务。

收尾核实本轮临时库剩余0；按完整容器ID、T07标签和挂载验证后，仅移除自建tmpfs测试容器及匿名卷。共享twoworlds-mongo仍healthy，命名数据卷未删除；本地JUnit/副本保留排查，不上传Git。

## 实际测试结果

| 范围 | 结果 | 退出码 |
| --- | --- | ---: |
| 首次测试先行接缝 | 3 failed/2 errors：缺成员查询/服务/路由；其中Mongo初始化仍有环境错误 | 1 |
| SQLite首次服务+HTTP子集 | 38 passed、38未选中（后又补7错误映射/2同B并发条目） | 0 |
| PairService双适配器 | 30 passed（SQLite/Mongo各15） | 0 |
| 房间HTTP双适配器及独立映射 | 55 passed | 0 |
| SQLite共享契约 | 31 passed | 0 |
| 真Mongo共享契约 | 31 passed | 0 |
| 两独立应用并发单独复验 | 10 passed、45未选中 | 0 |
| f0df725纯基线完整后端 | 695项：663 passed / 32 failed | 1 |
| T07完整后端 | 781项：750 passed / 31 failed | 1 |
| Ruff check / format --check | 通过，74文件 | 0 |
| uv lock --check --offline | 通过，24包一致 | 0 |

完整运行0 errors/0 skipped，1条原anyio弃用警告。专项统计相互有覆盖，不能相加当作全量。全量包含API111、application74、content191、contracts38、domain308、storage59；除了下表31个旧契约，其余均通过。本轮新增86项=服务30+房间HTTP55+共享契约1；没有删改原契约断言、skip或xfail。

实际命令的参数如下，MONGO_URI在本轮取自被忽略的work/t07-mongo-environment.json；临时容器完成后清理，复验应设置自己的可用本地真Mongo，不能把测试端口当游戏服务地址：

```powershell
$env:MONGO_URI=(Get-Content -Raw work/t07-mongo-environment.json | ConvertFrom-Json).uri
$env:TWOWORLDS_TEST_BACKEND='sqlite'
# 前期专项用系统TEMP；最终完整/并发显式指定C盘
$pairTestTemp=Join-Path $env:TEMP ('twoworlds-t07-application-'+[guid]::NewGuid().ToString('N'))
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/application/test_pairs.py -q --tb=short -p no:cacheprovider --basetemp=$pairTestTemp --junitxml=work/t07-application.xml
# API专项同参数，目标backend/tests/api/test_pairs.py，JUnit为work/t07-api.xml
# 共享契约目标backend/tests/storage/test_repository_contract.py，分别TWOWORLDS_TEST_BACKEND=sqlite/mongo，JUnit为work/t07-contract-{sqlite,mongo}.xml
$pairFullTemp=Join-Path 'C:\Users\30704\AppData\Local\Temp' ('twoworlds-t07-full-'+[guid]::NewGuid().ToString('N'))
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short -p no:cacheprovider --basetemp=$pairFullTemp --junitxml=work/t07-all-c.xml
$pairRaceTemp=Join-Path 'C:\Users\30704\AppData\Local\Temp' ('twoworlds-t07-races-'+[guid]::NewGuid().ToString('N'))
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/api/test_pairs.py -k 'compete' -q --tb=short -p no:cacheprovider --basetemp=$pairRaceTemp --junitxml=work/t07-concurrency.xml
.\backend\.venv\Scripts\ruff.exe check backend/src backend/tests backend/hatch_build.py
.\backend\.venv\Scripts\ruff.exe format --check backend/src backend/tests backend/hatch_build.py
uv lock --check --offline --project backend --cache-dir F:/two-worlds-agent-game/work/uv-cache
```

基线副本由git archive f0df725 backend .gitattributes导出到新建C盘临时目录，子进程PYTHONPATH指向该副本backend/src及backend；导入路径断言通过后，使用同一项目解释器/环境运行其695项。基线JUnit为work/t07-baseline-c.xml，当前为work/t07-all-c.xml。此前的环境/临时副本失败记录仍保留本地。

## 与合并基线逐项比较

新增失败ID=0，消失1项：test_room_admits_only_one_partner_across_application_instances。其余31项failure.message仍是相同安全404 JSON，但实际阶段已从建房推进到support.py:102的save，即POST /api/saves；不能把未执行到的规则、私密投影、NPC或WS后续断言称为通过。

| 原有失败ID | 合并基线 | T07结果/实际失败位置 |
| --- | --- | --- |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[bad-id]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[boolean]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[client-role]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[extra-arg]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[legacy-value]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[negative]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_commands::test_old_version_retry_confirms_receipt_and_returns_current_snapshot` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[args]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[kind]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[original-version]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_commands::test_same_request_id_is_independent_for_other_actor` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_commands::test_two_application_instances_compete_on_one_database[different]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_commands::test_two_application_instances_compete_on_one_database[identical]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_demo_npc_is_private_and_cannot_change_game_facts` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[early-dispatch]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[unpowered-repair]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[unscanned-rail]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[wrong-role]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_lighthouse_requires_both_roles_and_agreed_ending[guide_now]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_lighthouse_requires_both_roles_and_agreed_ending[wait_tide]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_only_discovered_owner_can_share_the_designated_clue_text` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_outsider_websocket_never_receives_a_snapshot` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_power_budget_rejects_the_entire_allocation` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_private_projection_and_forbidden_access` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_restart_restores_identity_save_and_receipt` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_room_admits_only_one_partner_across_application_instances` | support.py:87 pair → POST /api/pairs，404 | 通过：两应用竞争B位 |
| `tests.contracts.test_platform::test_scripts_and_pairs_have_independent_saves_and_receipts` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_starline_has_a_distinct_cooperative_solution[rescue_detour]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_starline_has_a_distinct_cooperative_solution[return_station]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_unfilled_room_allows_reading_but_no_game_or_npc_write[game-command]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_unfilled_room_allows_reading_but_no_game_or_npc_write[npc]` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |
| `tests.contracts.test_platform::test_websocket_uses_auth_frame_and_personal_projection_on_reconnect` | support.py:87 pair → POST /api/pairs，404 | 失败：support.py:102 save → POST /api/saves，404 NOT_FOUND |

## 文件、学习入口与边界

共17文件。新增application/pairs.py、api/routers/pairs.py、api/schemas/pairs.py、tests/application/test_pairs.py、tests/api/test_pairs.py及本报告；更新api/app.py、errors.py、security/credentials.py、ports/repository.py、storage/sqlite.py、mongo.py、共享契约、docs03/04、backend/README与交接。依赖、IdentityService、Account/GameState规则、原身份测试和原契约断言未改。

学习顺序：credentials的用途隔离 → Repository与两个成员查询 → PairService创建/刷新/join/列表 → 响应白名单与认证依赖 → WriteBarrier和两应用HTTP测试。输入例：A先创建，B只持invite_token加入；A刷新与B使用旧邀请若同时进行，数据库条件更新决定唯一合法状态，服务重读后返回明确错误。

QA-R01～R03取得真实证据；QA-R04未满员开场/游戏写入/NPC的完整HTTP验收留T08及后续。当前没有T08存档/命令、WS、前端、AI、OAuth、实时语音或生产部署。只提供TestClient验证，不提供未启动的TCP演示地址。完成后创建独立PR、目标codex/bootstrap，由用户审查手动合并；停止等待，不自动执行T08。
