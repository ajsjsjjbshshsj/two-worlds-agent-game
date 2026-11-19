# T06.3.3 · 前端邮箱账号认证

实现日期 2026-11-19。分支 `codex/t06-3-3-frontend-email-auth` 从最新远端 `codex/bootstrap` 的 `301d28aae365983f2f08a0f94ec3912667a75c2e` 建立，PR 目标同为 `codex/bootstrap`。基线包含 [PR #32](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/32) 的邮箱认证和 [PR #31](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/31) 已经正式合入的服务端 WS 代码。本次改动只有前端和文档。

## 体验和接口

`Identity.vue` 保留深蓝与金色的双世界视觉。默认显示邮箱登录，也可切到注册和找回。三个表单支持键盘提交、关联标签、完整的自动填充属性及密码显隐。注册校验规范化邮箱、1–40 字符昵称、6 位验证码和 10–128 字符密码。找回成功后返回登录，失败保留待重试的表单。密码和验证码留在页面内存，切模式、完成操作和卸载时清理。

| 操作 | 调用 | 前端行为 |
| --- | --- | --- |
| 申请验证码 | POST /api/verification-codes | 按规范化邮箱与 `register` 或 `reset` 用途分别计时。202 后显示中立提示并开始 60 秒倒计时，429 采用有效的 `Retry-After`。同一邮箱和用途恢复自己的截止时间，后端限频始终有效 |
| 注册 | POST /api/accounts | 200 接受账号概要，进入房间；只在响应 409 后提示邮箱已注册 |
| 登录 | POST /api/sessions | 200 进入房间，401 统一显示邮箱或密码错误 |
| 找回 | POST /api/password-resets | 204 清本地账号与私人状态，要求用新密码重新登录 |
| 启动、恢复与重试 | GET /api/me | 200 确认当前账号，401 清除身份，网络失败或 503 隐藏私人内容并提供重试入口 |
| 登出 | DELETE /api/sessions/current | 204 或服务端已确认会话无效时清状态。超时明确提示撤销尚未确认 |

注册、登录、登出和重置完成后通过 `GET /api/me` 确认当前会话。注册或登录的网络结果未知时，对照确认后的账号邮箱判断是否成功。重置和验证码申请结果不确定时提示下一步，避免自动重发密码或一次性验证码。

## 数据隔离

`services/http.ts` 负责 API 路径校验、请求超时、有限查询参数、固定本地错误及 `Retry-After` 解析。`services/identity.ts` 与 `types/api.ts` 按六个后端接口组装请求并白名单解析账号和会话到期时间。普通 API 与受保护媒体都由浏览器携带 Cookie，不读取 Cookie 内容。请求禁用缓存和重定向。表单、游戏及 API 错误均不显示服务端任意文案。

身份 Store 在确认登录、账号变化、登出、401 或密码重置时推进本地会话代次。房间/书架/游戏同步清理旧私人状态，保留原有请求与读档顺序校验。图片与音频组件按同一代次清除旧请求、对象 URL 和播放。旧媒体请求的 401 不会注销新会话。保持已有 A/B 投影、邀请 Fragment 清除、操作回执、媒体 MIME/32 MiB 限制、字幕和动效。首个登录前读到的邀请在同页内保留，进入房间后仍须明确点击加入。

### PR #33 审查修复：跨标签页账号隔离

`services/session-sync.ts` 在注册、登录、登出与密码重置开始和结束时通知同源标签页，涵盖结果未知的写入。`BroadcastChannel` 通知和本地协调标记只使用随机操作编号、阶段与到期时间。`localStorage` 中的 `twoworlds.auth-context.revision` 和 `twoworlds.auth-context.active.*` 让请求在异步通知送达前也能识别切换。前端继续由浏览器自动携带 HttpOnly Cookie。浏览器支持 Web Locks 时，认证写入和私人数据写入共用同源锁。

收到切换信号后，应用立即隐藏私人界面、推进会话代次，并清理房间、书架、存档、待确认指令、图片、音频和 Blob URL。认证写入完成后才用 `/api/me` 确认账号。私人 API 在发请求和交付响应时检查会话，媒体在创建 Blob URL 前再次检查。迟到的数据和 401 一律按所属代次丢弃。请求在同轮验证中合并，验证本身不广播。遗失结束信号时，协调标记到期后触发一次确认。

重新聚焦、回到前台或从往返缓存恢复页面时也会确认会话。若 `/api/me` 暂时失败，旧身份保留为未确认状态，私人数据与指令仍暂停。成功重试后直接恢复原路由，权限仍由后台判定。`BroadcastChannel` 受限时可通过存储事件和页面恢复确认。两个通知渠道若均被禁用，页面恢复或手动重试提供确认机会。其他源或绕过应用的 Cookie 变更没有同源通知。

## 首次提交验证

| 检查 | 结果 |
| --- | --- |
| 修改前前端基线 | 19 文件、328 通过、0 失败、0 跳过 |
| 最终前端回归 | 19 文件、356 通过、0 失败、0 跳过 |
| 安装、类型检查、生产构建、格式 | `npm ci`、`npm run typecheck`、`npm run build`、`npm run format:check` 均通过 |
| Git | `git diff --check` 通过；前端生产源码无旧认证入口、Bearer、凭证存储或 Cookie 读取调用 |

基线中 57 个旧身份用例（身份 Store、身份组件、Pending 生命周期、Storage 故障和离页保护）改写为 70 个邮箱契约用例，覆盖错误、输入与安全意图。其余 271 个场景用例保留，相关夹具和授权断言按 Cookie 契约适配。另增加 12 个 HTTP 用例和 3 个媒体隔离用例。迁移中首轮 340 项有两处测试装配错误，分别是音频加载参数索引和 RouterLink stub 的插槽，修正后全量无失败。未对用例加 skip 或 xfail。

真实浏览器联调使用 Chromium 与 Vite，通过 TCP 访问基线后端，分别使用真实 SQLite 和 MongoDB 7.0.48。每次使用独立账号和独立浏览器上下文，临时发布库用测试合成图片和音频。两种仓储均验证：

- 202 反馈、密码显隐、Enter 注册及登录，刷新时经 `GET /api/me` 恢复。浏览器 Cookie 为 HttpOnly，浏览器存储检查无认证秘密。
- A 创建房间、B 登录状态下明确加入；双角色分别打开同档，互读对方私有图像返回 404，自己的图片和音频均使用 Cookie 实际返回 200。游戏命令确认后版本推进一次。
- 登出后重新访问存档和授权媒体返回 401；旧页面回到登录页。找回触发实际 429 时按响应倒计时，再申请 reset 验证码；重置后旧会话和旧密码失效，新密码可登录。
- 390、768、1440 CSS 像素的身份布局正常，手机模拟配合减少动态偏好，无页面异常。

验证码使用显式开发模式 ConsoleEmailCodeSender，从被忽略的临时控制台读取。浏览器证据不等同于实际 SMTP 投递、手机真机或 GitHub CI。

## PR #33 审查修复验证

本轮在 PR 原有 356 项通过的基础上增加 16 项，覆盖通知开始及结束、请求与媒体代次、失败恢复和按用途计时。回归中发现匿名找回密码的网络错误提示被等待界面覆盖，修正后保留该用例。MongoDB 首轮联调曾在禁用通知的场景等待超时，重跑完整流程后通过。

| 云端工作区检查 | 最终结果 |
| --- | --- |
| `npm run test:unit` | 20 个文件，372 通过，0 失败，0 跳过 |
| `npm run typecheck`、`npm run build`、`npm run format:check` | 均通过 |
| `git diff --check` | 通过 |

Chromium 156.0.8078.79 通过真实 HTTP 分别连接 SQLite 和 MongoDB 7.0.48。每轮创建两个共用同一枚 HttpOnly `tw_session` Cookie 的标签页。用真实 API 预备账号、房间和存档，在浏览器中登录与登出，并调用页面的登录操作切换已有账号。

| 场景 | SQLite | MongoDB |
| --- | --- | --- |
| B 切换账号时 A 隐藏私人内容，重新确认后显示新账号的房间；B 登出后 A 回到登录页 | 通过 | 通过 |
| 阻塞真实房间及媒体响应后切换账号，迟到响应未恢复旧内容 | 通过 | 通过 |
| `/api/me` 网络中断时隐藏存档和命令，重试成功后重新读档；已确认账号提交游戏命令返回 200 | 通过 | 通过 |
| 连续切换账号；同账号聚焦、可见及 `pageshow` 信号合并为一次 `/api/me` | 通过 | 通过 |
| 禁用 BroadcastChannel 并屏蔽 `storage` 事件后，聚焦恢复时重新确认账号 | 通过 | 通过 |
| 页面 JavaScript 异常 | 0 | 0 |

单测另外模拟注册和密码重置通知、旧 401、验证响应乱序，以及媒体响应在切换后不得创建 Blob URL。真实联调使用隔离测试库、开发控制台邮件和测试素材，浏览器覆盖限于 Chromium。

## 交接与阅读

先看 `frontend/src/views/Identity.vue` 的表单和验证码交互，再读 `stores/identity.ts` 的启动确认、结果未知和会话代次。然后读 `services/identity.ts` 与 `services/http.ts`，对照 `tests/identity.spec.ts`、`tests/components/Identity.spec.ts` 和 `tests/pending-lifecycle.spec.ts`。媒体观察可先打开角色 A 的灯塔存档，再登出或换档，检查旧对象 URL 清理。

T06.3.4 待清理历史浏览器键并按授权重置演示库。准确键名是 `sessionStorage['twoworlds.session.token']`、`sessionStorage['twoworlds.recovery.pending']`，以及 `localStorage` 中以 `twoworlds.recovery.pending.v1.` 为前缀的逐账号记录。本轮从未读取、写入或清除这些键。正式素材发布、真实邮件与生产环境验收另行验证。本环节完成后停在独立 PR 等人工审查。
