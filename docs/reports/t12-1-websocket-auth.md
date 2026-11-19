# T12.1 · 个人存档 WebSocket 握手鉴权

2026-11-19 恢复 [PR #31](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/31)。在原分支 `codex/t12-1-websocket-auth` 的 `95cfb1949eeef6e1391782fe7ba573d116e6e172` 上普通合并目标分支 `codex/bootstrap`。基线为 [PR #32](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/32) 的合并提交 `4c3049f55aaa3249f9b0567fc090cb154a1eb15b`。保留 PR #32 的邮箱注册、登录、找回密码、Cookie 和 CSRF 行为。依赖锁同时包含原 PR #31 的开发依赖 websockets 16.0 与 PR #32 的 Argon2id 依赖。

## 握手和首次读取

1. 浏览器邮箱认证后，打开 `/api/ws/saves/{save_id}`，由浏览器携带 HttpOnly `tw_session` Cookie。
2. `api/routers/websocket.py` 接受唯一且精确匹配白名单的 Origin，无查询参数。HTTP 和 WS 使用同一 `api/auth.py::session_token`，从所有 Cookie 头中要求恰好一个非空 `tw_session`。`IdentityService.authenticate` 校验格式、有效期和撤销状态。
3. `SaveService.read_save` 用认证所得的账号检查存档成员资格并构建个人投影。若 B 连接，收到的第一帧是 `{"type":"snapshot","save":{...}}`，内容与 B 的 HTTP GET 相同。A 的私密装置、线索和观察不发送给 B。重连时重新读取已提交的存档版本。

| 情况 | 行为 |
| --- | --- |
| Origin 缺失、重复、`null`、不匹配，或 URL 有查询参数 | 拒绝 Upgrade，真实 TCP 为 HTTP 403 |
| Cookie 缺失、重复、伪造、过期或撤销 | 拒绝 Upgrade，真实 TCP 为 HTTP 403 |
| 已认证，存档缺失或账号非成员 | Upgrade 后统一 `4404` 关闭，无业务帧 |
| 已连接，心跳时会话过期、登出或找回密码后被撤销 | `4401` 关闭 |
| 错误或未到时机的 Pong、旧认证帧或其他不支持的消息 | `4400` 关闭 |
| 应用层心跳未及时获回应 | `4408` 关闭 |
| 客户端消息超出 4 KiB | TCP 消息上限 `1009`；应用解析 Pong 时同样限制 UTF-8 字节数 |
| 依赖错误 | 关闭连接，无异常详情；已升级连接用 `1011` |

Bearer、URL token、消息帧及客户端声明的 `account_id`、`role`、`pair_id` 均不参与身份判定。旧首帧认证和对应等待配置已移除。

## 心跳和断开

等候下一轮心跳时，连接可立即处理客户端断开。每次发 `{"type":"ping","id":N}` 前用原 Cookie 会话重新认证，确认账号一致。客户端在 5 秒内回复 `{"type":"pong","id":N}`，ID 必须是对应整数。默认心跳间隔为 10 秒。登出与密码重置的失效在服务端下一轮复核时体现。一个接收循环管理定时器，断开后退出，无独立心跳任务。

## 验证

在 Linux / Python 3.12 上使用真实 SQLite 和 MongoDB 7.0，两套工作树连接同一个临时 Mongo 实例，测试夹具使用独立随机数据库。专项通过新邮箱接口注册账号，通过真实 HTTP 登录取得 TCP 测试所用的 Cookie。两项 TCP 用例使用开发启动器分别连接 SQLite、MongoDB，显式注入隔离测试剧本，并验证合法握手、HTTP/WS 快照一致、非法握手 HTTP 403 与缺档 `4404`。两项原平台 WS 契约保留投影、重连与拒绝外人的断言。

在 `backend` 目录设置 `MONGO_URI` 指向真实测试 MongoDB，设置 `TWOWORLDS_TEST_MONGO_IMAGE` 指向既有仓储断网测试可用的本地镜像，再运行：

```bash
uv run --locked python -m pytest tests/api/test_websocket.py tests/contracts/test_platform.py -k websocket -q
uv run --locked python -m pytest -q
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv lock --check --offline
git diff --check
```

| 运行 | 通过 | 失败 | 错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| 合并基线完整 pytest（首次） | 1284 | 14 | 33 | 0 |
| T12.1 完整 pytest（首次） | 1358 | 7 | 22 | 0 |
| WebSocket 专项与原契约 | 58 | 0 | 0 | 0 |
| 修复分支复跑首次失败和错误的 28 个用例 | 26 | 2 | 0 | 0 |
| 补强限频测试时钟后，复跑完整限频文件 | 12 | 0 | 0 | 0 |

首次全量期间，临时 MongoDB 7.0.48 容器以退出码 14 停止。更换为独立 tmpfs、提高文件描述符上限的同版本容器后，基线受影响的 19 个用例全部通过；修复分支受影响的 23 个用例也全部通过。按用例 ID 合并全量与复跑证据，基线共 1330 项，1303 通过、27 项仍记录为失败或错误；修复分支共 1386 项，1384 通过、2 项历史失败，零新增失败。此统计包含复跑，并非单次全量输出。原 WS 重连契约改名以反映 Cookie，其断言保留。相对基线新增 56 项 WS 专项。

- 基线的 21 个验证码测试失败或装配错误来自异步投递与测试取码竞争。共享注册助手等待后台投递完成后取码，修复分支完整回归未再出现此类错误。
- 三项限频测试用真实时钟要求 Retry-After 精确等于 60，CPU 开销使其偶发少一秒。用例使用项目已有测试时钟固定窗口；双实例用例共享同一时钟。原断言、真实数据库和生产限频行为保留。
- 两项历史失败在基线与修复分支一致：深层 JSON 归类为 `CONTENT_INVALID_SCHEMA`，测试期待 `CONTENT_INVALID_JSON`；NPC 契约返回 HTTP 422 `UNKNOWN_ACTION`。
- Ruff check、Ruff format、离线锁与 Git diff 检查均通过。上述结果为本地运行证据。

## 阅读入口和范围

先看 [WebSocket 路由](../../backend/src/twoworlds/api/routers/websocket.py) 与 [共享 Cookie 解析](../../backend/src/twoworlds/api/auth.py)，再看 [订阅生命周期](../../backend/src/twoworlds/realtime/subscriptions.py) 与 [专项测试](../../backend/tests/api/test_websocket.py)。可运行上方专项命令观察两个角色的 HTTP/WS 投影对照，以及密码重置后两个旧会话同时失效。实时版本广播与前端邮箱/重连流程留待各自任务。原 PR 等待人工审查。
