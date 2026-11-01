# T01.2.2 · 《跨时灯塔》正式内容与验证

日期：2026-11-01。范围仅限正式内容、内容测试和文档，不实现规则执行器、投影、前端、数据库或AI。

## 设计与执行计划

基线：PR #4已于2026-10-29合并；本轮从`origin/codex/bootstrap`的`8cb0763de07042fadd5317ec85cdee9e6d9376b1`创建`codex/t01-2-2-lighthouse-content`。复用现有隔离工作树`F:\two-worlds-agent-game\work\pr-t01-1-schema`；不推送主学习目录的旧本地历史。

用户已明确指定文档02/03/05/07和现有Schema为设计依据。实现步骤：

- [x] 阅读约定、玩法、Schema、加载器和验收规范；核对PR、远端与本地修改。
- [x] 先写正式文件加载/完整性测试并确认缺少正式内容时失败。
- [x] 新建`backend/src/twoworlds/content/scripts/lighthouse/1.0.0.json`，通过既有`ScriptLoader(root).load("lighthouse", "1.0.0")`加载。
- [x] 运行新增内容测试、全部内容测试、全量后端测试与格式/依赖检查；分别报告结果。
- [ ] 更新任务、验收、学习入口与交接，检查文件范围；提交、推送并创建PR供用户手动合并，然后停止。

### 内容如何对应既定玩法

四个存档节点严格沿用`calibration → repair → decision → completed`。文档02按叙事列出的“供电维修”和“互相验证”均落在`repair`状态；B的`confirm_route`完成验证后进入`decision`，共同选择一致后才由未来T02结算到`completed`。不增加第五个状态，也不让修复时自动跳过B的贡献。

| 节点 | A的贡献/信息 | B的贡献/信息 | 出口声明 |
| --- | --- | --- | --- |
| calibration | 维护日志、发射角度/光型 | 航道目标、滤镜、当前光束结果 | B锁定有效信号 |
| repair | 得电后检查齿轮、获得工具、稳定维修 | 可逆路由供电、修好后验证航道 | 修复完成且B确认 |
| decision | 公开选择立即引航/等待潮汐，可改票 | 同等选择权，可改票 | 两票一致，由T02原子结算 |
| completed | 回看自己的场景与公开里程碑 | 回看自己的场景与公开里程碑 | 无游戏写动作 |

初值：发射器`0/steady`、滤镜`clear`；供电初始`observatory`（既定三选一中的非灯塔位置，时钟无电）。线索/分享/投票为空，布尔里程碑为false，`ending_id="none"`。无固定密码和预先发现的答案。

Schema只有等值条件、固定值写事实与记录投票；本轮不扩展它：

- `repair_clock`只声明可成功接受的`mode=steady`，`fast`不在成功参数集合内，不能套用修复效果；T02须验证错误尝试拒绝且完整状态不变。
- 调光/路由动作只写设备配置；条件化角色演出声明当前反馈，不把某一固定方向/供电成功无条件写入观察。T02/T03仍需按实际配置计算获准观察。
- `vote_ending`只声明`record_vote`，不无条件写完成或跳场景。`endings`列出两个合法结局，`ending_id/completed`由T02一致投票结算处理器写入，须与存档完成标志和场景一致；没有声称JSON已能执行结算。
- 通用`share_clue/request_hint/talk`由后续服务实现，不用虚假的observe效果伪装为已实现。

### 视听与私密边界

提供两角色场景、B专属光束方向、A供电/齿轮与B扫描反馈、共同结局，以及环境音、不同事件音效和带字幕的短旁白声明。每个秘密媒体与cue均绑定角色、场景和必要条件；背景与公开旁白不包含完整谜底。NPC的三级提示仅引导检查本人已开放对象和交流，不跨角色提供私密日志/目标。

所有媒体文件都尚未制作；source/license明确为制作规格、未获许可且不可发布。路径仅是未来资源约定，不是可访问URL。不生成假素材、不调用付费模型，不宣称资源许可、动态效果、音频播放或媒体访问鉴权已经通过。内容1.0.0为待审内容版本；发布冻结/公开目录/资源打包仍属T01.2.3。

## 实测记录

环境：Windows、Python3.12.4、Pydantic2.14.1、pytest9.0.2、Ruff0.15.4；沿用backend/.venv和锁定22包，无依赖改动。无数据库、模型调用或网络游戏服务。

正式JSON SHA256：`96bcd10911d77eca2f612919b4a79c25c165125ffd31df8a462cd7043b41f662`；58,833字节（LF换行），4场景、6事实、3线索、3装置、10动作、2结局、28媒体声明、8份角色场景配置。媒体类型为16图像、1环境音、8事件音效、3短旁白；是制作清单数量，不是实际资源数量。

