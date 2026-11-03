# T03.1 · 双角色信息投影

2026-11-03。范围仅限纯 Python `project_save(state, script, role)`，用户附件已明确授权设计与执行。

## 设计与执行计划

- [x] 阅读 AGENTS、交接、玩法/架构/验收、内容定义和 T02；核实 PR #7 已合并为 `b79ae0403a29e19a4520cdc4659293e32093785e`，从远端基线建立 `codex/t03-1-player-projection`，复用干净隔离工作树。
- [x] 先写正式内容驱动的投影测试，确认缺少入口时失败；覆盖全 JSON 私密标记、共享合法性、装置/观察、动作/媒体条件、不可变与非法状态。
- [x] 将 T02 的完整状态验证公开为 `validate_state`，命令与投影复用，不复制不变量；不改 Schema、引用校验、加载器或灯塔机关。
- [x] 构造独立的冻结展示模型；只逐字段复制本人/已公开内容。装置内部用冻结行，序列化为既定 `{device_id:{field:value}}` 对象；没有对话时只允许空列表。
- [x] 动作只输出 id/kind/参数白名单，按角色、场景、前置筛选。媒体按本人场景演出、资源角色/场景/条件与 cue 条件筛选，只返回安全引用；背景不可见时为 null，空 cue 不返回。
- [x] 新增测试、全部领域、全部内容、完整后端、Ruff/格式与锁检查；区分原有 38 个缺 API/SQLite 实现失败。
- [ ] 更新任务/架构/验收/交接及阅读入口；提交、推送、创建 PR，停在学习检查点。

没有实现线索分享命令、公共回顾、对话历史、认证、存储、HTTP/WS/AI 或媒体文件/播放。完整 QA-P01、QA-P02～P04、QA-M03 均不能据此标记完成。角色参数须由后续可信身份/成员层提供；媒体 ID 不构成读取凭证。

## 输入、过滤与输出

入口为`project_save(state: GameState, script: ScriptVersion, role: str) -> PlayerSnapshot`。没有持久化Save对象、save_id、内部回执或成员信息，也不为本轮创建这些模型。

1. 调用公开`engine.validate_state`。它从T02原有入口提取，仍校验事实/设备/线索引用、版本绑定、共享子集/去重/shareable、阶段与结局不变量、当前动态观察；额外防止ScriptVersion通过model_copy/construct绕过Schema引用约束。所有错误均用不含原始秘密的DomainError拒绝。
2. 验证role严格为字符串a或b。只选本人SceneDefinition.observations、本人Observation.audience、本人DeviceDefinition.role与已声明字段。
3. 本人线索必须属于该角色且在discovered_clues中；公共线索仅从已校验shared_clues中复制{id,text}。测试使用内存共享状态验证投影，**没有执行或实现share_clue**。
4. 动作按roles/scene_ids/preconditions筛选；输出新ActionView及ParameterView，不附加条件、效果或错误码。参数选项是可试调白名单，并非承诺每个选项都将改变状态；执行仍须apply_command复核，重复值保持NO_STATE_CHANGE。
5. 只读当前scene/role的ScenePresentation，cue先过自己的条件，资源再过audience/scene_ids/conditions。输出MediaReference仅asset_id/kind/alt_text/transcript，不含path/source/license。被拒绝的资源ID、字幕与空cue的ID/说明均不返回；同cue部分资源被拒绝时只保留获准引用。
6. 构造独立冻结快照。内部列表全部使用tuple和冻结子模型；personal.devices为独立DeviceView/DeviceFieldView，序列化时新建JSON对象以保持文档03的对象契约。JSON重新加载会严格验证结构；dialogue模型只接受空列表。输出顺序稳定，cue内部资源顺序与内容声明一致。

校验会在服务端内存中完整读取世界与内容，但这些对象和序列化结果不作为输出。命令和投影共用校验避免两套不变量漂移；当前小剧本逐次校验而不缓存可被绕构造替换的对象，代价是每次都会检查整份声明。没有为未实现的星轨规则承诺投影支持。

例子：A查维护日志后，A.personal.clues出现日志；B的整份JSON没有日志正文，B仍需自己查航道图。A调90°/pulse、B设amber后，B观察与beam_90媒体引用开放；A仍只看到自己的发射器。B把电送到tower后，A的时钟观察、inspect_gears动作和tower_powered引用一起开放，但A不会拿到B的供电台内部字段。

## 文件与学习阅读顺序

