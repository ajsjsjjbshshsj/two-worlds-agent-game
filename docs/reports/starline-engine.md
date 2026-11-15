# T09.1 · 《末班星轨》正式内容与纯Python规则

2026-11-15。仅完成T09.1，不执行T09.2、仓储/身份/房间/API重构、前端、WS、NPC、AI或正式素材制作。

## 基线、设计与文件

已通过GitHub核实PR #20合并，实际合并提交为`cf79227b2d2f17c76c597e10dff99ef6f6b2c67e`。Git默认连接重置后，以命令级schannel TLS后端和公共DNS实测的备用GitHub地址成功fetch，TLS验证未关闭，未修改用户系统或Git全局配置。从最新origin/codex/bootstrap在干净隔离工作树`F:\two-worlds-agent-game\work\pr-t01-1-schema`创建`codex/t09-1-starline-domain`；不携入旧本地900d517/fcc1a97历史，主目录用户未提交修改保留，未使用子代理。

用户已给定文档02第5节及本任务完整规格。本轮按该既定设计实施：所有普通前置和效果仍由既有common处理，只有功率算术与错误轨道错误分类需专用命令前检查；场景反馈和因果一致性各自独立实现。无需动态插件框架，也不复制引擎或让JSON执行Python代码。

| 文件 | 职责 |
| --- | --- |
| backend/src/twoworlds/content/scripts/starline/1.0.0.json | 从零编写的正式内容定义：四场景、3装置、2私线索、8事实、10动作、2结局、双视角与25项媒体声明 |
| backend/src/twoworlds/domain/mechanics/starline.py | 服务端5单位功率、错轨检查、A/B观察与星轨状态不变量 |
| backend/src/twoworlds/domain/engine.py | 静态注册lighthouse/starline，初始化、验证、命令完成统一分派机制；补齐初始化TypeError的安全领域错误边界 |
| backend/src/twoworlds/domain/errors.py | 7个星轨稳定错误码与安全文案，不附带原始状态/命令/私线索 |
| backend/tests/domain/test_starline.py | 真实规则轨迹、预算8组合/两阶段、原状态不变、两结局、角色权限、恢复与投影等85项 |
| backend/tests/content/test_starline_content.py | 正式文件加载、精确版本、引用拒绝、初态、真实结局路径与媒体待发布边界11项 |
| docs/02、docs/04、开发交接、README、backend/README | 状态、T09.1/T09.2拆分与学习入口；玩法规格本身不变 |

common.py、lighthouse.py、GameState、DomainEvent、CommandResult、角色投影、存储、身份、房间与命令API均未修改。临时编写辅助与测试日志只在忽略的backend/work目录，不进入提交。

## 星轨机制与调用关系

与灯塔的光路/供电不同，星轨以“功率预算不可同时启动两个大设备”逼迫阶段切换。engine=3、sonar=3、lamp=1，总预算5，由Python计算，不接受客户端提供budget或total。声呐/灯为4单位，引擎/灯也为4；引擎/声呐为6（加灯为7），整组失败，不能自动关闭其他设备修正。

```text
ScriptLoader.load("starline", "1.0.0") → 完整Schema和引用校验
create_initial_state → 静态_MECHANICS → 星轨观察/不变量 → GameState
apply_command
  → 重建并验证冻结的script/state
  → resolve_action / 角色 / 场景 / 严格参数
  → common.require_preconditions
  → starline.check_action（完整预算组、错误轨道）
  → common.apply_effect（发现线索、装置、事实、场景）
  → common.settle_votes（仅投票动作）
  → 星轨观察 / version+1 / 完整状态校验
  → CommandResult(新state, 按接受版本标记的events)
```

`_MECHANICS`仅包含显式导入的两个模块，不用JSON字符串import/eval；未注册的合法Identifier（如os）返回SCRIPT_UNSUPPORTED。保留原ScriptVersion重建冻结对象的边界，不恢复“只验证、不使用验证结果”的旧问题。

### 四场景与双向因果

