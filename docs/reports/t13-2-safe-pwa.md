# T13.2 · PWA 安装、安全缓存与离线恢复

2026-11-22。基线为 PR #41 已合并的 `f2c9d10884f77a0c6a4357a0fb5faf557206945e`。分支 `codex/t13-2-safe-pwa`；工作树 `work/t13-2-safe-pwa`。本轮不改后端、身份协议、数据库、规则、剧本、音频系统或 IndexedDB 格式，不开发 T14/T15/T16。

## 设计和阅读顺序

1. `frontend/pwa/build.ts`：仅生产构建启用的 Vite 插件，从实际 JS/CSS 构建产物和固定公开文件生成 SHA-256 白名单、manifest、离线 HTML 和原生 SW。没有新增依赖，锁文件不变。
2. `frontend/src/pwa/worker.ts`：`classifyRequest` 分类，`attachWorker` 安装/激活/读取；安装是唯一写入缓存的阶段。
3. `frontend/src/services/pwa.ts` 与 `components/PwaStatus.vue`：安全上下文中的生产注册；仅收到浏览器安装事件才显示按钮，更新只提示、不强制激活或刷新。
4. `components/NetworkGate.vue`、`services/http.ts` 与 `views/Game.vue`：断网时保留可读内存内容，禁用业务表单和回执请求；静音、字幕、设备定位和跳过演出仍可用。明确离线时在 fetch 前拒绝请求。
5. `services/save-recovery.ts`：沿用原恢复器，每次离线暂停后必须重新验证会话；再由原 Game Store 读取权威快照和核对原 UUID，不创建第二套同步逻辑。
6. `frontend/tests/pwa*.spec.ts`、`frontend/e2e/pwa_cache.py`、`pwa_sqlite.py`、`pwa_subpath.py`：分别观察单元行为、真实 Cache Storage、真实 SQLite 恢复及子路径生产构建。

普通网页仍可在线使用。开发模式不注册 SW，也不插入仅在生产构建生成的 manifest 链接。`index.html` 增加主题色和 Apple touch 图标；`App.vue` 装配提示和离线控件门控。没有修改原路由表或其身份保护逻辑。

## Manifest 和图标

| 字段 | 默认根路径构建 |
| --- | --- |
| name / short_name | TwoWorlds |
| id / start_url / scope | `/` |
| display / lang | standalone / zh-CN |
| theme_color / background_color | `#091725` |
| description | 两个人、两个世界；与搭档合作探索并在线确认进度 |
| icons | 原创 192px/512px PNG、512px maskable PNG |
| Apple touch | 原创 180px PNG |

图标为双圆与连接桥，没有字体、真实用户数据、第三方图片或剧本信息。源码 `frontend/pwa/make_icons.py` 可重建，CC0-1.0 声明在 `frontend/public/pwa/LICENSE.txt`；maskable 主体保留在中心安全区域内。图标只用于应用安装，不代表正式剧情美术完成。

支持显式同源绝对 base，例如 `/worlds/`。该构建实际验证 manifest 的 id/start_url/scope、图标、SW 和离线资源均在 `/worlds/` 内；不接受相对、跨源或含 API/WS 路径段的部署 base。无本机地址或私人配置写入 manifest。

Chrome/Edge 的安装按钮只在真实 `beforeinstallprompt` 到来后出现；已使用或取消的事件不重复调用。其他情况下展示浏览器菜单说明，iPhone/iPad 单列 Safari 分享菜单的“添加到主屏幕”。没有申请推送、后台同步、麦克风或其他权限。

## 精确缓存白名单

当前根路径生产构建恰有 10 条，所有内容均为公开构建字节：

| 资源 | 数量 |
| --- | --- |
| Vite 版本化 JS / CSS | 2 |
| `manifest.webmanifest` | 1 |
| 独立公共 `offline.html` | 1 |
| 四个安装图标 | 4 |
| `pwa/offline.css`、`pwa/offline.js` | 2 |

**不预缓存 `index.html`，不保存任何导航的网络响应。** 默认发布目录和后端完整剧本不在静态白名单内。前端包包含公开客户端代码，不含玩家会话、服务端谜底文档、未发布内容、私人投影或私聊。浏览器测试逐条比较真实缓存响应的 SHA-256 与构建登记，并检查私人标记、真实测试邮箱和私人线索不存在于缓存正文。

