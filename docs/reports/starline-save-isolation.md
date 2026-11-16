# T09.2 · 双剧本 HTTP、存档隔离与版本绑定

2026-11-16。仅执行 T09.2；基线为 PR #21 合并提交 `a76bb16a1a8308746d0b82c54862b34c8e31ef22`，分支 `codex/t09-2-save-isolation`。从重新 fetch 的远端基线建立分支，交付工作树为 `F:\two-worlds-agent-game\work\pr-t01-1-schema`；主目录未提交的用户学习修改未触碰，未使用子代理。

## 实现与文件

| 文件 | 本轮职责 |
| --- | --- |
| backend/src/twoworlds/domain/recap.py | 为星轨加入四种公共里程碑，沿用已有历史结构、受众筛选和严格一致性检查 |
| backend/src/twoworlds/domain/mechanics/starline.py | B 未发现本人功率板时仅提供检查引导；发现后显示数值预算，不改机关规则 |
| backend/tests/save_support.py | 分别读取两个真实正式 JSON，生成合法 PNG/WAV、哈希与明确 test-only 审核，经原 PublicationStore 封存 |
| backend/tests/contracts/conftest.py | 给历史平台契约同时注入真实灯塔与星轨测试发布版本；原 test_platform.py 断言不变 |
| backend/tests/api/test_save_isolation.py | 双适配器 HTTP、完整结局、跨档/跨房间/回执隔离、应用重开、版本与真实连接 CAS |
| backend/tests/domain/test_recap.py、test_projection.py | 最近30条事件截断后的四个里程碑、两结局、缺失里程碑拒绝、旧灯塔兼容、预算发现边界 |
| backend/tests/storage/test_repository_contract.py | 两个真实剧本、两个角色的 DialogueTurn 随聚合提交、独立保存和连接重开 |
| docs/04、docs/05、开发进度与交接、README、backend/README | 当前状态、验收边界与学习入口 |

没有改路由、应用服务、Repository、SQLite/Mongo 实现、正式剧本 JSON 或生产发布校验。默认正式目录仍为空，所有合成素材和审核仅存在临时测试目录，不代表正式素材或版权许可。

## 调用流程与完整轨迹

```text
真实账号注册 / A 建房 / B 通过邀请加入
  → POST /api/saves（精确 script_id + script_version）
  → 通用 SaveService → PublicationStore.load → create_initial_state
  → 同一 Repository 保存各自独立 SaveRecord
POST /api/saves/{id}/commands
  → 现有身份与 Pair 成员检查
  → 先查询本存档当前 actor 的回执，再检查版本
  → apply_command 静态分派领域机制
  → append_public_history → 完整聚合 CAS
  → project_save 生成当前角色快照
```

先让灯塔 A 查日志、设90度 pulse，捕获整份存档与双方投影。再创建星轨，按以下操作完成；每次由 `Platform.accept()` 同时断言版本仅加1、回执 accepted_version 正确、本人回执可查、伙伴投影使用同一新版本：

1. A 查 station_log，B 查 power_board。
2. A 开 east 回声闸，B 分配 engine=false / sonar=true / lamp=true。
3. B scan_track，A install_rail bridge_2，进入 boarding。
4. B 切换 engine=true / sonar=false / lamp=true，confirm_signal。
5. A 选 track_2，B dispatch_train，进入 decision。
6. A/B 同票 rescue_detour 或 return_station，分别跑完整轨迹。

星轨完成后，灯塔完整聚合及双方投影仍与之前一致。接着补完灯塔滤镜、锁定、供电、维修、航道与共同选择，星轨完整聚合仍不变。关闭 TestClient 和仓储，再创建全新应用与独立连接，通过恢复密钥恢复两人身份，检查两份存档、角色、结局、版本和本人回执。原命令在完成后重试仍只确认旧回执，不重复推进。

这属于应用生命周期与数据库连接重开；SQLite 使用真实临时文件，Mongo 使用真实本地服务的随机隔离数据库。未宣称独立进程崩溃恢复或 Mongo 服务重启演练。

## 隔离与原子性证据

- 同房间不同剧本：在另一档操作前后比较整个 SaveRecord，不只比较 completed；版本、装置、公共历史、私线索与回执独立。
- 同 actor 跨档同 UUID：两档各自接受；完整命名空间仍为 `save_id + actor_id + request_id`。本档重试相同内容返回 duplicate，改内容返回 REQUEST_ID_REUSED；仅另一档存在的回执不能查到。
- 不同房间同剧本：非成员读档与命令均返回与不存在一致的404；列表只返回本人 Pair 的档，拒绝后聚合不变。
- 无效星轨命令与6/7单位预算：422稳定错误、没有接受回执，整个状态/历史/版本/回执与之前相等；从已有非零能源配置验证整组拒绝。
- 并发：两个真实独立仓储连接、两个应用，通过测试屏障让同版本写入竞争。不同请求只有一个提交，另一个 VERSION_CONFLICT；同一请求两次响应指向同一次提交。屏障只安排到达顺序，实际提交仍由原数据库 CAS 决定。
- DialogueTurn：在两个剧本分别以真实规则动作推进并提交各 A/B 标记记录；写一档时另一档完整不变，关闭重开后内容、角色和回执仍准确。仓储是内部聚合读取接口，此测试验证存储隔离与角色归属，不把测试中的角色筛选当作新的生产鉴权功能。真实 HTTP/NPC 私聊流程仍属于 T14，未实现。