1. [projection.py](../../backend/src/twoworlds/domain/projection.py)：先看PlayerSnapshot、PublicView/PersonalView，再看project_save逐项构造与_actions/_presentation筛选。
2. [engine.py](../../backend/src/twoworlds/domain/engine.py)：validate_state、_require_script，以及apply_command如何共用入口；原状态不变量仍只有一份。
3. [test_projection.py](../../backend/tests/domain/test_projection.py)：at用正式内容和真实命令推进；完整JSON的PRIVATE_MARKER检查、双向反馈、共享状态与媒体条件用例。
4. [架构8.1](../03-技术架构与数据接口.md#81-t031已实现的纯领域投影契约)、[任务拆分](../04-开发阶段与任务清单.md)：T03.1与T03.2的接口和学习边界。

另更新README、backend/README、测试验收文档与交接。未修改content/schema.py、_references.py、loader.py、正式灯塔JSON、mechanics、旧测试、pyproject/uv.lock或构建系统；没有新增依赖。

## 实际验证（2026-11-03）

执行目录：`F:\two-worlds-agent-game\work\pr-t01-1-schema`，分支`codex/t03-1-player-projection`；Python3.12.4。不是在主目录的本地旧历史上提交。下列pytest的basetemp由pytest清理，仅放临时测试数据。

| 检查 | 实际结果 |
| --- | --- |
| T03前领域+内容基线 | 314 passed |
| 首轮先写测试再运行 | 79 failed，均缺twoworlds.domain.projection；随后79 passed |
| 补充严格输入与纯函数边界 | 89 passed/1 failed，装置混合类型键排序抛TypeError；修复后90 passed |
| 新投影测试 | 90 passed，0失败/错误/跳过 |
| 全部领域 | 213 passed（原123+新90），0失败/错误/跳过 |
| 全部内容 | 191 passed，0失败/错误/跳过 |
| 完整后端 | 404 passed / 38 failed，合计442；0 errors/0 skipped，保留1条原弃用警告 |
| Ruff检查/格式 | 全部检查通过，37个Python文件格式通过 |
| 锁/安装依赖 | 离线锁22包一致，安装22包兼容，无新增依赖 |

完整后端38项失败的JUnit消息全为`契约尚无业务实现（T04/T08）：twoworlds.api.app, twoworlds.storage.sqlite`，未进入HTTP行为断言。没有新增残留失败，没有删除测试/skip/xfail。早期非提升运行出现pytest缓存权限警告，另有测试空match警告；后者已删去无意义match参数，最终授权运行仅保留全量原有的anyio/Starlette弃用警告。

90项包括阶段/两结局、整个JSON的私密线索与媒体文字稿/装置/场景标记、未发现/非法共享拒绝、动作可用性与不暴露条件、背景/cue/资源条件各自阻断、修复后断电/恢复、非法角色/状态/剧本与构造绕过、冻结/独立序列化、禁止文件/网络访问、新进程禁止导入Web/存储/AI适配器。对话只有空列表验证，不能据此声称未来私聊历史隔离已通过。

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain/test_projection.py -q --tb=short --basetemp=work/pytest-t03-projection-final --junitxml=work/t03-projection-final.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain -q --tb=short --basetemp=work/pytest-t03-domain-final --junitxml=work/t03-domain-final.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q --tb=short --basetemp=work/pytest-t03-content-final --junitxml=work/t03-content-final.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short --basetemp=work/pytest-t03-all-final --junitxml=work/t03-all-final.xml
.\backend\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/hatch_build.py
.\backend\.venv\Scripts\python.exe -m ruff format --check backend/src backend/tests backend/hatch_build.py
uv lock --project backend --check --offline --cache-dir F:/two-worlds-agent-game/work/uv-cache
uv pip check --python backend/.venv/Scripts/python.exe
```

最终JUnit和完整日志保留在该工作树忽略的work目录，不进入提交；本轮未重建wheel/sdist，不把旧发行包当作T03.1安装证据。

## 自己比较A/B快照

在具备本轮代码的项目根目录执行；是纯Python输出，没有游戏服务地址。

```powershell
@'
from pathlib import Path
import twoworlds.content.loader as loader
from twoworlds.domain.engine import create_initial_state, apply_command
from twoworlds.domain.projection import project_save

script = loader.ScriptLoader(Path(loader.__file__).parent / 'scripts').load('lighthouse', '1.0.0')
state = create_initial_state(script)
state = apply_command(state, script, 'a', {'kind': 'inspect', 'args': {'target': 'maintenance_log'}}).state
for role in ('a', 'b'):
    snapshot = project_save(state, script, role)
    print(role, snapshot.model_dump_json(indent=2))
assert len(project_save(state, script, 'a').personal.clues) == 1
assert not project_save(state, script, 'b').personal.clues
assert state.version == 1
'@ | .\backend\.venv\Scripts\python.exe -I -X utf8 -
```

重点比较personal.clues、devices、observations、available_actions和presentation；A看过日志后可调光，B仍只有inspect_chart。两人public.clues均为空，投影本身不会新增共享或改变version。

## 验收边界与下一步

没有未修复的本轮测试失败。QA-P01只记录纯领域投影证据，完整HTTP/WS/命令响应/AI通道尚未集成；QA-P02、P03、P04未完成。QA-M03只有媒体声明筛选证据，真实资源许可与读取授权/播放仍待验证。内容中的自然语言必须由作者审阅；投影只能执行权限声明，不能自动证明文案绝无剧透。

下一环节T03.2只计划share_clue命令、公共里程碑与公共事件截断后的回顾及测试。没有实现上述功能，没有提前进入T04或媒体/前端。完成T03.1后停下来，等待用户审查和明确继续。
