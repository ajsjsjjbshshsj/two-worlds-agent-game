# T11.3.2 · 合作因果动效与可跳过关键演出

实现与验证日期：2026-11-17；最终交付核对：2026-11-18。本轮只完成T11.3.2，停止等待人工审查，不开始T11.3.3、T12或其他任务；未使用子代理。

## 基线与范围

开始时工作区干净。先fetch远端，确认codex/bootstrap最新HEAD为`63245509c5dfd15336da27d0becf3995bd1a87e6`（Merge pull request #28），父提交c31aa9e/cfdaea9，核实T11.3.1已实际合并。本地/远端均不存在同名任务分支，随后从该最新目标创建`codex/t11-3-2-cooperative-performances`，没有继续在T11.3.1分支实现，也没有向目标分支提交。

先阅读AGENTS、交接、README、04中T11/T11.3.1、05中QA-M01～M07、07及T11.3.1报告。现有个人投影已提供全部所需字段，因此没有修改后端、游戏规则、存档、已发布剧本JSON、AudioManager/audio_events/operation_sfx、字幕生命周期、game Store、类型协议或依赖锁。仅扩展原有CausalPerformance、WAAPI播放器与两个SVG场景，不建设第二套动画引擎。

## 每个剧本的三处合作节点

| 剧本/合作节点 | 观察者与确认字段 | 触发与画面 |
| --- | --- | --- |
| 灯塔：光路配合后聚焦 | B，beam_quality/beam_destination | calibration内blurred→clear且有授权落点；光束从模糊到清晰，落点短暂强调，保留当前确认光束。只读结果，不读A的emitter |
| 灯塔：B供电→A通电 | A，clock_powered | repair内false→true；保留T11.3.1电路点亮和时钟反馈，未替换旧实现 |
| 灯塔：A维修→机械/航道就绪 | A的clock_repaired、B的route_ready | repair内各自false→true；A看到机械启动与既有正常指针运行，B看到航道就绪标记描出。只表示就绪，实际confirm_route仍需提交规则命令 |
| 星轨：A开闸→B声呐就绪 | B，echo_available | survey内false→true；保留T11.3.1三道扩散波，不读取A的echo_gate |
| 星轨：B扫描→双方获得定位 | A/B，scanned_segment | survey内由未投影变为非空授权定位；B出现声呐扫描波，双方轨道区域短扫、定位文字显现，保留真实定位。是否扫描成功完全由服务器提供字段判断，不复制扫描规则 |
| 星轨：A安装→双方导轨连接 | A/B，rail_connected | 明确survey→boarding且false→true；导轨逐渐描出、接口光圈反馈，保留已连接轨道 |

灯塔的维修/航道反馈是同一合作节点的两个视角，不以两个演出ID虚增节点数。每个剧本各有3个物理合作节点，均包含跨角色观察。光束聚焦发生在calibration；锁定后按既有场景进入repair显示signal_locked，不把旧光束带进不相干场景。星轨缺轨定位只使用已有scanned_segment可见性（后端仅track_scanned后投影），无需新增后端字段。

## 两段关键演出与四个结局

关键演出必须同时满足：同一范围内相邻确认版本、旧场景decision且未完成/无结局、新场景completed且completed=true、public.ending属于当前支持的剧本结局。其他场景跳转、首次恢复、版本跳跃或未知结局均不触发。

| 剧本/公开结局 | 临时演出 | 结束/跳过后的静态画面 |
| --- | --- | --- |
| 灯塔guide_now | 灯塔恢复亮度、光束聚焦、海面轻动，约3.2秒 | 保留引航光束和“现在引航”标记，与服务器回顾一致 |
| 灯塔wait_tide | 灯塔恢复亮度、潮汐显现、海面轻动，约3.2秒 | 保留潮汐/月面分支和“等待潮汐”，不画引航光束 |
| 星轨rescue_detour | 列车相对其最终位置移动、站台和前景导轨变亮，约3.2秒 | 保留绕行支线与救援标记、列车最终位置及“绕行救援” |
| 星轨return_station | 列车向确认的归站位置移动、站台和导轨变亮，约3.2秒 | 保留归站列车最终变换与“安全归站”，不出现救援支线 |

列车使用内层g做临时移动，外层仍是服务器结局决定的最终transform，避免WAAPI覆盖最终位置。前景ending-rail在站台上方绘制，防止临时导轨反馈被站台遮挡。所有素材均为现有/新增原创SVG原型，仍明确标记非正式美术。

