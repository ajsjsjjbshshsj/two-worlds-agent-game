# T11.1 · 场景与装置交互

当前以文末「PR #26 审查修复」为准；前文保留初次提交的验证记录，其中“后端未改”“仅本人设备”等描述是初版状态。

2026-11-16。PR #25已合并，最新基线0b5d47b52c19b9df77d3f46c8cf9caa1772e7341；分支codex/t11-1-scene-device。复用既有干净工作树，主目录不改，无子代理。Git fetch网络低速失败后，经GitHub API导入签名Git对象，SHA与精确合并基线一致。本轮只做T11.1，不进入音频/复杂Cue/WS/PWA/AI。

## 设计与文件阅读顺序

1. frontend/src/types/game.ts：白名单完整解析个人投影的public、personal、available_actions、presentation；字段类型、事件枚举、参数类型/选项/长度严格检查，不保留完整state或其他额外内部字段。PublicRecap沿用后端默认空值，兼容已有合法空recap，不降低原测试要求。
2. frontend/src/services/game.ts：复用现有JSON HTTP客户端，GET个人快照、POST命令；验证回执UUID/status/接受版本与save，错误原文不展示。
3. frontend/src/stores/game.ts：权威快照、请求代次、显式刷新、提交及手动确认同一未知请求。参数仅来自当前行动；UUID用crypto.randomUUID；提交前不修改设备。成功确认后更新，拒绝/冲突保留旧快照，重新读取不接受版本回退。切档/登出使旧响应失效。
4. frontend/src/components/game/SceneRenderer.vue、Device.vue、ActionPanel.vue：原创SVG/CSS分层灯塔/观测站、站台/列车原型；仅渲染本人设备。发射器旋转/脉冲、布尔指示灯、电路、闸门位置与轨道指示依确认值变化；不计算谜题条件或预算。热点定位设备，原生按钮/输入支持键盘和触控；减少动态时静态显示同一状态。
5. frontend/src/services/media.ts：Bearer鉴权fetch PNG/JPEG/WebP，沿用API配置校验，no-store/omit/拒绝重定向；有界32MiB逐块读取，只为image创建object URL。SceneRenderer切换/登出/卸载中止请求并撤销URL，迟到结果也释放；图片失败保留观察与控件。
6. frontend/src/views/Game.vue、router/index.ts、styles/main.css：将既有/saves/:saveId路由接入游戏，保留返回书架；本人设备/观察/私线索与公开线索/事件/回顾分开展示。share_clue和结局投票仍由服务器提供的通用行动表达，无前端谜底。未知提交结果阻止新写入，提供同UUID/参数手动确认，SPA离开/刷新提醒；未做T12的跨刷新请求持久化。
7. frontend/tests/game.spec.ts、game-ui.spec.ts、game-fixture.ts：新增21项，原125用例和fixture未改。未改后端生产代码、依赖或正式发布目录。

## 数据流与取舍

Bearer → GET save → parseGame → game.snapshot → 场景/设备/线索/行动。用户编辑的是独立草稿；submit按当前available_actions验证类型和choices，生成UUID、expected_version、kind、args → 既有命令API/后端规则/CAS → receipt+个人save完整校验 → 替换已确认快照 → CSS/SVG更新。不提前播放成功效果，不由动画结束决定机关成功。

网络错误不自动重试，保留原请求供明确手动确认；VERSION_CONFLICT给重新读取入口。跨档与令牌变化清上下文，不以旧响应覆盖新档。图片是二进制，单独用fetch/流读取；游戏JSON仍复用原客户端。当前只解析空dialogue，未引入AI/NPC历史或音频。

原型中设备名称与有限视觉位置是表现映射，不包含“哪个选项正确”的规则。UI没有固定密码、隐藏线索、完整规则或功率预算计算。A/B场景与设备不同；未获准的发射角度不会用于B画面。数值/布尔设备状态也有文字读数，减少动态或图片失败仍可操作。

## 实际验证

在frontend目录：