## 精确版本与媒体

通过原发布流程真正封存测试2.0.0：修改私人线索文本、限制一个非通关必需的探索参数，并替换有效 WAV 字节。因此测试验证的是实际内容、规则和媒体变化，不是只改响应中的版本号。

两剧本分别验证：重开后旧档仍是1.0.0；旧私线索/投影不变、旧探索参数仍可用、受保护媒体仍读取旧字节；新房间的2.0.0使用新线索并拒绝旧参数。同 Pair/script 请求新版本得到 SCRIPT_VERSION_CONFLICT，省略精确版本得到 INVALID_INPUT，不能替换旧档。暂时移走临时目录中的1.0.0封存版本时，即使2.0.0存在，旧档仍明确 SCRIPT_NOT_FOUND，数据库原记录及旧回执保留；恢复原目录后旧档继续可读。不做迁移。

## 公共回顾与预算发现

`recap._FACT_STEPS` 增加 track_scanned / rail_installed / signal_confirmed / train_dispatched。它们仍只由已接受、audience=public 的确定性规则事件进入里程碑，不提升任何 private clue。`projection` 既有公共事实白名单取自同一映射，并按剧本已声明事实过滤，因此无需放松或复制校验。

真实通关进入 decision 后反复改票，使公开事件超过30条，最终完成两个结局。序列化/恢复后两人公共回顾一致，四个里程碑各保留一次；逐个移除任一关键项仍拒绝 INVALID_PUBLIC_HISTORY。旧灯塔历史 JSON 继续恢复，夹入外来星轨里程碑仍被拒绝。

B 初始 b_power 观察仅引导检查；发现 b_power_board 后显示能源开关与0/5预算。A 的个人部分前后不变，不能收到 B 完整功率板。领域测试和 HTTP 测试分别覆盖；合法公开的工程事实没有隐藏。

## 验证命令与实际结果

使用项目 Python3.12.4，无新增依赖。以下均在 backend 目录执行，Mongo URI 由进程环境注入本地回环地址，测试只清理各自随机创建的临时库。

初始红测确认：发布工厂冒用灯塔、预算提前出现、两个结局缺里程碑；另通过 PNG chunk CRC 检查发现旧测试 IDAT 校验码无效，已在测试工厂生成正确 CRC，不放松生产校验。

环境问题单独记录：第一次 Mongo 共享契约33项因本地 Docker Desktop 未启动、27017拒绝连接而报33 errors。启动已安装 Docker Desktop，检查既有 twoworlds-mongo 的回环映射与健康状态，真实 Ping 成功后重新执行。未删除/重建容器或卷，未改端口或业务数据。

恢复初期并行执行的 Mongo 共享契约还出现19通过、3失败、11初始化错误，底层日志显示索引请求超过既有3秒socket超时（一次3020ms）。停止额外API进程后串行复验；未改仓储超时。该次被中断的API专项不作为验收。另一次独立初始化诊断成功，耗时0.5秒，只使用随机临时库并清理。首轮API专项为24通过/17连接错误，也不冒称41项通过。

最终采用完整回归及其后独立复验的原始结果，**没有将多个运行拼成一次“1135通过/3失败”**。日志/JUnit只在忽略的 backend/work，不上传。

| 实际命令（backend目录） | 实际结果 | 退出码 |
| --- | --- | --- |
| `.venv/Scripts/python.exe -m pytest tests/domain/test_recap.py tests/domain/test_projection.py tests/domain/test_starline.py -q -p no:cacheprovider --basetemp=work/t092-domain-v1 --junitxml=work/t092-domain-v1.xml` | 212通过 | 0 |
| `.venv/Scripts/python.exe -m pytest tests/domain tests/content -q -p no:cacheprovider --basetemp=work/t092-domain-content --junitxml=work/t092-domain-content.xml` | 603通过：领域401、内容202；46.23秒 | 0 |
| `TWOWORLDS_TEST_BACKEND=sqlite`，`.venv/Scripts/python.exe -m pytest tests/storage/test_repository_contract.py -q -p no:cacheprovider --basetemp=work/t092-contract-sqlite --junitxml=work/t092-contract-sqlite.xml` | 33通过，真实SQLite文件；31.02秒 | 0 |
| `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=work/t092-full --junitxml=work/t092-full.xml` | **1138项：1131通过、3失败、4环境初始化错误、0跳过**；1428.49秒 | 1 |
| 同上全量中的 `tests/api/test_save_isolation.py` | 41项全部通过：SQLite19、真实Mongo19、发布/素材工厂3；是全量内的结果，不是独立专项成功声明 | 全量为1 |
| 下列4个Mongo节点独立复验，`-q -p no:cacheprovider --basetemp=work/t092-env-retest --junitxml=work/t092-env-retest.xml` | 4通过、0失败/错误；12.99秒 | 0 |
| `TWOWORLDS_TEST_BACKEND=mongo`，`.venv/Scripts/python.exe -m pytest tests/storage/test_repository_contract.py -q -p no:cacheprovider --basetemp=work/t092-contract-mongo-final --junitxml=work/t092-contract-mongo-final.xml` | 33通过，真实Mongo，含双剧本DialogueTurn重开；19.37秒 | 0 |
| `.venv/Scripts/python.exe -m ruff check src tests` | All checks passed | 0 |
| `.venv/Scripts/python.exe -m ruff format --check src tests` | 90 files already formatted | 0 |
| `uv lock --check --offline` | 24 packages，锁未改变 | 0 |
| `git diff --check`；只读打开默认PublicationStore.catalog | 无空白错误；正式目录0条 | 0 |

