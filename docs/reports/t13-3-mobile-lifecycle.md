# T13.3 · 音频、字幕、前后台恢复与 PWA 安装验收

基线为 `f417ef9c1b1ea14b7c8ee13d24be3845428bcfe2`，包含已合并的 PR #42。任务分支 `codex/t13-3-mobile-lifecycle`。检查采用生产构建与 Vite preview，经 HttpOnly Cookie 连接本机临时 FastAPI、SQLite 和 WebSocket。媒体来自项目已有的 TEST-ONLY 封存夹具，测试结束后回收独立浏览器配置和数据库。

## 修复与阅读顺序

1. `frontend/src/components/game/SubtitleDisplay.vue` 的字幕段落继承用户设定的字号。原全局段落规则将正文固定为 14px，仅标题随字号变化。Edge 在 375×667 真实计算样式断言上复现，修复后 Chrome 和 Edge 都能用键盘把正文从 16px 调至 28px。
2. `frontend/src/services/audio.ts` 的 `AudioManager.play` 识别 `NotSupportedError`，显示格式不支持，保留字幕替代，并释放对应 Blob。`NotAllowedError` 继续提示浏览器拒播与主动启用。两类错误都受既有失败记录约束，普通快照读取不会自动重试。`frontend/tests/audio.spec.ts` 新增的格式错误回归先失败、后通过。
3. `.gitattributes` 固定离线脚本为 LF。Windows 全新工作树原先受 `core.autocrlf` 影响触发 Prettier 失败，统一后本地检查通过，并保证该静态文件的内容摘要不随检出平台变化。
4. `frontend/e2e/mobile_lifecycle.py` 将音频、权限、字幕、会话和原 UUID 恢复放在同一真实存档上验证；`pwa_standalone.py` 通过 Chrome DevTools 安装、打开和卸载隔离配置中的桌面 PWA。两者共用 `pwa_sqlite.py` 提取的测试环境；原关闭重开用例与断言保留。

## 音频、字幕与前后台矩阵

Windows Edge 158.0.4370.33 与 Chrome 157.0.8103.79，Playwright 1.62.0。每个浏览器执行一条真实 SQLite 生命周期，分别检查 375×667、390×844、430×932、768×1024、1440×900，另检查 844×390 横屏。在 Chrome/Edge 中运行实际原生 `HTMLMediaElement` 和 Blob API，通过 `currentTime` 及 `paused`/`volume` 检查播放和控制行为。自动播放拒绝及不支持格式在 `play()` 注入指定异常。手机尺寸使用 Chromium 设备视口与触控事件。前后台 A～D 用注入的 `visibilitychange` 精确控制时序，未把桌面系统的最小化或手机系统生命周期当作已测。一次 Chrome 独立窗口最小化探测没有在限时内观测到 `hidden`，因此没有作为通过项。

| 验收 | 观测结果 |
| --- | --- |
| 首次进入、手势与拒播 | 首载无音频播放或环境音请求，触控后 native `currentTime` 推进。两种异常下字幕仍可读，手动刷新没有触发重试 |
| 声音、字幕和辅助操作 | 环境音实际音量到 0/1，音效/旁白滑块可用，键盘暂停/继续、静音/恢复、关闭、字幕开关和字号均通过。字幕和行动区域不重叠，所有尺寸无横向溢出，减少动态模式可正常提交命令。旁白主动重播和跳过保留既有组件测试 |
| 已确认音效与场景变化 | 检查日志只解锁媒体，成功调整发射器播放一次。相同进度读取、原 UUID 回执恢复和 WS 重连无补播。合作推进后旧场景声轨释放，旧旁白字幕消失 |
| A · 后台停音和取消演出 | 后台停止原生声轨并撤销 URL，行为门控禁用操作，`clock-power-on` 演出取消。原待确认命令保留供回执核对 |
| B/D · 前台恢复、期间断网及搭档推进 | A 的命令实际提交为 v4，浏览器丢响应。后台断网时 B 将存档推进至 v5。联网前无启用的行动，联网后请求顺序是 `/api/me` → 原存档 → 原 UUID 回执。恢复段有 1 个新的 WebSocket，0 笔自动 POST，0 次新增声音播放。后续动作可继续到 v8。迟到 HTTP/WS 不能回退版本由保留的 T12 单测复验 |
| C · 会话撤销和账号切换 | 后台用真实 API 撤销浏览器会话，前台回到登录页，私人游戏区移除。原音频 Blob 再读失败。B 登录后收不到 A 的私有设备字幕和图片，A 的受保护背景返回 404。B 自己的已读取音频断网后无法从原接口读取，返回书架后该页面全部媒体 Blob 被撤销 |

