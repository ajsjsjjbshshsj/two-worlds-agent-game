# TwoWorlds · T15.1 Docker 容器化与运行环境配置报告

日期：2026-11-22  
任务分支：`codex/t15-1-containerization`  
目标基线：`codex/bootstrap`（包含已合并的 PR #48，提交 `c8807167e6953d18affe52697534811772bcdfed`）  
对应 PR：待创建

---

## 一、本环节任务目标与完成情况

本环节是 **T15 容器、CI、配置与部署手册** 的第一阶段（**T15.1**）。目标是建立 TwoWorlds 稳定、可复现、安全且互斥的 Docker 容器运行基础。

本次任务严格支持两条互斥且无法隐式切换的运行路径：
1. **正式生产路径（Production Path）**：FastAPI 后端 + 真实 MongoDB（`mongo:7.0.48`）+ Vue 生产构建（轻量 Nginx 静态服务），通过 `compose.yml` 编排，支持环境变量注入、数据卷持久化，若 MongoDB 缺失或不可用则后端坚决报错退出（退出码 1），绝不自动降级到 SQLite 或内存存储。
2. **本地演示路径（Demo Path）**：FastAPI 后端 + SQLite 存储 + Vue 前端，通过 `compose.demo.yml` 独立编排，显式设置演示模式（`TWOWORLDS_MODE=demo`），强制离线 Demo NPC（`TWOWORLDS_AI_MODE=demo`，拒绝 `provider` 模式），零外部模型调用与费用，SQLite 挂载至持久化命名卷。

### 明确不做的范围（遵循系统边界）
- 不配置公网 HTTPS / 正式域名。
- 不配置 Nginx / Caddy 正式反向代理和证书自动申请。
- 不做 WSS Upgrade 部署验收。
- 不做生产级 Kubernetes liveness/readiness 探针。
- 不做生产 MongoDB 自动化备份与恢复脚本（留待 T15.3）。
- 不触动游戏规则、CAS、身份鉴权、AI 工作流核心逻辑。

---

## 二、双路径设计与实现机制

### 1. 服务启动器与严格环境校验 (`backend/src/twoworlds/server.py`)
为避免历史演示启动器（`twoworlds.dev`）的宽松默认值与隐式回退，新增独立的生产与容器运行应用启动器 `twoworlds.server`，提供 `create_server_app(environ)` 与 `main()` 入口：
- **强制显式运行模式**：环境变量必须显式设置 `TWOWORLDS_MODE` 为 `'production'`（或 `'formal'`）或 `'demo'`，缺失或非法直接抛出 `ValueError` 并退出。
- **生产模式保护**：
  - 强制 `TWOWORLDS_STORAGE_BACKEND=mongo`。
  - 必须提供有效的 `MONGO_URI` 与 `MONGO_DATABASE`。
  - 强制校验 `TWOWORLDS_VERIFICATION_SECRET`，且长度必须至少为 16 个字符，拒绝弱密钥或默认空串。
  - 启动阶段执行 `client.admin.command("ping")` 进行真实连通性测试。若 Mongo 无法连通（如连接被拒或超时），直接抛出 `ConnectionError`，退出码 1，**绝对不自动降级到 SQLite 或内存**。
  - 严格来源校验：`TWOWORLDS_ALLOWED_ORIGINS` 必须显式声明，且必须为完整 HTTP/HTTPS 精确来源（如 `http://localhost:8080`），拒绝包含通配符 `*` 或无效 URL。
- **演示模式保护**：
  - 强制 `TWOWORLDS_STORAGE_BACKEND=sqlite`。
  - 必须提供 `TWOWORLDS_SQLITE_PATH`。
  - 强制 `TWOWORLDS_AI_MODE=demo`，若用户误配置为 `provider` 则直接抛错，从源头上切断外部模型调用与费用风险。
  - 拒绝在演示模式下混用 MongoDB，两条路径配置严格隔离。

### 2. 依赖项分类调整 (`backend/pyproject.toml` & `backend/uv.lock`)
在容器多阶段构建中，Stage 1 使用 `--no-dev` 排除测试套件。为使容器内 FastAPI 能够以标准的 ASGI 服务器运行：
- 将 `uvicorn==0.54.0` 与 `websockets==16.0` 从 `[dependency-groups] dev` 移入 `dependencies`。
- 执行 `uv lock` 与 `uv sync --locked` 重新锁定，保持 57 个包版本锁定不变。

---

## 三、Docker 镜像规格与非 root 安全设计

