# T12.1 · 服务端 WebSocket 连接与身份鉴权

2026-11-18。实现基线为远端 `codex/bootstrap` 的 `04cb0d3687e8b410948ffb2238b4a07fecd9c425`，即 GitHub 确认的 PR #29 合并提交。开发分支为 `codex/t12-1-websocket-auth`，PR 目标为 `codex/bootstrap`。 交付前远端合入 PR #30，任务分支接到最新 `6641150e2b2cfbb204394b6cce6fac226e29b3c8`。PR #30 仅改文档，后端代码、测试及依赖与原验证基线一致。

## 接口与协议

本节与下方测试数据记录 PR #31 审查基准中的旧版首帧协议。现行设计以 PR #30 为准，合并条件与迁移清单见本报告末尾的架构审查。

连接路径为 `/api/ws/saves/{save_id}`。服务器在 Upgrade 前要求恰好一个 Origin 且完整匹配应用白名单。未配置白名单、缺失 Origin、不匹配或重复 Origin 均拒绝。本接口禁止 URL 查询参数，HTTP Bearer 头也不能代替首帧。开发启动器仍绑定回环地址，使用同一个存储与 Origin 配置。

| 方向 | 消息 | 含义 |
| --- | --- | --- |
| 客户端 → 服务端 | `{"type":"auth","token":"SESSION_TOKEN"}` | 首帧必须为此结构。认证和初次授权读取的默认期限为 10 秒。 |
| 服务端 → 客户端 | `{"type":"snapshot","save":{...}}` | 认证并获准读取后发送一次，`save` 和相同身份的 HTTP GET 返回相同。 |
| 服务端 → 客户端 | `{"type":"ping","id":1}` | 每连接从 1 递增。发送前重查会话。 |
| 客户端 → 服务端 | `{"type":"pong","id":1}` | 回复当前 ping 的整数 ID。 |

协议仅接收 UTF-8 JSON 文本，客户端消息最多 4 KiB。拒绝重复 JSON 字段、额外字段、二进制和不符合当前阶段的消息。`account_id`、`role` 和 `pair_id` 不属于认证帧。

| 情况 | 结果 |
| --- | --- |
| Origin 或查询字符串不合规 | Upgrade 前拒绝，TCP 客户端收到 HTTP 403 |
| 首帧非法、重复认证、超前或错误 pong | `4400` |
| 认证超时、会话无效、过期或撤销 | `4401` |
| 缺档或非房间成员 | `4404`，统一关闭且无快照 |
| 未及时回复 ping | `4408` |
| 客户端消息超过 4 KiB | `1009` |
| 认证或存档依赖异常 | `1011`，关闭理由为空 |

服务端不把异常详情、帧原文、token 或恢复密钥写入响应和日志。开发启动器关闭访问日志，关闭传输层压缩及附加 ping，以应用层心跳为准。

## 身份、成员与初始快照

`IdentityService.authenticate` 用会话摘要查询有效会话，检查创建和过期时间，并遵守原有撤销状态。身份验证成功后，才以服务器取得的 `account.id` 调用 `SaveService.read_save`。同步服务在工作线程执行，ASGI 接收循环可在等待期间推进其他连接。

`SaveService.read_save` 按存档 ID 读取已提交记录，再查对应房间成员关系，确定 A 或 B。按存档绑定的剧本 ID 和版本重建个人投影。外人和不存在的档在加载剧本或创建投影前统一拒绝。序列化使用既有 `SaveSnapshot` 模型，不发送完整 GameState、回执、恢复密钥或内部房间成员记录。下一次连接重复完整流程，读取最新已提交版本，不从旧连接复用快照。

集成测试在 SQLite 和真实 MongoDB 分别建立房间，并以 A/B 实际读取同档。两端的 WS 快照分别与对应 HTTP GET 完全相等，线索、观察和装置按角色隔离。两种仓储均验证非成员与缺档得到相同关闭帧，以及 HTTP 提交推进后重连返回新版本。

## 心跳与生命周期

`WebSocketTiming` 集中定义认证 10 秒、心跳间隔 10 秒、pong 超时 5 秒，应用可显式传入配置。发送初始快照或收到正确 pong 后，连接等待下一轮。每轮 ping 前重新调用 `IdentityService.authenticate`。有效会话必须在 5 秒内回复相同 ID。过期、撤销和任何未响应连接按上表关闭。

一个接收循环持有连接和计时器。断开时直接退出该循环，超时上下文退出时清除计时器。T12.1 没有全局订阅表或独立常驻心跳任务。测试分别在等待 auth、下一轮心跳和 pong 时主动关闭客户端，确认 ASGI 处理已退出。超时测试使用缩短的可控期限与可推进的身份时钟，无长时间 sleep。

## 验证与历史失败对比

测试环境为 Linux、CPython 3.12.14、uv 0.13.6、pytest 9.0.2 和 Ruff 0.15.4。真实 MongoDB 8.0.38 使用缓存的 `mongo:8.0` 镜像，绑定回环随机端口。测试按现有夹具使用独立随机库。第一次尝试中 MongoDB 默认文件描述符上限导致进程中止，该次不计为基线。提高临时容器的 `nofile` 至 8192 后，从独立的合并基线工作树和开发分支分别执行全量回归。开发启动器新增锁定的 dev 依赖 `websockets==16.0`，原有包版本保持一致。