播放中出现原生“跳过演出”按钮，固定在视口角落（含安全区偏移）、至少44×44px，支持键盘和触屏，不使用阻断交互的模态层。点击直接调用当前协调器skip→AbortController.abort，同步取消全部已创建的Animation；最终画面本来就由Vue按确认快照渲染。没有POST、规则调用、存档/版本修改，也不改变音频或旁白/字幕状态。跳过不清除已消费键和基线，同版本重读不再出现；刷新以当前快照建立基线，不播放历史关键演出。用户无需等待结束才能导航或查看结果。

## 状态隔离、取消与音频边界

继续沿用save_id/pair_id/script_id/script_version/role范围、凭证生命周期、接受版本、演出id和页面generation。只比较授权原子值，不读伙伴原始设备、不解析observations中文、不拼完整GameState。每个较新快照取消旧临时演出；相同版本不重启当前演出，跨版本直接恢复最终状态。

本轮仅允许两类明确跨场景触发：survey→boarding的导轨连接，以及decision→completed的公开结局；任意其他场景切换都只恢复画面。当前正式规则将这些节点分步提交，一个角色每个确认版本只选择一条对应演出，不补演未知中间过程。

隐藏、pagehide、减少动态、卸载、切档/角色/剧本/内容版本/凭证变化仍取消旧轨道并隔离generation。nextTick与finished/异常均检查AbortSignal、当前控制器和generation，旧异步不能覆盖新演出。原WAAPI播放器仍为全部轨道注册清理，逐条提前处理finished拒绝，部分启动失败时取消已经启动的轨道；fill:none、不调用commitStyles，动画不回写Vue的权威快照。图片/动画失败保留提示和最终状态，行动不因动画错误禁用。

T11.2音频逻辑完全保留。演出层不导入AudioManager，不生成audio_events，不从普通flag变化制造操作音效。跳过只跳过视觉，已有旁白/字幕按原生命周期继续，仍可单独使用原旁白控制。关闭声音时演出照常，减少动态时直接显示静态结局；不承诺两名玩家同步播放，也没有WS或持久化事件日志。

## 测试命令与结果

环境：Linux、Node24.22.1、系统Chromium156.0.8078.79；Playwright1.58.2仅为本机验证工具，不加入项目依赖。后端继续使用原有真实SQLite/uvicorn端口8017，Vite5187，仅隔离TEST-ONLY发布库。

| 检查 | 实际结果 |
| --- | --- |
| 原有前端测试 | 251项文件和断言完整保留，无删除/skip/xfail/弱化 |
| 新协调器测试 | 36通过：新节点、错误私人视角、首读/重读/跳版本、跨场景白名单、四结局、跳过/恢复与scope隔离 |
| 新场景/WAAPI集成 | 41通过：实际SVG目标、正常结束、失败静态回退、四结局双角色跳过、部分失败清理、后台/偏好/离页、声音独立与图片失败 |
| 前端完整回归 | 328通过，0失败/跳过，19个测试文件 |
| typecheck/build/format | 通过，构建88 modules |
| git diff --check | 通过 |
| 后端/SQLite/Mongo单测 | 后端代码未改，本轮未执行这些回归，不将旧统计当本轮证据 |
| GitHub CI | 修订前快照三类检查均为 0，当前没有可报告的 GitHub CI 运行结果，见下文 GitHub 实际交付 |

frontend目录：

```bash
npm run test:unit
npm run typecheck
npm run build
npm run format:check
npm run test:unit -- tests/cooperative-performance.spec.ts tests/cooperative-scene.spec.ts
```

根目录执行git diff --check。新夹具为cooperative-fixtures.ts，仅为测试个人快照，不作为生产剧情状态或前端剧本真值表。

## 真实浏览器验证

使用真实SQLite/TCP与独立A/B浏览器上下文，创建四个隔离房间/存档，分别走guide_now、wait_tide、rescue_detour、return_station。每条轨迹的初始身份/房间/记录检查以HTTP准备；新增合作操作、结局投票通过真实页面表单提交，观察方手动读取；没有用单元测试截图替代浏览器证据，没有直接改数据库或伪造GameState。

- 灯塔：A调整发射器后B聚焦；B供电后A通电；A维修后A机械/B航道反馈。检查B响应没有emitter及emitter_angle，A响应没有power_router。四种结局中的灯塔两个分支都经过真实操作。
- 星轨：A开闸后B就绪；B扫描后A/B定位文字出现；A安装后A/B导轨动画。检查B没有echo_gate/gate_position，定位由服务器返回。随后按规则完成确认灯号/接车，进入共同选择。
- 每个结局：双方在最后一票前读到decision基线，B最终投票后演出，B以Enter键或触屏tap跳过；检查轨道全部idle、POST计数不变，重新GET的存档版本与结局不变。A重新读取后正常看完演出；画面标签与服务器public.ending/recap.summary一致。
- 两个额外独立上下文分别验证版本跳跃与减少动态：前者跨越两票直接恢复完成画面，后者相邻版本也只显示静态；没有动画或跳过按钮。刷新已经完成的A页面同样不重播。
- 390px视口均无横向溢出，跳过按钮尺寸及坐标在390×844视口内；声音关闭时0音频响应，0未处理页面异常。原型最终画面已检查截图，不声称真实iOS/Android设备验收。