| 命令 | 结果 |
| --- | --- |
| npm.cmd run typecheck | strict通过，退出0 |
| npm.cmd run test:unit | 146通过，0失败/跳过；原125保留，新增21 |
| npm.cmd run build | 66模块，构建通过，退出0 |
| npm.cmd run format:check | 通过，退出0 |

先新增测试，缺types/game与组件时分别导入失败，再实现。首轮完整回归发现旧book测试的合法空PublicRecap尚未按默认值处理，修正解析器后原断言不变、全部通过。额外覆盖失败不改状态、旧版本拒绝、显式同请求确认、图片失败/切换/卸载释放、动态参数和角色设备隔离。

使用本地忽略目录backend/work/t111-both-browser.cjs、既有临时发布工厂与真实TCP，分别运行sqlite和mongo，均退出0。三个独立Edge context完成身份/邀请/第三人隔离；灯塔与星轨各12步通过新ActionPanel控件提交，非HTTP脚本代替玩家操作。角色切换重新读取服务端快照，B开启prefers-reduced-motion:reduce仍完成操作。截图检查灯塔A原型，1440/390无横向溢出；非iPhone/Android真机或跨浏览器验收。测试准备旧档使用既有API，但通关动作均由界面完成。

正式目录先验证空数组；非空界面和24步规则轨迹仅用隔离TEST-ONLY发布库。合成PNG/WAV不进入前端或正式资源，不播放音频。自有API/Vite/Edge关闭，Mongo随机测试库清理；未停止共享Mongo或既有5173。辅助脚本、截图、JSON在backend/work，不提交。

后端没有修改，本轮没有运行后端pytest，不把T10.2的1151通过/3失败当本轮结果。git diff --check、原测试差异与构建产物检查另在交付前执行。QA-U03取得临时内容UI通关证据，但正式内容/玩法体验验收仍未完成；QA-M01/M02仅原型状态动效部分，完整美术、至少3次跨角色演出/关键演出仍待素材与T11.3；QA-M06取得减少动态/文字操作证据，不冒称音频和真机已验收。

## 如何自试与停止点

按frontend/README与backend/README第17节显式启动本地后端和前端；两账号入房间后选择正式发布剧本。当前正式目录为空，正常不会出现可玩的正式卡片，禁止自动发布草稿。可先执行npm.cmd run test:unit -- tests/game.spec.ts tests/game-ui.spec.ts学习明确标注的测试数据；真实非空浏览器验收使用上述本机辅助脚本，不是正式内容上线。

本轮保留原SaveEntry组件作为历史实现但路由已切换Game，不新增第二个公开游戏路由。所有新行为只在既有认证入口后使用。下一T11.2再接基础音频/字幕/播放控制；T11.3再接复杂因果演出。本轮交付PR后停止等待用户审查，不自动继续。


## PR #26 审查修复（2026-11-16）

范围：仍在 `codex/t11-1-scene-device`，起点为 PR #26 HEAD `e3f7e2ac86a2df38ade01e1581ca2c825e49f3f7`。没有新建 PR、合并或开发 T11.2；没有使用子代理。主工作区保留，修改只在既有独立工作树。

### 服务端视觉契约与权限

新增 `presentation.visual_state`，JSON 为排序的 `{id,value}` 列表；内部是冻结 `VisualEffect` 的 tuple。`project_save → validate_state_and_script → _presentation → project_visuals`，先验证世界和剧本，再按确定的剧本/角色/阶段/发现条件逐字段构造。没有把完整 GameState、条件表达式、伙伴原始设备或线索正文加入视觉值。前端 `parseGame` 只复制 id 和标量值；旧快照没有该可选字段时使用空列表，不从观察文字推断。

