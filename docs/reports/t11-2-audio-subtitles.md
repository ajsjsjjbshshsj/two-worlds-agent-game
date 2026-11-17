# T11.2 · 基础音频与字幕系统

日期：2026-11-17。基线：`acca4ed6c4ff781f1e4077e7da08160aa5d1678a`，Git本地和远端codex/bootstrap均含PR #26合并及最终修复。开始时工作区干净；本轮分支`codex/t11-2-audio-subtitles`，目标`codex/bootstrap`。实现提交`65977da`已推送；实际`gh pr create`的`POST https://api.github.com/graphql`被网络代理以Forbidden拒绝，PR未创建。已保存api.github.com域名到环境草稿，保留原有设置；需在环境设置审阅保存/应用网络变更后重试，草稿保存不代表已生效。Git推送成功不证明API权限或认证可用，未要求重复提供凭证。本轮只做T11.2，不进入T11.3。

## 可观察行为与阅读顺序

1. `frontend/src/types/audio.ts`：AudioCue/Channel/Preferences/State，区分持续授权文字与瞬时播放状态。
2. `services/audio-assets.ts`：只将当前个人快照中的非图片资产转换为Ambient/SFX/Voice；双剧本复用各自真实scene/cue/media定义，无隐藏剧本、中文匹配或猜测成功。
3. `services/media.ts`：复用同一二进制加载器，图片旧入口保持；新增protectedAudio。Bearer头、精确API路径、配置Origin校验、no-store、omit、拒绝重定向、32MiB流式上限、AbortSignal、MIME白名单与object URL回收不变。
4. `services/audio.ts`：AudioManager.update建立读档基线/消费新确认Cue；start/load/play处理加载、拒播Promise和解码失败；enable/pause/resume/disable/skip/replay控制；reset停止旧作用域和请求。
5. `stores/audio.ts`：Pinia仅保存当前内存中的三通道音量、静音、字幕开关/字号和播放状态，不持久化Token、字幕或私有资源。
6. `components/game/AudioControls.vue`、`AudioSettings.vue`、`SubtitleDisplay.vue`：生命周期、后台停音、控制与可访问字幕；Game.vue只挂接组件，不承载音频实现。
7. `tests/audio.spec.ts`、`tests/audio-ui.spec.ts`、`backend/tests/api/test_audio_subtitles.py`：去重/取消/权限/实际数据库证据。

例如A的inspect经服务端成功提交后，已授权快照开放本人emitter_click Cue；AudioManager在后续快照首次看到该Cue才fetch受保护WAV并播放。请求未返回、失败、结果未知均不改变game快照，不会发成功提示音。B只收到B的Cue，不能下载A的私有声音。首次加载已有进度时当前Cue仅作基线；环境音在主动启用后循环，旁白需明确重播，字幕一直可读。

## 播放、取消与去重

使用浏览器原生HTMLAudioElement，没有新增应用依赖。Ambient/SFX/Voice分别音量；全局静音与关闭声音不同。环境音400ms交叉淡变，旁白降低环境音至35%而非关闭；SFX单次播放。旁白支持暂停/继续/跳过/当前授权内容主动重播。文件未配置、加载失败、格式不支持和NotAllowedError均明确提示，游戏操作保持可用；拒播或失败不随刷新快照循环重试，需要用户动作。

作用域包含save_id/script_id/script_version/role/当前Token生命周期（Token只在私有运行内存，不参与URL或日志），条目是cue_id+asset_id。首次快照将条目记入基线；后续只自动播放未见条目；禁音/暂停/关闭时消费但不补播。命令重试、相同或较新版本的相同Cue不重播。重新加载页面重建当前基线，避免历史SFX重放；不依赖持久化私有文字。只主动重播当前授权旁白。

切档、角色/凭证更换、登出、卸载、后台visibilitychange/pagehide立即停止、取消pending fetch、清理定时器、移除src并revoke对象URL。迟到请求即使忽略AbortSignal也会释放资源，不能跨作用域播放。后台回来不自动恢复；已加载的同场景资源保持到授权撤销/场景切换/结束/释放，失败字幕不消失。同场景授权撤销立即停止；切场景仅环境音淡出。

**边界：** 既有Cue是可见状态声明，不是带持久化event_id的完整事件流。每条Cue每个页面作用域自动播放一次，不保证每次调节角度/开关都发声；多次读取之间已消失的短暂Cue无法追溯。未修改游戏规则、个人权限、后端Schema或投影；没有WS、跨设备实时音频同步或T11.3演出队列。当前旁白串行占用Voice通道，不混播多段语音。

## 字幕协议与资源

当前后端MediaReference已有asset_id/kind/alt_text/transcript。新本地AudioCue结构：cue_id为服务端Cue原ID，key为cue_id:asset_id；text优先transcript、否则alt_text；subtitle_type按ambience/sfx/narration映射environment/effect/narration。当前正式定义没有角色名、逐句时间轴和语言字段，因此speaker=null、start_time=0、duration=null、language=zh-CN用于现有中文整段文字，不能声称实现逐句对齐。渲染支持可空说话人；旁白播放时关联key、显示实际currentTime与整段文字，暂停/跳过/失败/静音保留完整授权文字。支持16～28px字号、显示开关、中文lang、polite朗读区域、44px控件和小屏自然排版；不增加闪动动画。

