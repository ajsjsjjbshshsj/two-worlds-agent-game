# T02 · 《跨时灯塔》纯规则引擎

2026-11-01。用户明确授权本轮完成T02；不开始T03、数据库、API、前端或AI。

## 设计与执行计划

PR #6已重新核实合并，最新远端基线`90cba7c0513109a8fcda360467b5bddd9ed943f3`；新分支`codex/t02-lighthouse-engine`，复用干净隔离工作树。主目录原有改动保留，不推送旧本地codex/bootstrap历史。

统一入口：`apply_command(state, script, actor_role, action)`返回可解包的`CommandResult(state, events)`，或抛`DomainError.code`。`action`是且仅是`{kind,args}`；HTTP层的request_id/expected_version、成员身份、回执与CAS均不在本轮。actor_role必须来自后续认证/成员关系，命令不能自带role/account_id/完成标志。

领域状态与内容定义分开：复用既有ScriptVersion、条件/效果与Role/Audience/Scalar等类型。运行状态使用冻结模型与tuple，内部值只能是不可变原子值，避免冻结外壳中的dict仍被改写。初始化完全来自内容初值。效果以有限类型分派执行，不使用eval。

每次命令：核对剧本绑定/状态 → 解析命令、动作、角色/阶段/严格参数 → 检查声明前置与发现条件 → 在新状态上应用效果 → 同票结算/场景条件检查 → 生成带audience的当前观察及事件 → 确认实际变化 → 版本只加1。错误和无变化不返回新状态，不污染原状态或事件历史。

灯塔机制只负责固定机关的领域约束和反馈：A调角度/光型改变B当前光束观察；B供电改变A检修条件，A修复开放B扫描；锁定后不再更改第一阶段配置。`fast`不属于内容声明允许成功的参数，明确拒绝为REPAIR_MODE_UNSAFE。投票仅记录本人选择，两票一致才统一写completed/ending_id事实和完成场景；两种结局均合法。

当前观察与事件都是服务端领域产物，保留audience，不实现玩家快照/可用动作投影或分享。后续T03必须过滤，不能把CommandResult中的完整世界状态直接发给客户端。灯塔仍因28项媒体缺失而未发布，本轮测试显式加载待发布定义；纯规则执行不等于可玩发布或视听验收。

计划：