1. survey：A查站台日志后才可开east回声闸；B查功率板后才能分配能源。只有east、sonar=true、engine=false才可扫描。扫描实际发生后才写入track_scanned和公开工程事实scanned_segment=bridge_2。
2. A必须等待扫描后才可安装bridge_2。安装写rail_installed并进入boarding；set_echo_gate仅在survey可用，因此安装后的闸位不能再由玩家更改。
3. boarding：B点亮信号灯后确认蓝色双闪，写入signal_confirmed和公共confirmed_signal。A按私人站台标识选择track_2；B还必须切换到engine=true、sonar=false、lamp=true才能接车。错误轨道可恢复，不存在固定密码绕过整条动作链。
4. 接车写train_dispatched，进入decision。任一方可修改自己的投票，分歧不结束；rescue_detour或return_station只要两人一致都能完成，写入唯一ending_id后锁定世界。

站台私日志包含三个灯号/轨道映射，列车私功率板包含设备成本与本地操作说明；完整私线索不自动进入伙伴观察或投影。A开闸单次操作改变B的扫描反馈；B扫描改变A的安装反馈；B确认改变A的轨道可用性；A对位改变B的接车反馈。测试分别比较这些单次对方操作前后的个人观察，不用多步混合变化代替因果证明。发现线索事件保留本人audience；扫描段位和确认灯号通过明确public效果公开。

### 保留成果与锁定边界

扫描事实不因后续关闸、改能源而消失。扫描后的survey仍允许调整闸位，安装按文档仅要求已扫描；安装后锁住当时闸位，不擅自新增“安装时必须仍为east”的前置。已确认灯号不会因临时关灯抹除，但接车必须满足当前能源配置。decision/completed不允许继续分配能源或改轨道。

不变量检查完整世界：预算不超5、扫描/确认标志与对应工程事实一致、装轨依赖扫描、信号依赖装轨、非默认轨道依赖已确认信号、装轨/接车与场景一致、接车后轨道与能源正确、投票只在允许阶段；未完成/已完成/投票/结局的一致性仍由通用引擎检查。它拒绝不一致快照，不宣称能用一个值对象证明完整历史来源；可信上层仍负责身份与存档读取，客户端没有提交完整GameState的入口。

## 完整通关轨迹

以下版本仅说明这一条具体轨迹，每次有效变化统一+1，不把总步数当解锁条件：

| 接受后版本 | 角色 / 操作 | 结果 |
| --- | --- | --- |
| 0 | 初始化 | survey，closed、三个开关false、无发现/投票 |
| 1 | A inspect target=station_log | 本人日志解锁 |
| 2 | B inspect target=power_board | 本人能源控制解锁 |
| 3 | A set_echo_gate position=east | B得到回声条件 |
| 4 | B allocate_power false/true/true | 声呐/灯，功率4 |
| 5 | B scan_track | bridge_2经实际扫描公开，A可安装 |
| 6 | A install_rail segment=bridge_2 | boarding，闸位锁定 |
| 7 | B allocate_power true/false/true | 切到引擎/灯，功率4 |
| 8 | B confirm_signal | 公开蓝色双闪，A可选轨 |
| 9 | A set_platform track=track_2 | B得到对位反馈 |
| 10 | B dispatch_train | decision |
| 11 | A vote_ending choice=rescue_detour | 仅一票，未完成 |
| 12 | B vote_ending choice=rescue_detour | completed，唯一救援结局 |

把两票均改为return_station可完成归站结局；测试实际执行两条完整轨迹。另覆盖两种读记录顺序×两种开闸/分配顺序、错误闸位修正、关灯再恢复、错轨改正、投票分歧与改票。单角色可达世界（包括分享）均遍历到终止，无法独自完成；不将这些测试描述为所有双人可达状态的穷举证明。

## 错误与不可变性

