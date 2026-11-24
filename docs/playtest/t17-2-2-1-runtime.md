# T17.2.2.1 · 独立 Playtest 运行模式

本环节落实 [准备度审计](t17-2-readiness-audit.md) 中的后端启动与身份边界。基线为 PR #55 合并后的 `f8db0b1`。Playtest 供受控实例使用，账号预创建、接入部署和最终开测验收在后续环节独立完成。

## 启动契约

后端入口为 `python -m twoworlds.playtest`。程序默认监听 `127.0.0.1:8000`，适合本机或可信的 TLS 网关之后。进程启动时才构建应用。实际 TLS 终止、网关接入权限和安全网络边界由后续独立部署提供。

| 配置项 | 用法 |
| --- | --- |
| `TWOWORLDS_MODE` | 显式设为 `playtest`。Demo 与 Production 继续使用各自的启动入口 |
| `TWOWORLDS_PLAYTEST_MONGO_URI` | 独立单节点 `mongodb://` 地址和数据库内的 SCRAM 用户。URI 的默认库或 `authSource` 指向专用库，若同时提供，两者都必须与专用库一致。支持 TLS 及自定义 CA |
| `TWOWORLDS_PLAYTEST_MONGO_DATABASE` | 显式选择 `twoworlds_playtest_*` 命名空间，后缀使用小写字母、数字或下划线 |
| `TWOWORLDS_PLAYTEST_VERIFICATION_SECRET` | 每个环境独立生成 32 个随机字节并转为小写十六进制，例如由秘密管理流程运行 `openssl rand -hex 32` 后安全注入。缺省、已知占位、重复和明显顺序值失败。格式检查无法验证随机数生成过程 |
| `TWOWORLDS_ALLOWED_ORIGINS` | 明确列出实际 HTTPS Origin，例如 `https://playtest.example.invalid`。多值以逗号分隔。通配符、路径与 HTTP 被拒绝 |
| `TWOWORLDS_PLAYTEST_PUBLICATION_ROOT` | 独立封存发布库目录。程序化装配也可显式传入 `PublicationStore`。目录在打开 MongoDB 前经过版本和完整性校验 |
| `TWOWORLDS_AI_MODE` 与 `TWOWORLDS_EMAIL_MODE` | 缺省分别为 `demo` 与 `disabled`。提供其他值时拒绝启动。Provider 和 SMTP 配置值不读取 |
| `TWOWORLDS_STORAGE_BACKEND` | 缺省为 `mongo`。提供非 MongoDB 值时拒绝启动 |
| `TWOWORLDS_HOST`、`TWOWORLDS_PORT` 与 `TWOWORLDS_TRUSTED_PROXY_IP` | 控制内部监听与明确的单一可信代理。代理为空时禁用代理头信任 |

独立变量不继承正式 `MONGO_URI`、`MONGO_DATABASE` 或正式验证密钥。启动设置只在后端注入，配置表展示的是变量名，不含实际凭据。URI 的用户名、密码按照 MongoDB 约定编码。运行时数据库账号必须建在专用库中，且只持有该库的 `readWrite`。使用独立 MongoDB 实例及私有网络，测试主机不可到达正式数据网。启动检查能够限制库名、权限与匿名访问，物理实例和网络隔离由部署验收确认。

## 安全行为

1. 连接 MongoDB 后先读取认证会话，检查账号作用域。用同一单节点的第二条无凭据连接确认匿名 `listCollections` 被拒绝，检查双方确实抵达同一进程。之后才创建现有仓储索引。连接失败、认证被关闭、账号权限跨库或拓扑不符合均拒绝启动。
2. 应用工厂保留登录、`/api/me` 与登出。注册、验证码申请和密码重置路由关闭，正确 Origin 的请求返回 404。Playtest 不构建验证码服务。拒绝投递适配器提供第二层防护，任何直接投递请求都会以固定错误失败，既不发邮件也不会记录正文。
3. 继续使用已有会话 Cookie、CSRF、请求体上限、登录限流和 WebSocket Origin 验证。Cookie 固定为 Secure、HttpOnly 和 SameSite=Lax。HTTP 请求日志关闭，WebSocket 与启动错误使用固定的分类信息。
4. AI 网关不会创建。后端 NPC 命令只返回现有 Demo 文本。运行时校验显式传入的封存发布库，使用现有读取时完整性检查。独立库可以是已初始化的空库，此时目录为空，书架开测前需要获批内容。没有默认或草稿回退。

## 验证入口

在 `backend/` 运行。Playtest 专项使用已在本机或 CI 镜像缓存中的 `mongo:7.0.48`，创建独立的认证及非认证容器并清理。完整回归同时需要 `MONGO_URI` 指向一次性的隔离回归容器。

~~~bash
uv run --locked pytest tests/api/test_playtest.py -q --tb=short
uv run --locked pytest tests/api/test_server.py tests/api/test_dev_launcher.py \
  tests/api/test_identity.py tests/api/test_websocket.py tests/content/test_publication.py -q --tb=short
TWOWORLDS_TEST_BACKEND=sqlite TWOWORLDS_TEST_MONGO_IMAGE=mongo:7.0.48 \
  uv run --locked pytest -ra --tb=short
uv run --locked ruff check .
uv run --locked ruff format --check .
uv lock --check --offline
git diff --check
~~~

本地 Playtest 专项 28 项与 MongoDB 备份恢复专项 14 项通过，Demo、Production、身份、WebSocket 和发布库回归 232 项通过。Ruff lint、格式与离线锁检查通过。专项验证既有账号登录和会话撤销、认证拒绝条件、HTTP 与 WebSocket 请求、角色投影、固定 Demo 回复、内容完整性、错误脱敏、CLI 与仓储关闭。读取顺序为 [Playtest 工厂](../../backend/src/twoworlds/playtest.py)、[应用装配](../../backend/src/twoworlds/api/app.py)、[Mongo 仓储](../../backend/src/twoworlds/storage/mongo.py)及[测试](../../backend/tests/api/test_playtest.py)。

## T17.2.2.2 交接

预创建工具需使用同一试玩库限定和账号权限，复用现有身份服务和预先核准的测试别名。应处理重复配置、撤销初始化会话、受控交付登录凭据与脱敏操作记录。玩家继续通过现有登录路由取得会话。封闭网关、内容授权、环境清理和真人开测仍按[准备度审计](t17-2-readiness-audit.md#真人开测前必须完成)另行验证。
