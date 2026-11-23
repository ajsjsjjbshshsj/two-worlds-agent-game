# T15.2 · HTTPS、WSS 与生产环境安全集成

本轮基线为 `codex/bootstrap@c17061317c4a212f28b4987ae463d34c5c0097d5`，已包含 PR #50 的 SMTP 启动约束。开发分支为 `codex/t15-2-secure-deployment`。

## 网络与请求路径

```text
浏览器 ── HTTPS / WSS ── Nginx 网关 (443)
                         ├── /api、/api/* ── FastAPI (8000)
                         └── 其余 UI 路径 ── Vue 静态服务 (8080)
                                           FastAPI ── 数据网 ── MongoDB (27017)
```

Compose 只发布网关 80 和 443，默认绑定 `127.0.0.1`。80 转到已配置主机的 HTTPS，未知 Host 被拒绝。443 使用部署者挂载的 TLS 1.2/1.3 证书，启用 HSTS。后端、静态服务和 MongoDB 均无宿主机映射。数据库位于单独内部网络。静态服务保留 Service Worker 文件的 `no-store` 和哈希资源缓存。网关把 `/api` 和 `/api/*` 直接传给 FastAPI，未知 API 返回后端错误。生产前端以空 API base 构建，页面、API、媒体和 WebSocket 共用浏览器域名。Demo Compose 仍使用独立的 SQLite 和 HTTP 测试路径。

## 会话与代理边界

- 浏览器从 HTTPS 页面连接 `wss://<host>/api/ws/saves/{save_id}`。Nginx 转发 HTTP/1.1 Upgrade，保留 Origin 与 Cookie。FastAPI 按原协议验证单一精确 Origin、会话、成员和角色。每个连接只收到自己的存档投影。
- Compose 从 `TWOWORLDS_PUBLIC_HOST` 派生唯一精确 HTTPS Origin，并固定 `TWOWORLDS_COOKIE_SECURE=1`。生产启动器要求 HTTPS Origin 和 Secure Cookie，Cookie 仍带 HttpOnly 和 SameSite=Lax。独立启动生产时也需显式提供这两个设置。
- Nginx 重写 `X-Forwarded-For` 和 `X-Forwarded-Proto`，清除原始 `Forwarded` 与其他转发地址头。Uvicorn 只接受部署指定的单一网关 IP。Compose 网段把该静态 IP 和自动分配范围分开。改网段时同步设置 `TWOWORLDS_EDGE_SUBNET`、`TWOWORLDS_EDGE_DYNAMIC_RANGE`、`TWOWORLDS_PROXY_IP`。
- 网关 HTTP 请求体上限为 16 KiB，后端继续执行 HTTP 与 WSS 自身的上限和心跳策略。WSS 的 4096 字节帧上限及心跳超时由后端执行。网关读写超时给应用心跳留出时间。
- HTTP 与代理访问日志不记录原始请求。Uvicorn 的 WebSocket 握手只记录状态码，异常堆栈转为固定类别。启动器只输出已分类配置错误。AI 观测继续沿用 T14.4.2 的脱敏字段。

## 健康检查与 AI 设置

`/health/live` 报告应用进程状态。 `/health/ready` 执行有时限的 MongoDB ping，SQLite 使用只读数据库检查。探针返回固定 JSON，Mongo 不可用时 ready 为 503，live 仍为 200。网关对外拒绝探针路径，Docker 直接从后端容器内检查 readiness。Docker 的 `unhealthy` 表示服务未就绪，进程可以继续运行和恢复。

后端默认 Demo。经人工授权后，部署者从服务端密钥存储向后端容器**运行环境**注入 `TWOWORLDS_AI_API_KEY`，同时按 [.env.example](../../.env.example) 配置模式、服务地址、模型、超时、输入输出、每日上限和价格版本。后端启动时校验完整配置，玩家外发授权与预算仍由 T14.3 处理。Vue 构建参数只有公共 API 地址，Compose 正式路径固定为空。Docker 构建上下文排除本机 dotenv 和常见私钥文件。检查已注入密钥的 Compose 配置时使用 `config --quiet`，避免打印展开后的运行时值。测试使用 MockTransport 和虚拟值，外部模型与 SMTP 投递费用为零。

## 本地复现

在 Linux 中安装 Docker Compose、OpenSSL 和 uv，确认 127.0.0.1 的 80、443 可用于本地测试。在仓库根目录执行两套配置检查。