表中的环境变量使用PowerShell `$env:TWOWORLDS_TEST_BACKEND='mongo'` / `'sqlite'` 设置；`MONGO_URI`始终显式指向本机回环MongoDB。全量各组为：API315通过/4初始化错误，application115通过，content202通过，domain401通过，storage63通过，contracts35通过/3失败。全部新增50项通过（HTTP/工厂41、回顾7、投影1、共享仓储1），没有移除用例。

完整回归四个新增环境错误均发生在 `MongoRepository.__init__` 的fixture setup，未进入命令断言；安全异常包装没有逐例保留底层超时详情，不能据此宣称四项均已精确定位到某一条索引请求。独立复验的实际节点如下，用 `.venv/Scripts/python.exe -m pytest` 加引号包裹这些节点和表中参数执行，全部通过：

```text
tests/api/test_commands.py::test_receipt_precedes_version_and_returns_current_private_snapshot[mongo]
tests/api/test_commands.py::test_reused_id_changed_payload_is_rejected_before_rule_or_version[mongo-changes0]
tests/api/test_commands.py::test_reused_id_changed_payload_is_rejected_before_rule_or_version[mongo-changes1]
tests/api/test_commands.py::test_invalid_payload_never_writes_or_creates_receipt[mongo-changes7]
```

没有第二次重跑整套1138项；因此本次单次全量仍保留4个环境错误的记录，复验不能改写原始统计。并行/恢复负载下触及既有Mongo短超时是本轮环境限制，不通过增加超时、改断言或跳过测试解决。保留1条原anyio弃用警告。

### 与PR #21的1088项逐项比较

新增50，移除0。六项原失败转为通过，原 `tests/contracts/test_platform.py` 一行未改：

```text
test_starline_has_a_distinct_cooperative_solution[rescue_detour]
test_starline_has_a_distinct_cooperative_solution[return_station]
test_invalid_role_or_prerequisite_changes_neither_projection[unscanned-rail]
test_invalid_role_or_prerequisite_changes_neither_projection[early-dispatch]
test_power_budget_rejects_the_entire_allocation
test_scripts_and_pairs_have_independent_saves_and_receipts
```

保留3项业务失败，与历史相同：

| 用例（tests/contracts/test_platform.py） | 原因与后续范围 |
| --- | --- |
| test_websocket_uses_auth_frame_and_personal_projection_on_reconnect | WebSocketDisconnect；T12未实现 |
| test_outsider_websocket_never_receives_a_snapshot | WebSocketDisconnect；T12未实现 |
| test_demo_npc_is_private_and_cannot_change_game_facts | talk返回422 UNKNOWN_ACTION；T14未实现 |

新增业务断言失败0；新增环境错误4已逐项独立复验通过。没有删除、skip、xfail或削弱历史断言，也不将本地结果描述为GitHub Actions已全部通过。

## 学习与复现

建议顺序：`tests/save_support.py` → `tests/api/test_save_isolation.py` → `domain/mechanics/starline.py:observations` → `domain/recap.py` → `tests/domain/test_recap.py` → 共享仓储契约新增用例。通用调用可对照已有 `application/saves.py`，本轮没有复制星轨接口。

在 backend 设置本地 `MONGO_URI` 后运行 `.venv/Scripts/python.exe -m pytest tests/api/test_save_isolation.py -q -p no:cacheprovider --basetemp=work/t092-self-review` 可观察两个适配器的完整 HTTP 流程。可在 `test_two_stories_complete_independently_then_restore_after_real_close` 设断点，比较 repo.get_save() 整份聚合与 A/B 个人投影；临时测试资源不需要下载或付费模型。

未完成：正式媒体与许可、浏览器/手机播放、前端切档防迟到响应、WS、NPC/AI、生产部署、独立进程崩溃恢复与真实用户试玩。下一阶段建议 T10；本轮交付后停止，等待用户学习/审查，不自动执行。