| 错误 | 场景 |
| --- | --- |
| POWER_BUDGET_EXCEEDED | 已授权能源动作提出6/7单位组，在任何set_device效果前拒绝 |
| WRONG_TRACK | 接车一般前置已满足，但轨道不是track_2 |
| ROLE_FORBIDDEN | A执行B动作或B执行A动作 |
| ACTION_UNAVAILABLE | 在错误阶段操作，例如boarding后改回声闸 |
| INVALID_ARGUMENTS | 错段位/未知轨道、把1或字符串当布尔、漏参数/加budget等 |
| CLUE_NOT_DISCOVERED | 未看本人记录就操作装置 |
| SCAN_UNAVAILABLE / TRACK_NOT_SCANNED | 缺扫描条件 / 提前安装 |
| SIGNAL_UNAVAILABLE / SIGNAL_NOT_CONFIRMED | 没灯就确认 / 确认前设置轨道 |
| DISPATCH_NOT_READY | 导轨、信号或当前接车能源前置不足 |
| NO_STATE_CHANGE / ALREADY_DISCOVERED | 重复设置、扫描、确认、投票或检查 |
| SAVE_COMPLETED / INVALID_STATE | 结束后修改 / 不一致的完整快照 |

所有失败测试比较完整GameState及输入命令，不只检查completed；失败不生成CommandResult、不改原版本。成功不原地修改传入state或action，多个有限效果完成后只递增一次。领域层不创建数据库回执，本轮不宣称已经完成星轨HTTP失败无回执的集成验收。

## 实测与历史基线

使用项目Python3.12.4及既有锁，无新增依赖。先观察缺JSON的CONTENT_NOT_FOUND，再观察Schema已通过但统一引擎仍拒绝SCRIPT_UNSUPPORTED，随后添加静态分派/机制。沙箱路径解析曾阻止测试根目录访问，沿用获批准的真实本机测试方式，未降低路径检查。

| 命令 / 组别 | 实际结果 |
| --- | --- |
| 星轨domain + content专项 | 96通过（领域85、内容11），0失败；2.08秒 |
| 原test_lighthouse.py | 123通过、0失败；5.12秒 |
| 全部tests/content | 202通过、0失败；10.51秒 |
| Ruff check src tests | 通过 |
| Ruff format --check src tests | 89个文件已格式化 |
| uv lock --check --offline | 通过，24包，锁文件不变 |
| 只读audit_media与正式目录检查 | 25声明、0实际文件、0已审核许可，正式目录0条；未发布内容 |
| 完整后端 | 1088项：1079通过、9失败、0错误、0跳过；672.83秒，1条既有anyio弃用警告 |
| 全量中的全部domain / content | 393 / 202通过，均0失败 |
| 全量中的API / application | 278 / 115通过，均0失败 |
| 全量中的仓储 | 62通过：SQLite共享32+专项12，真实Mongo专项18；未改仓储 |
| 全量中的既有契约 | 29通过、9项后续边界失败，逐项如下 |

首次新增测试运行有4条来自测试中空match正则的警告，已经删除无意义的match参数，保留领域错误码和完整状态断言；最终专项无该警告。不删除旧测试、skip、xfail或降低断言来消除后续失败。

用户给定T08.3全量基线988项=979通过/9失败；PR #20随后审查修复还新增4项已获合并的HTTP参数组合（该次只做169项专项，没有重跑全量）。因此本轮比较旧JUnit时必须区分这4项既有审查测试与本轮96项新增测试，不将全部新增数都算给T09.1。旧9项为T09星轨HTTP六、T12 WS二、T14 NPC一；本轮未发布星轨，不能为了变绿把源JSON或临时素材直接注册为正式发布版本。

对照work/t083-all.xml：新增用例100=本轮85领域+11内容+已合并PR #20的4个媒体HTTP用例，移除0；新增失败0、消失失败0，旧通过用例没有回归。以下均位于tests/contracts/test_platform.py，失败ID和原因与988项历史基线一致：

