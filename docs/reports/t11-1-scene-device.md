# T11.1 · 场景与装置交互

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