- 安装请求固定 `credentials: omit`、`redirect: error`、`cache: no-store`，带 SRI 完整性。只接受成功、非重定向、非 opaque 响应。保存时仅保留已验证公开字节与 Content-Type、Cache-Control、nosniff 头，不持久化上下文头或 Set-Cookie。
- 运行时不写 Cache Storage。精确 URL 匹配前核对方法、同源、scope、API/WS 路径段、编码、查询、fragment、Authorization 和资源目的地。浏览器带 Cookie 的脚本/样式等子资源也只可能读已验证公开字节；带凭证的动态 fetch 不会成为缓存写入来源。
- 所有 `/api/**`、编码 API 路径、跨源响应、POST/DELETE、存档、身份、验证码、密码、私聊、回执及受保护媒体均走原网络逻辑，既不拦截成离线 HTML，也不克隆/写入缓存。
- 导航只走网络，不以旧页面离线回放。网络失败时返回当前构建的公共离线文档；该文档没有用户数据读取代码。普通刷新与 PWA 起始路径遵循同一边界。
- 不读写 IndexedDB。原有限待确认机关记录继续由 T12 管理，不存私人快照，也不转为自动重发队列。

## 安装和更新生命周期

缓存名称由部署路径前缀和内容版本组成。静态字节或 Worker 源码改变会产生新版本；公开资源名/摘要与该 SW 一起构建，重复构建结果可复现。安装不完整时删除该次缓存并失败。激活只清理本部署前缀的旧版本，不清除其他应用缓存、Cookie、IndexedDB 或待确认 UUID。

没有 `skipWaiting` 消息，也没有 `controllerchange` 强刷。当前页面收到新版本等待提示后，先处理当前请求，再关闭所有 TwoWorlds 窗口；浏览器自然激活新 Worker。未确认操作仍留在原有记录中。实测在待确认命令存在时 v2 只进入 waiting；窗口退出后激活并清理 v1。再让 v3 的预缓存 CSS 返回 302 到私人 API，安装被拒绝，v2 仍可用且 v3 部分缓存被清理。

## 完整恢复流程及真实 SQLite 证据

1. 玩家在线登录，打开原存档。现有服务先持久记录普通机关命令，再提交原 UUID。
2. SQLite 已把 A 的检查操作提交为 v1；浏览器测试仅截断返回响应并断网，不 mock API 或规则。离线门控禁用新操作，原 UUID 不删除。
3. A 离线期间，真实 B 通过 API 检查航道图，将**同一存档**推进到 v2。
4. 关闭整个浏览器进程，用同一独立配置在离线状态重新打开 manifest 起始路径。只得到公共离线页，邮箱、存档标识、私人线索和游戏快照均不显示。
5. 联网后点击有效的“重新连接”。现有 HttpOnly Cookie 经 `GET /api/me` 重新验证。普通在线应用恢复，不把 onLine 当作身份凭证。
6. 玩家通过房间、书架继续原存档；读取服务端 v2 投影后，查询原 UUID 的回执，确认原操作为 v1。自动恢复不再 POST 原命令。
7. 现有角色、会话、版本与待确认门控全部满足后，玩家手动提交一次新配置，进度到 v3。
8. 直接读取真实 SQLite 聚合：回执版本严格为 `[1,2,3]`，原 UUID 恰好一条。真实受保护音频读取返回 200，之后再次审计缓存，没有 `/api/` 键、测试邮箱或完整私人线索。

重新打开的起始页不会猜测上一个私人路由，用户从原房间书架继续。只有原机制允许持久化的有限机关命令能跨关闭恢复，NPC 私聊或分享正文不因此增加持久化能力。会话被服务端拒绝时仍显示登录页，不能凭旧缓存进入私人页面。已有版本防回退、前后台门控、Blob 释放、音频启用与字幕逻辑保持原样。

## 实际验证

本机 Windows，Node 20.19.0 / npm 10.8.2，Python 3.12.4，Playwright 1.62.0，Edge 158.0.4370.33。浏览器检查使用真实生产构建和 Vite preview，不以开发模式代替 SW 验证。