| 用例 | 归属与本轮真实阻塞 |
| --- | --- |
| test_starline_has_a_distinct_cooperative_solution[rescue_detour] | 星轨HTTP后续验收；测试发布库未封存starline，建档404 SCRIPT_NOT_FOUND |
| test_starline_has_a_distinct_cooperative_solution[return_station] | 同上，404 SCRIPT_NOT_FOUND |
| test_invalid_role_or_prerequisite_changes_neither_projection[unscanned-rail] | 同上，404 SCRIPT_NOT_FOUND，未执行后续HTTP规则断言 |
| test_invalid_role_or_prerequisite_changes_neither_projection[early-dispatch] | 同上，404 SCRIPT_NOT_FOUND，未执行后续HTTP规则断言 |
| test_power_budget_rejects_the_entire_allocation | 同上，404 SCRIPT_NOT_FOUND，未执行HTTP回执断言；本轮纯领域完整状态拒绝已验证 |
| test_scripts_and_pairs_have_independent_saves_and_receipts | T09.2跨档；星轨建档404 SCRIPT_NOT_FOUND |
| test_websocket_uses_auth_frame_and_personal_projection_on_reconnect | T12，握手WebSocketDisconnect |
| test_outsider_websocket_never_receives_a_snapshot | T12，握手WebSocketDisconnect |
| test_demo_npc_is_private_and_cannot_change_game_facts | T14，talk返回422 UNKNOWN_ACTION |

这些失败不能说明星轨纯规则尚未完成，也不能因纯规则已通过就称HTTP/跨档通过。本轮未修改tests/contracts、临时发布工厂、API或仓储来提前完成T09.2。实际pytest全量退出码为1，不宣称全量或GitHub Actions全绿。

复现命令（backend目录；每轮basetemp使用新的专用临时目录）：

```powershell
.venv/Scripts/python.exe -m pytest tests/domain/test_starline.py tests/content/test_starline_content.py -q
.venv/Scripts/python.exe -m pytest tests/domain/test_lighthouse.py -q
.venv/Scripts/python.exe -m pytest tests/content -q
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/python.exe -m ruff format --check src tests
uv lock --check --offline
$env:MONGO_URI='mongodb://127.0.0.1:27017'
$env:TWOWORLDS_TEST_BACKEND='sqlite'
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=work/t091-local-all --junitxml=work/t091-local-all.xml
```

本地JUnit与日志位于backend/work/t091-*，忽略且不上传；实际执行使用-p no:cacheprovider和独立basetemp避免旧缓存/沙箱路径问题。以上纯领域/内容专项无需数据库；完整回归使用既有真实SQLite和MongoDB，不用Mock替代数据库。

## 素材与未完成边界

25项MediaAsset声明含每场景双角色背景、条件图像、环境音、事件音效、开场/结局旁白与字幕；content_version均1.0.0。source明确待制作，license明确待核验、禁止生产发布，不编造版权或实际文件。

没有制作图片/音频，没有将临时测试素材填进正式资源，没有发布星轨。默认PublicationStore仍为空。正式内容定义由ScriptLoader读取供纯领域执行；发布与媒体文件/审核是独立边界，不能因JSON可加载就声称HTTP目录/建档可用。

T09.2存档隔离/版本相关工作保持未开始；没有修改SQLite/Mongo、身份、房间、命令API、回执或同步。未验证星轨HTTP完整流程/跨档、真实媒体权限与播放、前端/WS、AI或生产部署，也未证明目标游玩时长与手机体验。QA-G07/G08/G09只记录内容与纯领域证据，QA-S04/S05仍待后续。

## 学习顺序与检查点

1. 正式JSON：看power_panel、allocate_power、scan_track、install_rail和两个结局的因果声明。
2. engine.py：_MECHANICS、apply_command、_apply_supported_command；了解通用流程只执行受信任的显式机制。
3. starline.py：check_action在任何效果前检查整组功率，observations按角色算反馈，validate_invariants拒绝不一致快照。
4. common.py：require_preconditions、apply_effect和settle_votes仍负责普通规则和投票；并未复制实现。
5. test_starline.py：TRACE、accept/reject、八种功率组合、单角色遍历与恢复测试；content测试还以真实finish调用证明两结局路径。

可以在backend目录运行专项pytest，并在accept/reject断点查看旧state/new state、事件audience与version。只对纯规则操作，不需要启动API或提供账号；没有实际演示服务地址。

本轮分支codex/t09-1-starline-domain，独立PR目标codex/bootstrap。完成报告、验证和PR后停止等待用户学习/审查，不自动开始T09.2，不合并PR。