| 剧本/角色 | 获准字段 | 授权边界 |
| --- | --- | --- |
| 灯塔 A 校准 | emitter_angle、emitter_pattern | 本人发射器，驱动指针/光束旋转与脉冲 |
| 灯塔 B 校准 | filter_tint、beam_quality；有条件的 beam_destination | 未读本人航道图为 unidentified；图已读但滤镜/光型不足为 blurred；只有既有观察允许清晰辨认时才给落点符号，不传 A 的角度/光型 |
| 灯塔 A 维修 | clock_powered | 只给时钟是否通电，不给 B 的路由目的地 |
| 灯塔 B 维修 | power_target、route_ready | 本人的路由与已授权航路反馈，不给 A 的齿轮/工具状态 |
| 灯塔双方锁定后 | signal_locked、clock_repaired | 公开里程碑；改变供电不抹除已完成维修 |
| 星轨 A 活动阶段 | gate_position、platform_track | 本人装置；不传 B 的三个能源开关 |
| 星轨 B 活动阶段 | engine_on、sonar_on、lamp_on；survey 的 echo_available | 三个指示独立；回声可用只表达现有观察允许的结果，不传 A 的闸门原始位置 |
| 星轨双方 | rail_connected、signal_confirmed、train_arrived；活动阶段有条件的 scanned_segment、confirmed_signal | 实际扫描后才给 bridge_2；确认后才给双方灯号，不能提前看到答案 |

视觉函数只派生表现，不修改规则、数据库模型或权威事实。灯塔方向到视觉符号的服务端映射复用既有观察语义；客户端只将符号映射到屏幕坐标，不计算锁定条件或通关答案。

### 前端分层与实际阶段变化

`SceneRenderer` 管理授权图片、清理和舞台；`LighthouseScene`、`StarlineScene` 只绘图。删除“任意设备 boolean 为真就全局通电”与 energized CSS。每个组件使用明确效果字段；无字段不猜机关状态。

| 阶段 | 灯塔实际图形 | 星轨实际图形 |
| --- | --- | --- |
| calibration / survey | A 灯塔发射器与旋转指针；B 观测站、滤镜与授权落点/模糊光 | 缺轨间隙、本人回声闸或声呐圆环；扫描后出现实际定位框 |
| repair / boarding | 切到时钟箱、通电线、机械指针和 B 三路路由；维修后指针运行 | 安装后出现连接轨道；确认灯号、A 轨道选择与 B 三个独立能源灯 |
| decision | 已修复灯塔、双人岔路图形及现有投票控件 | 到站列车、完整站台、双人岔路图形及现有投票控件 |
| completed | 结局勾选；引航光束或等待潮汐图形 | 结局勾选；绕行留站或归站列车位置差异 |

completed 隐藏热点与 ActionPanel，不显示可操作机关。每阶段不同 SVG 结构，不只切标题或 class。终局以服务器 public.ending 为准。

背景图片独占 `.scene-background` 底层，Cue 图片独占 `.scene-overlay` 叠加层；SVG 在中层提供状态图形与失败替代。相同 asset 只取一次，仍保留不同位置，不混成 figure；Cue ID 与背景层标记不共用命名空间。HTTP/图片解码失败保留 SVG、观察和行动。沿用原 `protectedImage` 的 Bearer/no-store、32MiB 有界读取和类型校验；切档、登出、卸载或迟到请求撤销 object URL。不请求音频，不修改发布目录，不发布 TEST-ONLY 素材。

### 本次验证记录

测试先写：新增投影测试最初因缺少 visual_state 真实失败，然后实现后通过。初轮 API 回归错误地把既定领域拒绝状态写为409，核对现有契约后修正新增测试为422；未改已有 API 语义。默认 pytest 临时目录曾因 Windows 权限失败，改用忽略目录 `backend/work/pytest-visual-*`，未跳过测试。初轮新增测试 TypeScript get().exists() 类型错误已修正为 find().exists()，重新执行检查。