| 命令 / 场景 | 结果 |
| --- | --- |
| `npm.cmd ci --engine-strict` | 成功；依赖锁不变，无新增依赖 |
| `npm.cmd run typecheck` | 通过 |
| `npm.cmd run test:unit` | 463 通过、0 失败；原 434 项未修改，新增 29 项 |
| `npm.cmd run build` | 通过，103 个模块；JS `index-BJuryU9Q.js`、CSS `index-CpP-kujv.css` |
| `npm.cmd run format:check` | 通过；检查范围扩展到 PWA 构建和公开离线文件 |
| `python e2e/pwa_cache.py` | 通过：真实 SW/Cache Storage、安装资格、更新、重定向拒绝、不同测试账号与离线恢复；HTTP 为明确夹具 |
| `python e2e/pwa_sqlite.py` | 通过：真实 FastAPI / SQLite / Cookie / HTTP / WS，v1 → 离线 → v2 恢复 → v3 |
| `python e2e/pwa_subpath.py` | 通过：独立 `/worlds/` 生产构建、manifest、scope、离线样式和 10 条缓存 |
| 既有 `python e2e/mobile_layout.py` | T13.1 原 154 个七尺寸布局/交互场景通过 |
| Python 测试工具 Ruff / 格式 | 通过 |
| `git diff --check` | 通过 |
| GitHub CI | 交付 PR 的 Checks 记录实际最终结论；全部既有检查保留 |

缓存专项发送了身份、注册/验证码/密码重置、存档、回执、NPC 路径、图片/音频路径、编码 URL、查询、跨源、带 Cookie、POST/DELETE 和账号切换请求，缓存键数量及完整响应字节均未污染。补充真实 SQLite 媒体与私人文字审计，不把夹具响应当成真实后端证据。浏览器 CDP `Page.getInstallabilityErrors` 返回空列表；普通在线页面在禁用 SW 时仍可使用。

过程中先复现离线门控与恢复鉴权的四项失败后修复；复审补充本地音频/阅读控件不应随业务操作一起禁用的回归。浏览器驱动修正了无痕模式无法安装、等待请求实际结束、原生 fieldset 属性判断及 Windows 测试连接清理；冷安装曾受本轮 preview 的 esbuild 文件锁影响，关闭该拥有进程后重装及全量重验成功。没有删除、skip、xfail 或弱化原有测试。

## 复验和截图

```powershell
cd frontend
npm.cmd ci --engine-strict
npm.cmd run typecheck
npm.cmd run test:unit
npm.cmd run build
npm.cmd run format:check
python e2e/pwa_cache.py
python e2e/pwa_sqlite.py
python e2e/pwa_subpath.py
```

浏览器驱动使用本机已有 Python Playwright/httpx；SQLite API 子进程用项目 `backend/.venv`，先在 backend 执行 `uv sync --locked --group dev`。Linux 对应虚拟环境路径也有处理，可通过 `PWA_BROWSER=chrome` 指定已安装通道；Safari/手机未以该测试冒充。测试拥有的服务器、独立配置和数据库自动关闭，临时报告放在忽略的 `frontend/test-results/pwa`。`frontend/work` 的测试 preview 配置/子路径产物另行忽略，不进入 PR。

- [安装说明与 TEST-ONLY 应用页面](../assets/t13-2/installation.png)：不是原生系统安装弹窗或手机安装完成证明。
- [公共离线页](../assets/t13-2/offline.png)。

## 限制、范围与下一步

**iPhone / iPad Safari、Android Chrome、macOS Safari 真机未验证；未宣称完成操作系统原生安装、主屏图标点击或 T16 完整验收。** 复现的是实际桌面 Edge 安装条件、浏览器关闭重开到 manifest 起始 URL 和真实离线链路。需要 HTTPS 或浏览器认可的 localhost 环境，HTTP 公网不保证可安装。

本轮关键恢复使用真实 SQLite，未另跑本机 Mongo PWA 全链路；已有真实 Mongo 和后端全量仍由 PR CI 执行。正式剧情素材/许可未补齐；不新增离线游戏、自动提交、推送、模型、T14 或生产部署。下一任务需用户指定；可先独立补设备安装实测，或按任务清单讨论 T14 的默认文本工作流。

参考：[MDN Service Worker 生命周期](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers)、[MDN 安装提示支持边界](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/How_to/Trigger_install_prompt)。本轮交付后停止，等待人工审查，不自动合并。
