# TwoWorlds 前端

T06.3.3 接入邮箱注册、登录与密码找回。房间、书架、游戏与受保护媒体使用相同的 HttpOnly 会话。T10.1 与 T10.2 报告中的匿名账号、恢复密钥与提醒是历史设计，现行流程见 [T06.3.3 报告](../docs/reports/t06-3-3-frontend-email-auth.md)。

## 本地运行

使用 `package.json` 支持的 Node 版本。先按 [后端开发说明](../backend/README.md#17-开发专用http启动器t102)启动显式 SQLite 或 MongoDB 后端，独立本地验证可用 `TWOWORLDS_EMAIL_MODE=console` 从后端开发控制台查看验证码。

在 `frontend` 目录：

```bash
npm ci
VITE_API_BASE_URL=http://127.0.0.1:8016 npm run dev -- --port 5186 --strictPort
```

在 PowerShell 中先执行 `$env:VITE_API_BASE_URL='http://127.0.0.1:8016'`，再运行 `npm.cmd run dev -- --port 5186 --strictPort`。浏览器打开 `http://127.0.0.1:5186`。后端 `TWOWORLDS_ALLOWED_ORIGINS` 须精确包含该来源。前后端端口可不同，本地联调用同一主机名与协议，避免将 `localhost` 与 `127.0.0.1` 混用。Vite 环境变量是公开配置。

## 页面与会话

| 路由 | 行为 |
| --- | --- |
| / | 邮箱登录、验证码注册、密码找回、当前账号和登出 |
| /pairs | 查看自己的房间、创建房间或确认加入 |
| /pairs/:pairId | 查看成员和角色，未满员的 A 生成或刷新邀请 |
| /pairs/:pairId/library | 列出已发布剧本和本人存档，按绑定版本开始或继续 |
| /saves/:saveId | 展示个人快照和可用操作，按授权读取图片、音频和字幕 |

首次加载通过 `GET /api/me` 验证 Cookie。接口 401 表示会话无效，保护页面返回登录，私人数据清理。网络异常和 503 在启动时显示验证重试入口，业务请求失败时保留上次确认的会话。注册或登录结果未知时只尝试安全的 `GET /api/me`，密码不会自动重发。登出超时会明确提示撤销尚未确认。

账号变化、确认为登出、会话失效或密码重置会推进会话代次。房间、书架和游戏利用代次丢弃迟到结果，场景与音频停止旧加载并释放对象 URL。邀请只经 URL Fragment 传递，读取后即从地址栏清除，保留到明确确认加入或离开当前会话。

HTTP 和媒体均使用 `credentials: 'include'`、`cache: 'no-store'`、`redirect: 'error'`。前端不读或存 Cookie，也不读取历史认证键。历史键和演示库清理由 T06.3.4 单独执行。

**正式目录当前为空。** 非空书架依靠已发布内容。开发验证用隔离发布库和测试素材，详细结果和阅读路径见 [T06.3.3 报告](../docs/reports/t06-3-3-frontend-email-auth.md)。

```bash
npm run typecheck
npm run test:unit
npm run build
npm run format:check
```

## T11.2 · 基础音频与字幕

游戏页在场景下方新增声音与字幕区域。首次打开不播放；点击“启用声音”启动当前环境音。可分别调整环境音/设备音效/旁白音量，全局静音或关闭声音，旁白可暂停、继续、跳过与主动重播。字幕独立开关和字号，静音/音频不可用仍可阅读当前角色授权内容。进入后台停止声音；回来需主动开启。现有本地启动命令与API地址不变。

读取顺序：`types/audio.ts` → `services/audio-assets.ts` → `services/media.ts` → `services/audio.ts` → `stores/audio.ts` → `components/game/AudioControls.vue`、`AudioSettings.vue`、`SubtitleDisplay.vue` → `views/Game.vue`。后端现有音频MIME白名单、32MiB上限与角色权限不变。首次快照基线不重播历史；只有后续确认快照中的新Cue触发一次性声音。手动刷新获取搭档进度，尚无WS实时同步。

正式发布目录仍空，不会出现可供正式游玩的音频内容。测试的合成WAV与临时发布库严格隔离，不能作为正式配音。现有内容只提供整段中文transcript/alt_text，没有说话人或逐句时间戳；默认speaker=null、start_time=0、duration=null。资源失败不阻断行动，授权文字保留。没有新增依赖、ESLint或大型音频框架。实际检查结果、已知后端基线失败、Chrome与真机验证界限见[报告](../docs/reports/t11-2-audio-subtitles.md)。

PR #27审查修复：`presentation.operation_sfx`由服务端标记当前授权的设备操作声音，发现线索仅开放资源和文字；只有新命令成功CAS提交的`audio_events`触发对应声音。客户端验证其接受版本与Cue权限，使用接受版本+cue_id+asset_id去重，连续实际操作可再次发声，同请求重试不重放。`gameApi.read`不恢复历史事件，丢响应再确认不补播；没有可靠事件日志或伙伴操作音效追溯。阅读新增`backend/domain/audio.py`与`application/audio.py`，再读`services/game.ts`、`types/game.ts`和`audio-assets.ts`。详见[T11.2审查修复报告](../docs/reports/t11-2-audio-subtitles.md#pr-27-审查修复2026-11-17)。

## T11.3.1 · 两个确认状态驱动的因果演出原型

场景现在可在相邻确认版本发生授权false→true时播放短反馈：灯塔A时钟箱通电、星轨B声呐就绪。初次读档/刷新只显示最终状态，同版本不重播，跳过多个操作时不补演。后台、切档/角色/凭证、离页或减少动态会取消旧轨道；没有动画支持也能继续看正确状态并操作。声音开关不控制动画，演出不生成任何操作音效，T11.2的audio_events保持原样。

阅读顺序：`services/causal-performance.ts` → `performance-animation.ts` → `SceneRenderer.vue` → `LighthouseScene.vue`/`StarlineScene.vue` → 新增两个performance测试文件。运行`npm run test:unit -- tests/causal-performance.spec.ts tests/performance-scene.spec.ts`学习机制；前端全量251通过，typecheck/build/format通过。[详细报告](../docs/reports/t11-3-1-causal-performance.md)含真实双角色检查和临时TEST-ONLY演示库的观察步骤。正式目录仍空，未发布正式素材，未宣称Safari/iOS/Android真机通过；本轮只完成T11.3.1。

## T11.3.2 · 合作节点与可跳过结局原型

复用CausalPerformance与原WAAPI播放器：灯塔包含光束聚焦、供电、维修/航道就绪；星轨包含声呐就绪、扫描定位、导轨连接，各3处物理合作反馈。两套关键演出只从相邻确认的decision→completed启动，按当前公开结局显示引航/待潮或救援/归站。右下角“跳过演出”支持键盘和触屏，仅取消视觉，不发命令、不改存档/版本，也不停止或重写原旁白字幕。首读、同版本、跳版本或减少动态只保留正确最终状态，仍需手动获取搭档进度。

该阶段原251项保留，新增77，历史全量328通过；typecheck/build/format通过。`npm run test:unit -- tests/cooperative-performance.spec.ts tests/cooperative-scene.spec.ts`可学习新增机制。先读causal-performance.ts的字段与显式转场，再读performance-animation.ts、SceneRenderer的skip和两个SVG的最终状态。[详细报告](../docs/reports/t11-3-2-cooperative-performances.md)含真实SQLite/TCP四结局双角色检查、临时测试库观察方式和限制。正式素材未发布，真机未验收，本轮不表示QA-M01～M07全部完成。