| 执行 | 收集 | 通过 | 失败 | 错误 / 跳过 |
| --- | ---: | ---: | ---: | ---: |
| 修改前两个 WebSocket 契约 | 2 | 0 | 2 | 0 / 0 |
| 修改后两个 WebSocket 契约 | 2 | 2 | 0 | 0 / 0 |
| 新增 WebSocket 专项（SQLite、真实 MongoDB、真实回环 TCP） | 41 | 41 | 0 | 0 / 0 |
| 修改前全量 `04cb0d3` | 1202 | 1198 | 4 | 0 / 0 |
| 修改后全量 | 1243 | 1241 | 2 | 0 / 0 |

两项 WebSocket 契约在基线因路由尚未注册而发生 `WebSocketDisconnect`。`test_websocket_uses_auth_frame_and_personal_projection_on_reconnect` 和 `test_outsider_websocket_never_receives_a_snapshot` 的原断言均保留。NPC 测试仍以 HTTP 422 `UNKNOWN_ACTION` 为范围外已知失败。除此之外，本轮基线还复现此前报告过的深层 JSON 失败，`test_json_parser_recursion_failure_is_reported_without_a_raw_traceback` 得到 `CONTENT_INVALID_SCHEMA`，而原断言期待 `CONTENT_INVALID_JSON`。两者均未修改。 两次全量 JUnit 逐项比较，原用例无移除，新增 41 项且新增失败 0。两项旧 WebSocket 失败消失，剩余两项的用例和失败信息均与基线一致。两轮各有一条既有 Starlette/AnyIO 弃用告警。

从项目根目录运行。设置 `MONGO_URI` 指向已有的真实测试实例。若缓存镜像为 `mongo:8.0`，同时设置 `TWOWORLDS_TEST_MONGO_IMAGE=mongo:8.0` 供既有仓储故障测试使用。

```bash
uv run --project backend --locked python -m pytest backend/tests/contracts/test_platform.py -k websocket -q
uv run --project backend --locked python -m pytest backend/tests/api/test_websocket.py -q
uv run --project backend --locked python -m pytest backend/tests -q
uv run --project backend --locked ruff check backend/src backend/tests
uv run --project backend --locked ruff format --check backend/src backend/tests
(cd backend && uv lock --check --offline)
git diff --check
```

云环境使用 `UV_CACHE_DIR=/workspace/.cache/uv` 避免默认用户缓存目录只读。真实 TCP 专项启动 `python -m twoworlds.dev`，验证错误 Origin 返回 HTTP 403，正确 Origin Upgrade，认证后读取不存在的档返回 4404。快照相等和角色隔离通过真实 ASGI 应用与两种仓储验证。

## 阅读顺序与下一步

1. [WebSocket 路由](../../backend/src/twoworlds/api/routers/websocket.py) 查看握手限制与关闭映射。
2. [协议](../../backend/src/twoworlds/realtime/protocol.py) 和 [订阅生命周期](../../backend/src/twoworlds/realtime/subscriptions.py) 查看认证期限、初始快照和 ping/pong。
3. [身份服务](../../backend/src/twoworlds/application/identity.py) 和 [存档服务](../../backend/src/twoworlds/application/saves.py) 查看会话验证、角色推导和按版本读取。
4. [集成测试](../../backend/tests/api/test_websocket.py) 查看 A/B 快照、HTTP 对照、心跳、超时及关闭验证。

以上验证覆盖旧协议中的初始投影与心跳等服务端行为。现行 Cookie 鉴权的验收须在迁移后重新执行。实时广播、前端自动重连、多端版本防回退、pending 恢复、离线缓存、NPC 和生产反代 WSS 验收均留待后续。

## PR #31 架构审查

2026-11-18 核对时，[PR #31](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/31) 为 OPEN、未合并，审查基准 `71593d9b9ee7944f79bb9addcbb4216548f40cef`。目标分支为 `codex/bootstrap`，开发分支为 `codex/t12-1-websocket-auth`。已合并的 [PR #30](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/30) 采用邮箱与密码、Argon2id 和 HttpOnly Cookie 会话，WebSocket 通过握手 Cookie 认证。旧版首帧 token 与该设计冲突，**PR #31 暂停合并**。

保留精确 Origin、`SaveService.read_save`、A/B 授权投影、外人和缺档统一 `4404`、重连取最新快照、心跳与断开清理，以及 SQLite 和 MongoDB 集成测试方法。上面的历史测试结果适用于旧版协议。

先从最新远端 `codex/bootstrap` 单独完成 T06.3.2。待其通过人工审查并合并，在现有 PR #31 执行以下迁移：

1. 将 `codex/t12-1-websocket-auth` 更新到 T06.3.2 合并后的最新基线。
2. 将 `websocket.py` 的鉴权入口改为握手 Cookie，复用服务端会话验证。移除 `protocol.py` 的 `auth_token` 首帧解析，以及 `subscriptions.py` 等待客户端发送 token 的流程。拒绝首帧 token、URL token 和客户端自报的 `account_id`、`role`。
3. 使用 Cookie 验证得到的身份检查房间成员，从服务端成员关系确定角色，并返回对应的最新个人快照。外人和缺档继续统一使用 `4404`，不发送快照。
4. 心跳期间复核该 Cookie 对应的会话。验证登出、密码重置和会话过期后，已有连接会失效。
5. 重写依赖旧首帧协议的安全与契约测试，保留其拒绝、隔离和资源清理覆盖。分别用真实 SQLite 与 MongoDB 验证 Cookie 握手、会话失效、A/B 投影及重连。
6. 更新当前协议文档，核查没有首帧 token 或 Bearer 兼容路径，再提交原 PR 人工审查。T12.2 保持暂停。

本轮记录审查结论，未改业务代码与测试，未实施上述迁移。