### 1. 后端镜像 (`backend/Dockerfile`)
采用标准多阶段构建（Multi-Stage Build）：
- **Stage 1 (Builder)**：
  - 基础镜像：`python:3.12-slim-bookworm`。
  - 安装锁定版本 `uv==0.13.6`，配置 `UV_COMPILE_BYTECODE=1`、`UV_LINK_MODE=copy`。
  - 利用 Docker 缓存层：先复制 `pyproject.toml` 与 `uv.lock` 执行 `uv sync --locked --no-dev --no-install-project`。
  - 复制项目源码及构建文件，使用 `uv sync --locked --no-dev --no-editable` 将 `twoworlds` 构建为不可变 wheel 安装至 `.venv`。
- **Stage 2 (Runner)**：
  - 基础镜像：`python:3.12-slim-bookworm`。
  - **非 root 用户**：创建专属非特权用户 `twoworlds:twoworlds`（固定 UID:GID 为 10001:10001）。
  - 从构建阶段复制只读 `.venv` 并赋予属主权限。
  - 创建专用持久化数据目录 `/data`，属主为 `twoworlds:twoworlds`。
  - 切换至非特权用户：`USER twoworlds:twoworlds`。
  - 暴露端口 `8000`，默认命令为 `["python", "-m", "twoworlds.server"]`。

### 2. 前端镜像 (`frontend/Dockerfile` & `frontend/nginx.conf`)
采用轻量生产多阶段构建：
- **Stage 1 (Builder)**：
  - 基础镜像：`node:22-alpine`。
  - 接收构建参数 `ARG VITE_API_BASE_URL=http://localhost:8000`。
  - 复制 `package.json` 与 `package-lock.json` 执行 `npm ci`。
  - 复制源码执行 `npm run build`，产出高度优化的 SPA/PWA 静态资源包。
- **Stage 2 (Runner)**：
  - 基础镜像：`nginx:1.27-alpine`。
  - 自定义 `nginx.conf`：
    - 监听 `8080` 端口（避免特权端口 80 需要 root 权限）。
    - 配置前端路由兜底：`try_files $uri $uri/ /index.html;`，确保 Vue 客户端路由刷新正常。
    - 注入安全响应头：`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: strict-origin-when-cross-origin`。
    - 静态资产缓存（`/assets/` 缓存 1 年不可变），PWA Service Worker（`/sw.js`）及 `manifest.webmanifest` 严格 `no-cache`。
  - **非 root 用户**：调整 `/var/run/nginx.pid`、`/var/cache/nginx`、`/var/log/nginx` 与静态目录权限，以 Alpine 预置非特权用户 `USER nginx`（UID 101）运行。

---

## 四、容器网络与持久化卷设计

| 路径 | Compose 配置文件 | 编排服务 | 内部网络 | 持久化数据卷 | 宿主机端口映射 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **正式生产路径** | `compose.yml` | `mongo` (`mongo:7.0.48`)<br>`backend`<br>`frontend` | `twoworlds-net` (bridge) | `mongo_data` 挂载至 `/data/db` | 后端 `8000:8000`<br>前端 `8080:8080`<br>(Mongo 端口不对外暴露) |
| **本地演示路径** | `compose.demo.yml` | `backend`<br>`frontend` (无 Mongo) | `twoworlds-demo-net` (bridge) | `sqlite_data` 挂载至 `/data` | 后端 `8000:8000`<br>前端 `8080:8080` |

### 编排依赖与健康检查
- 在 `compose.yml` 中，`mongo` 服务配置了 `healthcheck`：
  ```yaml
  test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
  interval: 5s
  timeout: 5s
  retries: 5
  start_period: 5s
  ```
- `backend` 服务声明 `depends_on: mongo: condition: service_healthy`，确保 MongoDB 启动完毕并能够响应 ping 之后，后端容器才启动并建立连接。

---

## 五、环境变量矩阵与安全配置

完整的环境变量说明已更新至根目录 `.env.example`，敏感密钥及配置通过容器编排环境注入，严禁硬编码或直接提交 `.env` 文件。