## PWA、缓存与边界

- Windows Chrome 真实桌面窗口安装资格通过，DevTools 执行安装及启动，`display-mode: standalone` 确认独立窗口。游戏可操作且无横向溢出。关闭独立窗口，在离线状态重新启动安装应用，显示公共离线页，从实际缓存看到 10 个公开键。联网重试回到真实会话并读取原游戏进度。结束时卸载测试应用。该验证没有替代人工点击系统安装菜单或手机主屏图标的测试。复现所用接口见 [Chrome DevTools PWA 协议](https://chromedevtools.github.io/devtools-protocol/tot/PWA/)。
- Edge 生产 preview 的原 PWA 驱动回归通过。检查 manifest、192px/512px/maskable 图标、安装资格、禁用 SW 时在线可用、新版 SW 在未知结果命令期间等待、失败更新保留旧版，以及 10 个实际 Cache Storage 键和按字节计算的摘要。身份、回执、快照、NPC、授权图像/音频及各类动态请求使用明确的 HTTP 测试夹具验证缓存排除。真实后端场景另验证私有线索和 WAV 请求没有落入缓存。
- 原真实 SQLite 关闭浏览器再从 PWA 起始 URL 重开、回执唯一、v1→v2→v3 及 `/worlds/` 子路径生产构建均通过。自动化保留既有 HTTP 补偿、减少动态、幂等与隐私测试。
- **iPhone/Android 真机未验证**。iPad、macOS Safari、真实刘海/安全区、系统音量限制、手机系统冻结/杀进程及从真实手机主屏重开仍待实测。前端轨道音量已验证，正式音频听感、音量设备行为与新资源在本轮范围之外。QA-U04～U06 和 T16 保持待完整验收。桌面 Edge 安装资格通过，实际独立窗口安装执行于 Chrome。

## 复现

在 `backend` 执行 `uv sync --locked --group dev`。在 `frontend` 执行：

```powershell
npm.cmd ci --engine-strict
npm.cmd run typecheck
npm.cmd run test:unit
npm.cmd run build
npm.cmd run format:check
python e2e/mobile_lifecycle.py
python e2e/pwa_standalone.py
python e2e/pwa_cache.py
python e2e/pwa_sqlite.py
python e2e/pwa_subpath.py
git diff --check
```

浏览器脚本使用已安装的 Python Playwright/httpx。`pwa_standalone.py` 需要支持 CDP 安装的桌面 Chrome 和可打开实际窗口的桌面环境。输出写入被忽略的 `frontend/test-results/pwa/`。原布局测试在 `npm.cmd run dev -- --port 5193 --strictPort` 启动后运行 `python e2e/mobile_layout.py`。

Node 20.19.0、npm 10.8.2、Python 3.12.4。前端 **464 项通过**，原 463 项完整保留，新增 1 项。类型、生产构建、格式、Python 验收脚本 Ruff、Git 差异检查通过。原布局测试 154 项通过。GitHub 检查以本轮 PR 的实际记录为准。

下一任务建议从 T14 的默认文本演示和角色上下文隔离开始，并复用现有确定性规则和权限接口。T13.3 到此停止，等待用户审查。