辅助脚本/测试库位于被忽略的work/t11-3-2-browser，截图为/tmp/t1132-<ending>-playing.png及-final.png，仅本实例临时证据，不进入PR或正式资源。测试媒体为程序合成透明PNG与测试WAV，原型不会被不透明占位图遮挡；正式发布库未改变。这些材料不代表正式图片、配音、音效或版权许可。

## 学习阅读顺序与观察方法

1. services/causal-performance.ts：Baseline从个人投影提取哪些字段，update如何只允许相邻/明确转场，skip为何只取消而不reset基线。
2. services/performance-animation.ts：各id对应哪些临时轨道，列车内外层变换与finally清理。
3. components/game/SceneRenderer.vue：active.skippable与按钮、偏好和生命周期挂接。
4. LighthouseScene.vue与StarlineScene.vue：静态最终状态先由确认值渲染，data-causal-part只是动画目标。
5. 新增两个测试文件：先看触发/去重，再看跳过/异常、真实DOM与快照不变断言。旧两个测试文件仍覆盖T11.3.1的供电/就绪。

真实页面可复用[T11.3.1报告中的临时TEST-ONLY服务说明](t11-3-1-causal-performance.md#如何自己观察原型)（显式注入隔离PublicationStore、透明测试PNG、SQLite），另启动Vite，两个独立浏览器创建身份并加入同房。切换另一玩家操作前先重新读取，避免版本冲突；观察者先读基线，再由搭档只提交一次，然后观察者读取相邻版本。声呐需先按服务器规则配置电源，不能靠前端预期推断就绪。

灯塔观察光束聚焦可先让B检查海图并选amber，再让A检查记录、切pulse并调整角度；维修前保持tower供电并检查clock_gears。星轨按开闸/声呐电源/扫描/安装顺序观察。进入decision后A先投票，B重新读取再投同一结局；A也在最后一票前读取基线，才能分别看到两端关键演出。若两票间未读而版本跳跃，按设计只显示最终状态。

## 未完成事项与交付检查点

本轮达到每剧本3处合作动效和1段可跳过关键演出的**SVG/WAAPI原型机制目标**，不是正式视听交付。正式美术/音频/媒体分层/来源许可、人工听感/观感、Safari/iOS/Android真机、WS与可靠跨设备事件补送仍未验收，不提前将QA-M01～M07全部标通过。当前关键演出覆盖已确认的结局，首次或跨版本读档不重放历史；没有主动重看历史关键演出功能。

### GitHub实际交付（2026-11-18）

实现提交为 `e062900dfac5b39ecd66903e3a9e02741809614d`，已推送到 `codex/t11-3-2-cooperative-performances`。早期交付记录为 `6da1ea5d4a5f75f3b44bcb7a86cd81d80aba61d1`。

历史上首次用 [PR 正文文件](t11-3-2-pr-description.md) 执行 `gh pr create` 时，GitHub GraphQL 返回 `Forbidden`，命令退出码为 1。此后 PR #29 已成功创建。

[PR #29](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/29) 已成功创建，状态为 OPEN，尚未合并，等待人工审查。base 为 `codex/bootstrap`，head 为 `codex/t11-3-2-cooperative-performances`。

此前文档推送遇到 503，之后使用 `git -c http.version=HTTP/1.1 push` 成功推送历史文档提交 `3627febc9fdff000244ba6ee9a0c733c0027a66f`。

本次文档修复前，GitHub 的开发分支和 PR HEAD 均核实为 `a2f79ef65ee844305576d2548d6ad5e2b51951a8`。修复后的 SHA 以推送验证为准，见 [PR 提交页](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/29/commits)。

按用户提供的修订前 GitHub 检查快照，check-runs：0，workflow-runs：0，commit statuses：0。当前没有可报告的 GitHub CI 运行结果。328 项通过是 T11.3.2 的本地测试结果。

人工验收还包括正式美术、配音与音效、素材许可、媒体分层、人工视听和 Safari/iOS/Android 真机体验。后端代码保持在原实现，本轮交付文档修正不计为后端或 Mongo 回归证据。