| 环境变量名 | 生产模式要求 | 演示模式要求 | 说明 |
| :--- | :--- | :--- | :--- |
| `TWOWORLDS_MODE` | 必须为 `production` | 必须为 `demo` | 核心模式门控，缺省或非法直接拒绝启动 |
| `TWOWORLDS_STORAGE_BACKEND` | 必须为 `mongo` | 必须为 `sqlite` | 存储引擎，生产严禁为 sqlite |
| `MONGO_URI` | 必填（如 `mongodb://mongo:27017`） | 不使用 | MongoDB 连接串 |
| `MONGO_DATABASE` | 必填（默认 `twoworlds`） | 不使用 | MongoDB 数据库名称 |
| `TWOWORLDS_SQLITE_PATH` | 不使用 | 必填（如 `/data/twoworlds_demo.db`） | SQLite 文件路径 |
| `TWOWORLDS_VERIFICATION_SECRET` | 必填，至少 16 字符安全随机串 | 选填（容器提供预设演示串） | 会话签名密钥（生产建议 `openssl rand -hex 32`） |
| `TWOWORLDS_EMAIL_MODE` | `console` 或 `smtp` | `console` | 邮件服务模式，`console` 将验证码打到容器日志 |
| `TWOWORLDS_ALLOWED_ORIGINS` | 精确 HTTP 来源 | 精确 HTTP 来源 | CORS 白名单（默认 `http://localhost:8080,http://127.0.0.1:8080`） |
| `TWOWORLDS_AI_MODE` | `demo` 或 `provider` | 必须为 `demo` | 演示模式强制 demo，禁止外部模型与计费 |
| `VITE_API_BASE_URL` | 前端构建参数 | 前端构建参数 | 前端指向后端的地址（默认 `http://localhost:8000`） |

---

## 六、实测验证证据

所有验证均在宿主机实际 Docker 环境执行并记录真实输出：

### 1. 镜像构建与非 root 身份检查
- 后端镜像：`docker build -t twoworlds-backend:test ./backend` 构建成功。
  - 检查用户：`docker run --rm twoworlds-backend:test whoami` 输出 `twoworlds`。
  - 检查 UID：`docker run --rm twoworlds-backend:test id` 输出 `uid=10001(twoworlds) gid=10001(twoworlds)`。
- 前端镜像：`docker build -t twoworlds-frontend:test ./frontend` 构建成功。
  - 检查用户：`docker run --rm twoworlds-frontend:test whoami` 输出 `nginx`。
  - 检查 UID：`docker run --rm twoworlds-frontend:test id` 输出 `uid=101(nginx) gid=101(nginx)`。

### 2. 模式校验与异常退出测试
- **缺配置启动失败**：
  `docker run --rm twoworlds-backend:test`  
  退出码：`1`  
  输出：`Server startup failed: Explicit TWOWORLDS_MODE required: 'production' or 'demo'`。
- **生产模式缺少 MongoDB 连通报错退出（不产生 SQLite，不降级）**：
  `docker run --rm -e TWOWORLDS_MODE=production -e TWOWORLDS_STORAGE_BACKEND=mongo -e MONGO_URI=mongodb://127.0.0.1:29999 -e MONGO_DATABASE=tw -e TWOWORLDS_VERIFICATION_SECRET=01234567890123456789 twoworlds-backend:test`  
  退出码：`1`  
  输出：`Server startup failed: Production MongoDB connection failed; server will not start without database`。
- **生产模式缺少有效密钥报错退出**：
  `docker compose up -d`（`TWOWORLDS_VERIFICATION_SECRET` 为空）  
  容器状态：`Restarting (1)`  
  日志输出：`Server startup failed: Production mode requires explicit durable TWOWORLDS_VERIFICATION_SECRET (min 16 chars)`。
- **演示模式误配外部 AI 报错退出**：
  `TWOWORLDS_MODE=demo` 配合 `TWOWORLDS_AI_MODE=provider` 触发：  
  `ValueError: Demo mode strictly forbids external AI providers (must be demo)`。

### 3. 本地演示路径完整跑通与数据持久化验证
1. 执行 `docker compose -f compose.demo.yml up -d --build`，两个服务均成功启动为 `Up`。
2. HTTP 探测前端 `http://localhost:8080/`：返回 `200 OK`，携带安全头及 `index.html`。
3. HTTP 探测后端 CORS：携带 `Origin: http://localhost:8080` 请求 `http://localhost:8000/api/auth/me`，正常返回 `404` 且携带 `access-control-allow-origin: http://localhost:8080` 与 `access-control-allow-credentials: true`。
4. 注册流程：
   - 发送验证码：POST `/api/verification-codes` 请求 `tester@example.com`（`purpose="register"`），返回 `accepted`；
   - 查看容器日志：`docker compose -f compose.demo.yml logs backend` 打印 `[dev-email] to=tester@example.com purpose=register code=494640`；
   - 注册账号：POST `/api/accounts` 携带该验证码与密码，返回新建账号 ID。