- 新增后端：`tests/domain/test_visual_projection.py` 20项，`tests/api/test_visual_feedback.py` 4项（每剧本 SQLite/Mongo 各1），24通过。API 真实创建身份、房间和同一存档，经命令与重读验证双方效果及不泄露伙伴字段；fast/超预算失败比较完整持久聚合与快照保持不变。
- `python -m pytest tests/domain tests/content -q -p no:cacheprovider --basetemp=work/pytest-visual-domain --tb=short`：623通过，0失败/错误/跳过。
- 前端 `npm.cmd run test:unit`：164通过，0失败/跳过，原146全部保留且原文件未改，新增18项视觉专项。覆盖两角色效果、独立能源灯、八个阶段结构、背景/Cue、解码失败、Bearer/清理、拒绝命令不提前改变画面、无中文解析。
- `npm.cmd run typecheck`、`npm.cmd run build`、`npm.cmd run format:check`：通过；构建73模块，产物忽略不提交。
- Ruff check/format --check（src tests）、`uv lock --check --offline`：通过。
- `python -m pytest -q -p no:cacheprovider --basetemp=work/pytest-visual-full --tb=short`（设置真实本地 MONGO_URI）：1178项，1175通过、3失败、0错误/跳过，1119.02秒。与T10.2基线1151通过/3失败逐项比较，新增24通过，无新增或消失的失败。3项均在 `tests/contracts/test_platform.py`：
  - `test_websocket_uses_auth_frame_and_personal_projection_on_reconnect`：WS入口未实现，WebSocketDisconnect。
  - `test_outsider_websocket_never_receives_a_snapshot`：同上，WebSocketDisconnect，不能据此宣称WS权限验收通过。
  - `test_demo_npc_is_private_and_cannot_change_game_facts`：NPC命令未实现，422 UNKNOWN_ACTION。
  - 保留这3项契约，不skip/xfail、不降低断言。只有既有Starlette/anyio弃用警告，不是新增错误。

使用忽略目录的 `backend/work/t111-fix-browser.cjs sqlite` 和 `... mongo`，分别启动自有 FastAPI/Vite/Edge，均退出0。每次三个独立浏览器上下文，灯塔/星轨各12步均通过 ActionPanel；伙伴重新读取同一 save 后断言实际 DOM（光束落点、时钟通电、扫描定位、线路连接、信号、到站）。B 全程 prefers-reduced-motion:reduce；修好时钟的 computed animationName 为 none，仍完成操作。两个适配器均记录四阶段截图、390px 小屏阶段与1440px页面，无横向溢出。已查看灯塔维修/星轨 boarding 的实际截图，不以 DOM 测试代替视觉检查。只关闭自有进程，Mongo随机测试库清理；正式目录仍为空，合成图片仅临时发布库。不是 iPhone/Android 真机或全部浏览器验收。

### 学习入口与未完成项

按 `domain/visuals.py → domain/projection.py → tests/domain/test_visual_projection.py → tests/api/test_visual_feedback.py → frontend/types/game.ts → SceneRenderer.vue → LighthouseScene.vue / StarlineScene.vue → tests/visual-feedback.spec.ts` 阅读。例如 B 路由到 tower，既有规则提交事实，A 重读时只得到 clock_powered=true，时钟线条点亮；A 不得到 B 的完整路由数据。

可重现：在 backend 用上述 pytest 专项（Mongo 设置本地 MONGO_URI，需真库）；frontend 执行 `npm.cmd run test:unit -- tests/visual-feedback.spec.ts`。应用入口启动方法沿用 frontend/README 和 backend/README；正式目录为空时没有正式卡片，不能自动发布草稿。

QA-M01/M02仍只有状态视觉原型部分证据，正式美术、完整关键演出、音频、真机体验未完成；没有把部分原型标记为完整通过。WS、自动同步、音频/字幕与T11.2、T11.3仍未实现。本环节更新PR #26后停止，等待用户审查。

最终文件检查：本轮14个必要文件；既有146项前端测试文件、media.ts的32MiB读取实现、正式内容/发布目录均无差异。临时库、截图、日志、辅助脚本、node_modules、dist和凭证不进入提交；git diff --check通过。更新原PR #26，保持未合并，停止等待审查。