原有后端允许audio/mpeg、audio/ogg、audio/wav、audio/mp4并做文件签名检查，资源归属仍由SaveService复用角色投影校验。原始世界、磁盘路径、未授权资源引用、恢复密钥和邀请不进入音频数据。没有直接外部URL、URL Token或公开私有预载清单。

正式发布目录仍为空，无新增正式音频文件及版权声明。正式环境音、语音、音乐和进一步音效仍需制作并审核来源/许可。本轮浏览器专用PCM WAV由程序生成330Hz低幅提示音，仅在隔离TEST-ONLY发布库使用，测试来源与许可均带Test-only标记，未加入正式资源/静态包；旁白通道使用同一测试音证明加载/播放链路，**不是实际配音朗读**。没有下载第三方音频。

## 验证记录

环境：Linux x86_64，Node24.22.1/npm11.9.0，Python3.12.14，Mongo7.0.48（固定镜像，nofile=4096），系统Chromium156.0.8078.79，Playwright1.58.2仅用于本地验证工具（不加入项目依赖）。

| 检查 | 实际结果 |
| --- | --- |
| 原有前端164项 | 文件/断言未改，全部保留通过 |
| 新管理器/加载器测试 | 27项：循环/单次/暂停继续/音量/静音/淡变/去重/过期请求/拒播/失败/MIME/上限/后台等 |
| 新组件与确认联动测试 | 12项：字幕/字号/朗读区/角色隔离/失败替代/关闭后台/释放/未知结果确认后发声等 |
| 前端完整测试 | 203通过，0失败/跳过（14文件） |
| 前端typecheck/build/format | 通过；无ESLint配置，未新增lint工具链 |
| 真实SQLite/Mongo API专项 | 74通过：新音频投影/媒体10项，原媒体接口64项；0失败/跳过 |
| SQLite浏览器真实TCP | 两剧本各A/B独立context，WAV解码currentTime递增/环境循环/旁白重播跳过/新Cue/关闭/刷新基线/角色隔离/390px无溢出通过，16次音频响应，0页面异常 |
| Mongo浏览器真实TCP | 同上，两剧本各A/B，16次音频响应，0页面异常 |
| 后端完整回归 | 1184通过、4个既有失败、0错误/跳过，244.43秒 |
| Ruff/格式 | 通过（96文件） |

后端四项失败与云环境安装时基线一致，无新增失败：

- `test_json_parser_recursion_failure_is_reported_without_a_raw_traceback`：当前CPython3.12.14能解析3000层JSON，返回CONTENT_INVALID_SCHEMA而非测试预期CONTENT_INVALID_JSON。
- `test_websocket_uses_auth_frame_and_personal_projection_on_reconnect`、`test_outsider_websocket_never_receives_a_snapshot`：WS尚未实现（T12）。
- `test_demo_npc_is_private_and_cannot_change_game_facts`：NPC talk尚未实现（T14）。

保留这些失败的断言，未借本轮修改后端逻辑。现有AnyIO BlockingPortal别名产生一项弃用警告。

专项命令（项目根）：

```bash
MONGO_URI=mongodb://127.0.0.1:27017 backend/.venv/bin/python -m pytest backend/tests/api/test_audio_subtitles.py backend/tests/api/test_media.py -q --tb=short
```

前端目录执行`npm run typecheck`、`npm run test:unit`、`npm run build`、`npm run format:check`。后端目录完整命令：

```bash
TWOWORLDS_TEST_MONGO_IMAGE=mongo@sha256:884c055bff8b7144ca44830d01826facd3083b33c4dea44b94a1476c62de3c32 MONGO_URI=mongodb://127.0.0.1:27017 .venv/bin/python -m pytest tests -q --tb=short
```

浏览器验证通过临时`work/t11-2-browser/server.py sqlite|mongo`运行真实uvicorn8017，Vite5187使用对应API；`work/t11-2-browser/check.cjs`驱动两个独立角色context，合成内容不提交。截图`/tmp/t11-2-{sqlite,mongo}-{lighthouse,starline}.png`为本实例临时证据，非仓库发布资源。API测试与前端测试在仓库中可重跑；临时脚本/工具依赖不在提交中。HTTP操作准备测试状态，浏览器实际操作音频控件、手动读取，不声称本轮重做全剧本UI通关。

## 实际兼容与未验收部分

Chromium真实解码/播放通过，不等同人工听感合格。模拟NotAllowedError验证Chrome/Safari类拒播不会抛出未处理异常且不自动重试；Safari、iOS、Android实机均未运行，未确认其有声输出、编码兼容或系统后台行为。异步加载后play仍可能被浏览器拒绝，组件提供主动重试/文字替代，没有绕过自动播放策略。

QA-M04/M07正式资源/版权/听感与手机体验未完成，完整关键演出仍待T11.3。QA-M05仅已实现的HTTP读档基线与去重、取消部分通过，WS/实时恢复留T12。未将未完成条目改skip/xfail，不自动发布TEST-ONLY库，不自动合并PR。

## 自己试与检查点

按frontend/README和backend/README先启动显式SQLite演示与前端；正式书架目前应为空，不自行发布内容。用前端单测验证交互，用上面的双适配器专项生成隔离TEST-ONLY发布库验证授权。可对照AudioManager.update→protectedAudio→start/play→AudioControls→SubtitleDisplay理解从确认事实到声音/文字的链路。

完成本轮后停止等待用户审查；下一环节是T11.3复杂因果演出，仅介绍，不执行。