```bash
TWOWORLDS_PUBLIC_HOST=localhost docker compose --env-file /dev/null config --quiet
docker compose --env-file /dev/null -f compose.demo.yml config --quiet
cd backend
uv sync --locked
uv run --locked python -m tests.deployment_smoke
```

测试为临时 Compose 项目生成 `localhost` 自签证书。HTTP 客户端和 WebSocket 客户端用该证书验证链路。测试挂载合成剧本资源、在独立 MongoDB 测试库中创建合成账号，启动后验证 HTTPS、WSS、日志和数据库故障恢复，结束时回收专用容器与卷。程序可通过 `--prebuilt BACKEND_IMAGE FRONTEND_IMAGE` 复用已构建镜像，前端镜像需要使用空 `VITE_API_BASE_URL`。

手动启动时从示例配置提供 `TWOWORLDS_PUBLIC_HOST=localhost`、只读证书目录 `TWOWORLDS_TLS_DIR`、随机验证密钥及本地虚拟 SMTP 主机和发件地址。证书目录须有可读取的 `fullchain.pem` 和 `privkey.pem`。如果使用符号链接，链接目标必须在容器可访问的证书挂载内。本地浏览器可在隔离的测试配置中信任对应证书。证书和密钥均在仓库及镜像外保存。启动后可用 `curl --cacert <证书> https://localhost/api/scripts` 检查同源 API。正式域名需拥有合法证书和正确 DNS，当前没有公网部署。

## 验证记录

- Ruff lint、Ruff format、离线 uv lock、`git diff --check` 通过。前端 TypeScript、生产构建和 Prettier 检查通过，Vitest **468 项通过**。
- 后端 `uv run --locked --offline pytest -ra --tb=short` 最终为 **1735 通过、0 失败、0 跳过**，含一条 Starlette/AnyIO 弃用警告。默认仓储为 SQLite，同时覆盖真实 MongoDB 7.0.48 参数化用例。
- 启动专项 **55 项通过**，包括 HTTPS/Secure Cookie 门控、代理白名单、Provider 启动校验和 SQLite 就绪探针。已有 MockTransport 超时测试验证固定错误分类、Fallback 与日志脱敏。
- 容器镜像在本地环境使用 BuildKit 临时挂载该环境的代理 CA 访问依赖仓库。证书未写入镜像层。本地 smoke 使用同一生产 Compose 配置与上述镜像，经 SSH 或公网的环境未使用。
- 两套 Compose 配置和 `nginx -t` 通过。真实容器链路验证 HTTP 308 跳转、Host 拒绝、未知 API 404、超大 HTTP 请求 413、WSS 101 与非法或未认证握手 403。A/B 投影与各自 HTTP 一致，重连拿到最新版本。超大 WS 帧关闭码 1009，缺少 pong 关闭码 4408。
- Chromium 仅放行本次临时证书的 SPKI 指纹，验证 HTTPS 登录、Secure/HttpOnly Cookie、Service Worker 更新检查和代理重启后的自动 WSS 恢复。TCP 工具独立以证书验证 TLS。
- Mongo 停止后 ready 503、live 200，后台容器仍运行但标记 unhealthy，恢复后重新 healthy。停止后端时，网关返回 504。按照虚拟凭据、会话、邀请、私聊和被拒绝查询标记检查日志，扫描前端容器的静态构建产物。SMTP 配置失败拒绝启动，虚拟密码没有输出。
- GitHub Actions 新增 Deployment / HTTPS and WSS，使用现有测试镜像、临时证书和虚拟凭据。最终运行结果以本任务 PR 的 Checks 为准。

## 待独立验收

公网域名、证书签发和续期、真实 SMTP、实际 Provider 与账单、正式资源发布留待各自验收。T15.3 建议补齐正式部署手册、证书与密钥轮换、MongoDB 备份和恢复演练。当前检查点为 T15.2 PR 人工审查。

## 阅读顺序

1. [Compose 拓扑](../../compose.yml) → [Nginx 入口](../../deploy/nginx/site.conf.template)
2. [启动和代理信任](../../backend/src/twoworlds/server.py) → [探针](../../backend/src/twoworlds/api/app.py) → [WebSocket 鉴权](../../backend/src/twoworlds/api/routers/websocket.py)
3. [前端 WSS 地址解析](../../frontend/src/services/websocket.ts) → [运行时环境变量](../../.env.example) → [容器验收](../../backend/tests/deployment_smoke.py)