5. 持久化与重启验证：
   - 执行 `docker compose -f compose.demo.yml down`（保留 `sqlite_data` 数据卷）；
   - 执行 `docker compose -f compose.demo.yml up -d` 重新启动容器；
   - 登录：POST `/api/sessions` 提交上述注册凭据，成功登录并返回 Session，证明 SQLite 在命名卷中成功持久化。
6. 清理：执行 `docker compose -f compose.demo.yml down -v` 安全销毁。

### 4. 正式生产路径完整跑通与 MongoDB 数据持久化验证
1. 传入随机密钥并启动：
   `$env:TWOWORLDS_VERIFICATION_SECRET="prod-verification-secret-32-chars-long"; docker compose up -d`
2. 服务就绪：
   - `mongo:7.0.48`：健康检查通过 (`healthy`)；
   - `frontend`：`Up` (8080)；
   - `backend`：`Up` (8000)，后端日志输出 `Application startup complete. Uvicorn running on http://0.0.0.0:8000`。
3. 真实 MongoDB 写入与持久化验证：
   - 请求注册验证码至 `produser@example.com`，日志打印 `code=268829`；
   - 注册 `produser@example.com` 账号成功写入 MongoDB；
   - 重启集群：`docker compose down` 紧随 `docker compose up -d`；
   - 登录凭据校验：POST `/api/sessions` 携带 `produser@example.com` 密码，成功登录并验证 Session，证明真实 MongoDB 数据在 `mongo_data` 命名卷中成功持久化。
4. 清理：执行 `docker compose down -v` 安全销毁。

### 5. 单元测试与代码风格验证
- **后端专项测试 (`backend/tests/api/test_server.py`)**：
  覆盖来源白名单、非法模式拒绝、生产缺少配置退出、生产缺少 Mongo 拒绝降级、演示禁止外部 AI、演示 SQLite 启动与持久化、CLI 参数解析等 22 项测试全部通过（`22 passed, 1 warning in 15.24s`）。
- **后端静态检查**：
  - `uv run ruff check`：`All checks passed!`
  - `uv run ruff format --check`：`143 files already formatted`
  - `uv lock --check --offline`：`Resolved 57 packages in 2ms`
- **前端静态检查与测试**：
  - `npm run typecheck`：通过（退出码 0）
  - `npm run test:unit`：通过（退出码 0）
  - `npm run build`：通过（退出码 0）

---

## 七、代码与配置阅读建议

建议按如下顺序阅读本次新增与修改的配置与代码：

1. **[生产应用启动器](../backend/src/twoworlds/server.py)**：
   - 阅读 `create_server_app(environ)`：了解严格的 `TWOWORLDS_MODE` 门控、MongoDB 连通与不降级保证、以及 Demo 模式与外部 AI 隔离。
   - 阅读 `validate_origins()` 与 `main()`：了解精确 CORS 校验与 CLI 优雅失败。
2. **[后端服务测试](../backend/tests/api/test_server.py)**：
   - 了解 22 项测试如何分别证明两模式隔离、安全退出及真库契约。
3. **[后端 Dockerfile](../backend/Dockerfile)**：
   - 了解基于 `uv` 的多阶段构建与 UID 10001 非 root 用户。
4. **[前端 Dockerfile](../frontend/Dockerfile) 与 [Nginx 配置](../frontend/nginx.conf)**：
   - 了解前端 SPA/PWA 静态资产构建、安全头配置及 UID 101 非 root 用户。
5. **[Docker Compose 配置](../compose.yml) 与 [演示编排](../compose.demo.yml)**：
   - 对比两份配置如何分别映射生产 MongoDB 路径与本地 SQLite 演示路径。
6. **[环境变量示例](../.env.example)**：
   - 了解生产与演示模式环境变量清单及敏感信息说明。

---

## 八、未完成项与后续计划

本轮 **T15.1** 已经完全达到目标，严格停止在学习检查点。

后续阶段计划（不自动开始，等待用户明确指令）：
- **T15.2：反向代理、HTTPS、WSS 与环境变量生产集成**：
  - 配置外部反向代理（Nginx / Caddy）参考配置与 HTTPS 证书配置说明。
  - 重点验证 WebSocket（WSS）Upgrade 在代理下的稳定握手与保活。
  - 生产日志策略与监控告警建议。
- **T15.3：生产部署 Runbook、备份恢复与容灾验收**：
  - 编写完整的部署运维手册（`docs/RUNBOOK.md`、`docs/DEPLOYMENT.md`）。
  - 实现并实际测试 MongoDB 备份与恢复（`mongodump` / `mongorestore`）脚本与演练记录。
