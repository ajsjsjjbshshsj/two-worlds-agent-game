# TwoWorlds 前端 · T11.1

当前/saves/:saveId已接入Game场景与通用装置/行动，复用个人投影与命令API。只有服务端确认才更新设备；失败保留旧快照，未知结果仅可手动确认同请求，搭档变化暂用手动刷新。图片带Bearer读取并在切档/登出/卸载清理；不播放音频。

本轮146项通过（原125未改），类型/构建/格式通过；真实SQLite/Mongo在隔离测试内容中通过两剧本UI通关。正式目录仍为空，不自动发布。原型SVG/CSS不是正式美术，完整Cue/音频/WS留后续。运行命令沿用下方T10.2步骤，新增阅读见[T11.1报告](../docs/reports/t11-1-scene-device.md)。

以下为T10.2运行与架构说明，存档入口展示部分已由Game替代，其历史测试数以当前146项为准。

# TwoWorlds 前端 · T10.2

已实现身份创建/恢复、一次性密钥保护、房间创建/加入/邀请刷新、成员状态、正式剧本书架和本人存档入口。游戏操作、场景/音频、WebSocket、PWA与AI尚未实现，存档入口明确说明T11后续范围。

## 本地运行

使用Node20.19.0/npm10.8.2或package.json支持的Node版本。前端依赖及package-lock本轮未改。先按[后端说明](../backend/README.md#17-开发专用http启动器t102)在另一个终端启动后端：

```powershell
cd F:/two-worlds-agent-game/work/pr-t01-1-schema/frontend
npm.cmd ci --engine-strict --registry=https://registry.npmjs.org
$env:VITE_API_BASE_URL='http://127.0.0.1:8016'
npm.cmd run dev -- --port 5186 --strictPort
```

本轮真实SQLite/Mongo浏览器验收使用这两个回环端口，验收后本轮服务已关闭。启动后的页面地址为http://127.0.0.1:5186；后端Origin须精确匹配。VITE变量是公开配置，禁止放凭证。Vite不自动启动/切换数据库，无内置代理或线上部署。

## 页面与流程

| 路由 | 能做什么 |
| --- | --- |
| / | 创建、恢复、一次性密钥确认、各身份提醒、登出 |
| /pairs | 创建/列出本人房间、明确接受邀请 |
| /pairs/:pairId | 角色和服务端成员数；未满员A生成/刷新邀请 |
| /pairs/:pairId/library | 正式元数据+本房间存档概要，开始或继续 |
| /saves/:saveId | 从已有个人投影提取本人角色/场景/版本/完成状态 |

受保护路由先验证身份，401清会话及私人列表并返回身份页，不清Pending。角色最终由后端认证确定。人数不是在线状态，搭档加入后手动刷新。

创建身份后先保存密钥。有邀请时，确认保存后进入房间页，再明确点击加入。邀请链接仅用URL Fragment；启动时先读入内存、立即replaceState清理地址，不自动加入。复制失败有手动备用。刷新/关闭会丢失邀请，需重新打开原链接；满员后清除已发出的无用内存邀请。

**正式目录当前为空。** 真实GET /api/scripts返回空数组时显示正常空状态，不能硬编码灯塔/星轨卡片。非空书架测试使用独立test-only发布库，不代表素材授权或正式上线。

## 状态、安全与版本

- token仅在内存/sessionStorage的twoworlds.session.token，只通过Bearer头发送。Recovery Key仅在页面局部内存，不进Pinia、storage、URL或日志。
- Pending仅保存twoworlds.recovery.pending.v1.<account_id>的四字段元数据：account_id、display_name、created_at、pending:true。恢复B只清B，确认/二次放弃一项不影响其他身份，登出保留全部提醒。
- read/write/remove/invalid独立跟踪；对应成功操作只清自己的瞬时问题。invalid保守保留到新页面重新检查，不识别的原记录不改写/删除。故障保留内存提醒，浏览器存储不等于密钥备份或跨设备同步，清理/禁用存储时不能保证重开保留。
- SPA离开实际展示密钥的页面时明确确认；取消或后续guard失败均保留密钥，真正卸载才清密钥但不清Pending。保存确认后不再拦截。beforeunload仍保护刷新/关闭，但[浏览器限制](https://developer.mozilla.org/en-US/docs/Web/API/Window/beforeunload_event)下不能保证系统强制终止时提示。
- 旧版无归属全局标记保留独立警告，不猜测迁移；未实现跨标签页实时同步。
- 邀请只留内存与明确分享界面，不进storage/query/path/日志。创建/刷新结果不明时先刷新列表，不自动重试。
- HTTP保留no-store、omit、拒绝重定向、超时、安全本地错误与原路径白名单。只有GET /api/saves可通过独立query选项增加合法Identifier的pair_id，原始路径里的query/fragment仍拒绝。
- 每剧本卡片取数值最新的目录元数据，按ID稳定排序；存档按pair_id+script_id关联。旧档只GET原save_id，仍用原script_version，目录介绍不同版本会标注；下架故事的既有档也保留原入口。
- 新档只在服务端确认两人加入后创建，用真实content_version并校验返回版本。身份/房间切换、读档请求代次和页面卸载阻断迟到响应，不串入另一身份或房间。
- 网络错误保留可恢复的会话；登出204或401才清本机会话。服务端验证过期，本地时间不作为认证依据。

## 验证与学习

```powershell
npm.cmd run typecheck
npm.cmd run test:unit
npm.cmd run build
npm.cmd run format:check
```

当前125通过、0失败/跳过；原82测试文件与fixture完全未改。新增43：告警/路由10、资源HTTP8、房间书架Store17、页面路由8。严格类型、构建和格式均通过。单元测试使用响应桩；另分别用真实SQLite/Mongo TCP、三个独立Edge上下文完成房间/书架验收。390px模拟不是手机真机；正式空目录与test-only非空目录分开验证。

前端锁未改，历史审计生产依赖0/开发4项moderate为T10.1证据，本轮未重审或声称消除。完整结果与限制见[T10.2报告](../docs/reports/t10-2-identity-room-library.md)，历史身份实现见[T10.1报告](../docs/reports/frontend-identity.md)。

阅读顺序：identity Store独立告警 → Identity路由离开保护 → types/resources白名单 → pairs/library服务和Store → Router/页面 → 测试。例如旧档1.0.0、目录2.0.0：继续只读取原save_id，不POST新档或替换版本。

本轮交付后停止等待审查，下一阶段T11只介绍，不自动执行。

## T11.2 · 基础音频与字幕

游戏页在场景下方新增声音与字幕区域。首次打开不播放；点击“启用声音”启动当前环境音。可分别调整环境音/设备音效/旁白音量，全局静音或关闭声音，旁白可暂停、继续、跳过与主动重播。字幕独立开关和字号，静音/音频不可用仍可阅读当前角色授权内容。进入后台停止声音；回来需主动开启。现有本地启动命令与API地址不变。

读取顺序：`types/audio.ts` → `services/audio-assets.ts` → `services/media.ts` → `services/audio.ts` → `stores/audio.ts` → `components/game/AudioControls.vue`、`AudioSettings.vue`、`SubtitleDisplay.vue` → `views/Game.vue`。后端现有音频MIME白名单、32MiB上限与角色权限不变。首次快照基线不重播历史；只有后续确认快照中的新Cue触发一次性声音。手动刷新获取搭档进度，尚无WS实时同步。

正式发布目录仍空，不会出现可供正式游玩的音频内容。测试的合成WAV与临时发布库严格隔离，不能作为正式配音。现有内容只提供整段中文transcript/alt_text，没有说话人或逐句时间戳；默认speaker=null、start_time=0、duration=null。资源失败不阻断行动，授权文字保留。没有新增依赖、ESLint或大型音频框架。实际检查结果、已知后端基线失败、Chrome与真机验证界限见[报告](../docs/reports/t11-2-audio-subtitles.md)。
