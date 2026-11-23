# T16.1 / T16.4 · 双浏览器端到端验收结果

基线：`codex/bootstrap @ 8b10ee6`（PR #52 已合并）。任务分支：`codex/t16-acceptance`。
执行日期：2026-11-23。执行环境：Windows 11 本机，Python 3.12.4（backend/.venv），Node 20.19.0 / npm 10.8.2，Playwright 1.62.0（dev 依赖，已入 uv.lock）。

## 测试方法

`frontend/e2e/t16_dual_browser.py`：真实 FastAPI 子进程（`twoworlds.dev.create_dev_app` + 隔离 TEST-ONLY 封存发布库）+ 生产 Vite preview（`/api` 同源代理，含 WS）+ **两个完全独立的浏览器上下文**（独立 Cookie / LocalStorage / Session / 网络）。不使用任何 HTTP/WS 响应桩；唯一开发适配器是 console 邮件传输（验证码打印到子进程控制台）。

每个上下文记录**全部** `/api/*` 响应正文与 WebSocket 帧，用于跨角色私密泄露断言；私密标记取自正式剧本 JSON 中角色私有线索原文（已公开分享的线索除外，另做"分享后双方可见"正向断言）。

## 环境与命令

| 运行 | 命令（frontend 目录） | 结果 |
| --- | --- | --- |
| Edge 桌面 + SQLite | `T16_STORAGE=sqlite ../backend/.venv/Scripts/python.exe e2e/t16_dual_browser.py` | 15/15 通过 |
| Edge 桌面 + 真实 MongoDB 8.0.34 | `T16_STORAGE=mongo MONGO_URI=... python e2e/t16_dual_browser.py` | 15/15 通过 |
| Chrome 157 桌面 + SQLite | `T16_BROWSER=chrome T16_STORAGE=sqlite ...` | 15/15 通过 |
| 手机竖屏模拟 390x844 触控 | `T16_TOUCH=1 T16_VIEWPORT=390x844 ...` | 15/15 通过 |
| 手机横屏模拟 844x390 触控 | `T16_TOUCH=1 T16_VIEWPORT=844x390 ...` | 15/15 通过 |

浏览器版本：Edge 158.0.4370.33、Chrome 157.0.8103.79（系统通道，非 Playwright  bundled Chromium）。

## 15 项检查（每次运行均执行）

1. register-three-accounts：A/B/外人三账号经验证码注册。
2. ui-login-two-independent-contexts：两上下文分别 UI 登录。
3. ui-create-and-join-pair：A UI 建房、B 经邀请 fragment UI 加入。
4. two-scripts-entered：双方 UI 进入灯塔与星轨两个独立存档。
5. lighthouse-full-cooperation-both-endings-votes：14 步 UI 行动（含分歧票与改票）通关，双方页面经 WS 同步到同一版本。
6. private-isolation-http-ws-page-after-lighthouse：A/B 的全部 HTTP 正文、WS 帧、页面 DOM 均不含对方私有线索；已分享线索双方可见。
7. api-tamper-media-receipt-role-outsider：A 读 B 私有媒体 404；A 查 B 的回执 `{accepted:false}`；命令夹带 `role` 字段 422；外人读存档 404。
8. starline-independent-progress：星轨 10 步 UI 行动到 decision。
9. script-isolation-lighthouse-unchanged：灯塔存档版本/完成态不受星轨操作影响。
10. concurrent-submit-and-idempotent-replay：同预期版本并发提交一胜一 409；原包络重放返回原回执 `duplicate:true`。
11. offline-reconnect-convergence：A 断网期间 B 推进；A 恢复后刷新收敛到权威版本。
12. refresh-keeps-progress：双方刷新后进度保持。
13. service-restart-then-finish-starline：终止 API 进程并以同库重启；双方重连后继续提交至通关。
14. relogin-restores-both-saves：清 Cookie 重新登录后两存档均恢复且完成态正确。
15. private-isolation-final：终态再次全量隔离断言。

## 证据

- 逐次运行的捕获计数与检查清单：`docs/reports/t16-evidence/t16-*.json`（含每角色 HTTP 响应数与 WS 帧数，例如 mongo 运行 A=90 条 HTTP/35 帧、B=94/36）。
- 运行日志保留在本机 `work/t16-*.log`（不入库）。
- 失败修复记录：开发过程中修正的是**测试脚本**问题（卡片渲染竞态、分享线索误判为私密、重启后重复封存发布库、无变化投票 422），未发现产品侧私密泄露；所有隔离断言均对真实响应生效。

## 回归

- 前端：`npm run typecheck` 通过；`npm run test:unit` 27 文件 468 项通过；`npm run build` 通过（e2e 使用生产构建）。
- 后端静态：`ruff check .`、`ruff format --check .`、`uv lock --check --offline` 通过。
- 后端全量（SQLite + 真实 Mongo，含新增 `tests/t16_backup_restore.py`）：见下方"后端全量"行与 PR Checks。
- CI：新增 `acceptance-e2e` job（sqlite/mongo 矩阵，真实 Mongo service + Playwright Chromium），复用现有工作流；既有 backend/frontend/deployment-smoke/database-recovery job 不重复执行相同测试。

后端全量（SQLite + 真实 Mongo，37 分 15 秒）：**1730 passed, 4 failed, 2 errors**。6 项非通过全部在**未改动的基线主目录**复现，属本机 Windows 既有环境限制，非本轮回归：

| 用例 | 原因 | 对照 |
| --- | --- | --- |
| test_command_restart::test_killed_api_process_recovers_receipt_and_private_views[sqlite/mongo] | 子进程回环连接超时（Windows 既有问题） | 基线同样失败 |
| test_websocket::test_dev_launcher_serves_real_websocket_over_loopback[sqlite/mongo] | 同上 | 基线同样失败 |
| tests/ai/test_openai_compatible.py::test_malformed_or_unaccepted_response_is_rejected[超长参数] ×2 | Windows 环境变量上限 32767 字符，setup 阶段 ValueError | 基线同样 ERROR |

上述用例在 CI（ubuntu）由 backend-tests 矩阵执行；本 PR Checks 复核。本轮新增的 `tests/t16_backup_restore.py` 在全量中通过。注意：本轮双浏览器 e2e 在**同一台 Windows 机器**上成功启动并连接子进程 API（含 WS），说明回环子进程本身可用；pytest 内这两个夹具的失败路径与 e2e 不同，已登记为待排查环境问题，不冒充通过。

## 未执行 / 未验证

- iPhone / Android / iPad 真机、Safari（本机无环境）：见 devices.md，标记未执行。
- 软键盘弹出遮挡：仅 VisualViewport 逻辑有单测，真机未执行。
- 正式域名 HTTPS/WSS 公网验收：deployment-smoke 在 CI 以自签证书回环验证，公网未执行。
- 负载/并发规模、长时间稳定性：未执行。