- [x] 阅读约定/玩法/架构/验收/Schema/正式内容，核对Git与PR。
- [x] 先写真实轨迹与拒绝测试，确认缺引擎时失败。
- [x] 实现models/errors/engine、mechanics/common与lighthouse，只处理T02动作。
- [x] 证明两个结局、角色独有贡献、双向反馈、严格参数、失败不变、配置恢复与版本规则。
- [x] 新增、内容、全量后端及Ruff检查完成，更新文档/交接。
- [x] 已提交并创建[PR #7](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/7)，停下等待用户手动审查/合并和学习。

## 实测记录

环境：Windows、Python3.12.4、Pydantic2.14.1、pytest9.0.2、Ruff0.15.4；沿用原22包开发环境，无新增运行依赖，不修改pyproject/uv.lock。领域代码仅使用Python计算和既有Pydantic内容/冻结模型，不导入Web、存储或AI适配器。

| 执行 | 实际结果 |
| --- | --- |
| 开始前全部内容 | 191 passed |
| 实现前新增首批行为测试 | 107 failed，缺engine/errors实现，非setup errors |
| 首实现的行为测试 | 107 passed |
| 扩展可达图、后段失败、输入与I/O检查 | 117 passed |
| 不支持的光路值/新内容错误码 | 先2 failed、1个依赖隔离检查通过；普通KeyError修为DomainError/通用错误说明，随后通过 |
| 绕过模型构造的缺字段快照 | 先1 failed，版本绑定前访问缺字段触发AttributeError；改为先严格校验状态后核对版本，随后通过 |
| 最终T02领域测试 | 123 passed，0 errors/0 skipped |
| 最终原内容测试 | 191 passed，原用例无修改 |
| 最终全量后端 | 314 passed、38 failed、0 errors、0 skipped，1条既有Starlette/AnyIO弃用警告 |
| 38个失败逐项核对 | 全因缺twoworlds.api.app/storage.sqlite，未进入HTTP断言；没有删除/skip/xfail/假服务 |
| Ruff检查与格式 | check通过，35个Python文件format --check通过 |
| 离线锁/依赖检查 | 22包锁一致且兼容，无新增依赖 |
| 文档/范围/凭证模式检查 | 22份Markdown、171个本地链接/代码块/JSON通过；2个原始聊天本机链接按约定排除，16个交付路径无同期主目录修改，凭证模式无匹配 |

本地证据：`work/t02-domain-verified.xml`、`work/t02-content-verified.xml`、`work/t02-all-verified.xml`；状态图统计`work/t02-state-graph.json`。这些都被忽略，不提交临时记录。

## 修改与阅读入口

| 文件 | 负责什么 |
| --- | --- |
| [models.py](../../backend/src/twoworlds/domain/models.py) | GameState/当前值/当前观察/领域事件；不可变tuple与原子值，可解包CommandResult |
| [errors.py](../../backend/src/twoworlds/domain/errors.py) | 稳定DomainError.code与不回显私密输入的说明；内容可声明新错误码 |
| [engine.py](../../backend/src/twoworlds/domain/engine.py) | 初始化、剧本/快照校验、严格命令边界、统一接受版本与结果 |
| [common.py](../../backend/src/twoworlds/domain/mechanics/common.py) | 使用原Condition/Effect；参数、前置、发现、装置/事实、场景与同票结算 |
| [lighthouse.py](../../backend/src/twoworlds/domain/mechanics/lighthouse.py) | 当前光束/供电/维修/扫描观察与锁定后阶段不变量 |
| [mechanics包](../../backend/src/twoworlds/domain/mechanics/__init__.py) | 固定机关模块边界，不按客户端字符串动态加载代码 |
| [test_lighthouse.py](../../backend/tests/domain/test_lighthouse.py) | 真实正式内容驱动的123项测试、不同轨迹、可达状态与依赖隔离 |
| README、后端/测试README、docs02/03/04/05、交接及本报告 | 当前实现状态、边界、验证与学习记录 |

内容Schema、_references、原加载器、灯塔JSON、发布/打包系统、旧测试和依赖/锁均未改。灯塔定义仍是未发布草稿，测试显式加载它，不绕过缺媒体发布保护。

## 一次操作如何执行

以B供电tower为例：入口根据ScriptVersion选出route_power声明，确认B角色、repair阶段和严格target选项；Condition检查信号已锁定。SetDevice只写B设备的新tuple，原输入还保留旧值。灯塔机制据新供电产生A的“时钟箱有电”观察与B的能源反馈，事件保留各自audience。成功后统一version+1并返回；不是在原state上赋值。

有电时A检查齿轮才会发现a_clock_gears、获得私有repair_tools_ready；steady维修才写clock_repaired。B随后得到当前扫描就绪反馈，仍要独立confirm_route。切断供电只改变当前可用性，不清除维修成果；切回即可继续。

共同选择先按actor_role替换本人那一票；单票或分歧不完成，同票统一生成确定结局、completed/ending_id事实、运行完成标志和终场。返回中仅一个game_completed事件，完成状态再提交任何写命令都拒绝。这里的“统一”是单次纯函数结果一致，不是数据库提交/网络幂等保证。

### 版本、不可变性与错误

- 运行模型及其StateValue/DeviceState/Observation/Event都冻结，内部tuple/原子值不留可变dict；不会出现仅冻结外壳却仍能改写内部事实的问题。
- 每个效果在新对象上暂算，后续场景条件/状态校验失败则整次拒绝，已暂算的事实和事件不外泄。测试有“先暂算signal_locked、目标场景条件再失败”的例子。
- 不变设置、重复查看发现、同票重投等被拒绝，不增加version；合法但未解谜的调角/滤镜/供电试验则真实改变配置，所以增加version。
- 参数按现有定义逐项验证，拒绝布尔冒充整数、字符串数字、浮点角度、缺参/额外参数。fast只会拒绝，不套用steady效果。
- action只允许kind/args，额外role、actor_role、account_id、player_id、state、completed等拒绝。actor_role自身仅接受小写a/b，不能据此声称已认证真实玩家。
- 典型错误：ROLE_FORBIDDEN、ACTION_UNAVAILABLE、INVALID_ARGUMENTS、CLUE_NOT_DISCOVERED、SIGNAL_UNSTABLE、CLOCK_UNPOWERED、TOOLS_NOT_READY、REPAIR_MODE_UNSAFE、NO_STATE_CHANGE、SAVE_COMPLETED。库只支持灯塔，其他剧本未注册。

### 事件与私密边界

发现线索事件只给所属角色；repair_tools_ready事实事件沿用FactDefinition的audience=a；设备变化沿用DeviceDefinition的角色，方向观测仅B，A不自动获得B的目标/方向。共同里程碑、公开投票与结局才是public。事件均绑定本次接受的version。

测试只在测试端按audience检查，不实现生产玩家投影。CommandResult.state本身含完整世界，events也含双方事件，不能直接发给A或B。T03需要产出真正的PlayerSnapshot/分享/公开回顾；HTTP/WS/AI均需复用它。T02不提供可用动作投影，也不操作私聊、素材路径或播放。

## 可达性证据

按实际Schema枚举动作的有限参数组合，对所有成功后继状态遍历。状态签名只排除version这个单调计数器，保留所有业务值/发现/投票/当前观察；T02没有以version数值作为机关条件。错误参数/fast等不会产生新世界，已另行拒绝测试。

| 可操作角色 | 可达世界状态 | 成功状态边 | 可达结局 |
| --- | --- | --- | --- |
| 只有A | 9 | 57 | 无 |
| 只有B | 4 | 7 | 无 |
| A和B | 54 | 333 | guide_now、wait_tide |

逆向遍历证明：上述54个世界中的所有未完成状态都能继续到达任一合法结局。12步验收轨迹与16步不同探索顺序/额外试验/反向投票轨迹均通过，规则不检查固定步数/密码。

证明范围只限当前灯塔内容和纯规则；不证明趣味/15分钟时长、未来命令额度、并发、持久化、身份所有权或其他剧本。单一角色必要贡献不等于阻止一个真人持有两个身份。

## 自己运行与学习

在项目根目录运行：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain -q --basetemp=work/pytest-t02-domain-verified --junitxml=work/t02-domain-verified.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q --basetemp=work/pytest-t02-content-verified --junitxml=work/t02-content-verified.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short --basetemp=work/pytest-t02-all-verified --junitxml=work/t02-all-verified.xml
.\backend\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/hatch_build.py
.\backend\.venv\Scripts\python.exe -m ruff format --check backend/src backend/tests backend/hatch_build.py
```

预期领域123通过、内容191通过；全量后端314通过、38个已知失败。basetemp是会清空重建的专用临时目录，不放笔记。真实文件加载/目录联接测试需本机相应读取权限，不应放宽路径规则。

建议阅读：先看GameState，再跟踪apply_command的输入校验、common的有限条件/效果、lighthouse的反馈，最后回到测试at/accept/reject及两角色/全状态遍历。测试还在新进程阻止FastAPI/httpx/存储/AI模块导入后执行规则，并在操作时禁止文件/网络访问，均实际通过；无需数据库、Web服务或模型密钥。

下面是实际执行过的12步轨迹的可复制版本。角色标签只是内部测试输入；实际产品必须由后续身份/成员服务决定角色。

```powershell
@'
from pathlib import Path
from twoworlds.content import loader
from twoworlds.domain.engine import create_initial_state, apply_command
script = loader.ScriptLoader(Path(loader.__file__).parent / 'scripts').load('lighthouse', '1.0.0')
state = create_initial_state(script)
steps = [
    ('a', 'inspect', {'target': 'maintenance_log'}),
    ('b', 'inspect', {'target': 'sea_chart'}),
    ('a', 'set_emitter', {'angle': 0, 'pattern': 'pulse'}),
    ('b', 'set_filter', {'filter': 'amber'}),
    ('a', 'set_emitter', {'angle': 90, 'pattern': 'pulse'}),
    ('b', 'lock_signal', {}),
    ('b', 'route_power', {'target': 'tower'}),
    ('a', 'inspect', {'target': 'clock_gears'}),
    ('a', 'repair_clock', {'mode': 'steady'}),
    ('b', 'confirm_route', {}),
    ('a', 'vote_ending', {'choice': 'guide_now'}),
    ('b', 'vote_ending', {'choice': 'guide_now'}),
]
for role, kind, args in steps:
    state, events = apply_command(state, script, role, {'kind': kind, 'args': args})
    print(state.version, role, kind, state.scene_id)
print(state.completed, state.ending_id)
'@ | .\backend\.venv\Scripts\python.exe -I -X utf8 -
```

实际输出依次为calibration版本1～5、repair版本6～9、decision版本10～11，版本12 completed，最后True guide_now。替换两人的结局选项可得到wait_tide；只有一人或两票不同不会完成。

## 当前限制与下一环节

T02范围内没有未解决的测试失败；仍有38个后续实现缺失的契约失败。只做了源码级测试，本轮未重新构建/安装发行物，旧T01.2.3产物不能称本轮新版。无真实图片/音频、许可/播放、存储、HTTP/WS、前端、AI、真机或部署验收。

角色所有权、房间满员、会话、请求ID/expected_version、回执、CAS和事件提交后投递由后续环节负责。Save.version和GameState.version后续应使用同一接受版本，不能各自再递增一次；重新对旧状态计算同一纯命令不是网络幂等保证。完整游戏状态不能直接外发。

下一环节T03：角色快照投影、分享本人已发现可分享线索、按公共里程碑生成回顾，并隔离伙伴秘密及媒体引用。本轮未实现这些功能，完成PR后停止，等待用户审查和明确继续。