| 检查 | 真实结果 | 边界 |
| --- | --- | --- |
| 改动前`pytest backend/tests/content` | 110 passed | 已合并基线 |
| 先写首批32项，再执行正式内容测试 | 32 failed | 当时正式scripts目录尚不存在，全部CONTENT_INVALID_ROOT，无装配错误 |
| 编写正式JSON后执行首批测试 | 32 passed | 没有修改Schema/加载器来迁就内容 |
| 增补4项损坏文件副本加载检查后，`pytest backend/tests/content` | 146 passed | 新增36项，含Schema损坏拒绝与实际文件加载分类 |
| `pytest backend/tests` | 146 passed、38 failed、0 errors、0 skipped | 38项全为缺twoworlds.api.app/storage.sqlite，尚未进入HTTP行为断言；原Starlette/AnyIO弃用警告1条 |
| `ruff check backend/src backend/tests` | 通过 | 未抑制规则 |
| `ruff format --check backend/src backend/tests` | 22个Python文件通过 | JSON由严格加载器实际读取 |
| `uv lock --project backend --check --offline` | 22包锁一致 | 锁/pyproject无变更 |
| `uv pip check --python backend/.venv/Scripts/python.exe` | 22包兼容 | 原环境，无新增安装 |
| 最终单独执行正式内容测试与只读加载示例 | 36 passed；实际打印灯塔1.0.0与四个状态ID | 确认示例可复现，无游戏执行 |
| Markdown本地链接/代码块/JSON检查与变更文件凭证模式检查 | 20份Markdown、133个本地链接通过；凭证模式无匹配 | 排除2个按约定只在本机保留的原始聊天链接 |

Windows严格路径解析的运行权限沿用T01.2.1：文件加载测试在扩展本地执行权限下运行，不改为宽松路径。普通受限环境的uv依赖检查曾因解释器缓存写入被拒绝而失败；同一离线命令在扩展权限下成功，没有重建锁文件或联网安装。JUnit保存在忽略的`work/lighthouse-content-results.xml`（146项）、`work/lighthouse-all-results.xml`（184项），不随PR提交。

新增检查的重点：

- 真正从正式源码目录按lighthouse/1.0.0加载、JSON往返和缺9.0.0不回退。
- 四状态、干净初态、独有动作角色与阶段；有效锁定的全部前置、可逆配置不直接写成功事实。
- B供电才开放A工具/维修，修复后仍需B确认；repair_tools_ready仅A可见。
- 两种共同结局、投票只记录不直接完成；两个结局的画面/字幕均受完成事实与结局ID约束。
- 公开介绍/事件/NPC/回顾/公开媒体不嵌入私线索全文与关键答案；每角色入场文案不提前包含线索全文。它是静态内容审核，不能替代后续HTTP/WS/AI隔离测试。
- 四方向仅B可见且需本人已读图、pulse和amber；不稳定组合有模糊反馈；供电、维修和扫描演出有角色/条件与文字替代。
- 破坏正式内容副本的角色、图边、引用、资源版本，既有Schema拒绝；临时文件缺视图、错误设备归属、缺媒体、错误ID由加载器拒绝，正式文件不变。

未执行：实际动作轨迹、全部可达状态无软锁、改票/一致票原子结算、权限投影、发布冻结与旧档版本绑定、wheel内资源整合、真实媒体/许可/播放、浏览器/真机/数据库/AI。本环节不是L1规则原型，也没有可玩地址。estimated_minutes=15仍为体验目标，尚无试玩测量。

## 学习入口

1. [正式JSON](../../backend/src/twoworlds/content/scripts/lighthouse/1.0.0.json)：metadata/initial_state/scenes → clues/devices/actions → endings → media/presentation。
2. [正式内容测试](../../backend/tests/content/test_lighthouse_content.py)：`load_lighthouse` → `test_lock_requires_both_discoveries_and_the_complete_optical_configuration` → `test_reverse_power_unlocks_a_tools_then_repair_unlocks_b_confirmation` → 两结局与损坏副本测试。
3. [既有加载器](../../backend/src/twoworlds/content/loader.py)：`ScriptLoader.load`依次读取、解析、校验和核对ID/版本，无新增加载接口。

例如B把power_router.target设为tower，声明层面A的inspect_gears前置与tower_powered演出条件才满足；A获得工具并稳妥修复后，B的route_scan条件满足，仍需B执行confirm_route。现在能检查这些声明相互引用正确；T02再证明实际动作会按此生效且错误尝试不改变世界。

在主项目根目录（同步本轮学习文件后），或上述PR工作树根目录运行：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content/test_lighthouse_content.py -q --basetemp=work/pytest-lighthouse-local
.\backend\.venv\Scripts\python.exe -I -X utf8 -c "from pathlib import Path; from twoworlds.content import loader; root=Path(loader.__file__).parent/'scripts'; s=loader.ScriptLoader(root).load('lighthouse','1.0.0'); print(s.metadata.title, s.metadata.content_version); print([x.id for x in s.scenes])"
```

预期第一条测试命令36 passed；加载打印“跨时灯塔 1.0.0”和四个状态ID。此处是源码目录读取，不是服务启动；普通受限执行若拒绝严格路径解析需相应本地读取权限，不应删除安全校验。pytest的basetemp为专用临时目录，会清空重建，不放学习笔记。

完整定义只供服务端，不能直接发给浏览器或AI；测试小样`minimal.json`仍只用于Schema测试。下一环节是T01.2.3发布不可覆盖/公开目录/资源集成打包，本轮不执行。PR提交与审查状态见[交接](../开发进度与交接.md)。
