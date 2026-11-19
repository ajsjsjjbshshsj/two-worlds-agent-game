# T06.3.2 · 后端邮箱账号认证系统

日期：2026-11-19。分支 `codex/t06-3-2-email-auth-backend`，基线 `6641150`（PR #30 合并后的 `origin/codex/bootstrap`），工作树 `F:\two-worlds-agent-game\work\pr-t01-1-schema`。授权规格为用户 17 节任务书（本地 `work/t0632-spec.txt`，不入库）。本轮只做后端；前端页面（T06.3.3）、前端清理与产品验收（T06.3.4）、WS 实现均未开始。

## 1. 修改了哪些文件

新增源码（9）：

- `backend/src/twoworlds/security/passwords.py`：Argon2id 哈希器、Password 约束、dummy_verify。
- `backend/src/twoworlds/security/mailer.py`：console/smtp 邮件适配器与 build_email_sender。
- `backend/src/twoworlds/ports/email.py`：EmailCodeSender 端口与 EmailSendError。
- `backend/src/twoworlds/application/verification.py`：验证码申请/消费/作废。
- `backend/src/twoworlds/application/rate_limit.py`：数据库共享原子限频。
- `backend/src/twoworlds/api/cookies.py`：tw_session 下发/清除。
- `backend/src/twoworlds/api/limits.py`：路由级限频键与 peer IP。
- `backend/src/twoworlds/api/routers/verification.py`、`api/routers/password_resets.py`：两个新端点。

修改源码（14）：`domain/persistence.py`（AccountRecord 邮箱模型、VerificationCodeRecord、RateLimitRecord）、`security/credentials.py`（verification_digest）、`ports/repository.py`（9 个新方法）、`storage/sqlite.py`、`storage/mongo.py`、`storage/indexes.py`（新增 4 个索引，只增不删）、`application/identity.py`（register/login/reset_password/authenticate/revoke）、`api/app.py`（IdentitySafety CSRF、CORS 凭证、必填注入）、`api/auth.py`（Cookie 认证）、`api/errors.py`、`api/schemas/identity.py`、`api/routers/accounts.py`、`api/routers/sessions.py`、`dev.py`（显式邮件模式）。

删除：`backend/src/twoworlds/api/rate_limit.py`（旧单进程限频）；`POST /api/sessions/recover` 端点、恢复密钥生成/摘要与 Bearer 认证一并移除，无兼容分支。

测试：新增 `tests/identity_support.py`、`tests/application/test_verification.py`、`tests/application/test_rate_limit.py`；改写 `tests/application/test_identity.py`、`tests/api/test_identity.py`、`tests/api/test_rate_limit.py`、`tests/api/test_request_limits.py`、`tests/api/test_dev_launcher.py`、`tests/contracts/test_identity.py`；适配注册助手与 create_app 注入的既有测试（commands/media/pairs/saves/save_isolation/platform/persistence/projection/仓储契约等）。未删除安全断言，未使用 skip/xfail。

依赖：`pyproject.toml` 新增运行依赖 argon2-cffi==25.1.0，`uv.lock` 共 30 包；其余版本未升级。

文档：docs/03（§5 契约细节修正、§9 WS 目标契约注记、§10.1 响应表、装配入口）、docs/04（T06.3.2 完成、T06.3.4 职责改为前端清理/演示库重置/产品验收）、docs/05（QA-I 证据状态）、backend/README（第 9/10 节标历史、新增第 18 节）、本交接、本报告。

## 2. 新的 Account 数据模型

`domain/persistence.py` 的 AccountRecord：`id`、规范化 `email`（strip+lower，≤254，数据库唯一）、`email_verified_at`、`password_hash`（Argon2id 编码串，StrictStr 20..512）、`display_name`（1–40）、`sessions`（最多 5 个，每个只存 `token_digest`/`created_at`/`expires_at`）、`created_at`/`updated_at`、`version`。秘密字段 `repr=False`，序列化 dump 不含密码/token 明文。

新增 VerificationCodeRecord：确定性 `code_id`（邮箱+purpose 的 SHA-256 派生，保证同邮箱同用途只有一条活码）、`email`、`purpose`、`code_digest`（HMAC-SHA256）、`attempts`、`expires_at`、`consumed_at`、`version`。RateLimitRecord：确定性 `rate_id`（键摘要派生）、`count`、`window_started_at`、`expires_at`、`version`；键本身也只存摘要。

Mongo 新增索引：`accounts_email_unique`（email 唯一）、`verification_email_purpose_unique`（email+purpose 唯一）、`verification_expiry`、`rate_expiry`（expires_at 普通索引，供清理）。SQLite 以表内唯一约束与事务保持同样语义。旧索引只增不删；冲突索引显式失败，不静默重建。

## 3. Argon2id 实现及参数

`security/passwords.py` 用 argon2-cffi：`PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID)`，即内存 64 MiB、迭代 3、并行 4。密码约束 10–128 字符，不截断。登录成功且 `needs_rehash` 为真时，在账号 CAS 内用当前参数重哈希并随会话写入同次提交；竞争失败重读合并，不会丢会话。未知邮箱登录调用 `dummy_verify`（对固定假哈希做一次真实 Argon2 校验）均衡时序，测试用 monkeypatch 计数证明未知邮箱与畸形密码路径确实执行了等量哈希工作。

## 4. 验证码和邮件发送流程

申请：`POST /api/verification-codes {email, purpose}` → 路由先过三组共享限频（邮箱 1/60s、邮箱 5/h、IP 10/h）→ VerificationService.request_code 生成 6 位数字码，计算 `HMAC-SHA256(secret, email|purpose|code)` 摘要，作废旧码并以 CAS 写入新记录（10 分钟有效）→ 调用注入的 EmailCodeSender 投递。响应恒 202 `{status:"accepted"}`：未知邮箱、已注册邮箱、投递失败外部不可区分。reset 用途对未知邮箱静默不发信；register 用途对已注册邮箱仍发码（409 只在注册端点消费有效码之后才出现）。投递失败记 SEND_FAILED 并把该码标记 consumed（不可再用），日志只留净化信息，不含邮箱/验证码。

消费：注册/找回提交 code 后，`consume` 重算 HMAC 摘要并 `hmac.compare_digest` 常量时间比较；错误尝试 attempts+1，达到 5 次后即使正确码也 CODE_LOCKED；到期时刻即失效；consumed_at 非空即单次使用拒绝；purpose 不匹配 INVALID_CODE。并发消费用真实双仓储 CAS 竞争测试证明只有一方成功。重发（再次 request_code）使旧码作废并重置尝试数，并发重发测试证明最终只有一条活码。

邮件适配器必须显式选择：`TWOWORLDS_EMAIL_MODE=console` 仅本地开发（stdout 打印验证码，不进应用日志）；`smtp` 强制 TLS/超时，主机/端口/账号/密码/发件人全部来自环境变量，失败只抛净化的 EmailSendError。没有默认回退；create_app 必须注入 email_sender 与 verification_secret（≥32 字符），dev 入口省略密钥时生成一次性临时密钥（重启作废未用码）。

## 5. Cookie 和 CSRF 实现

会话 token 为 `secrets.token_urlsafe(32)`，只存 SHA-256 摘要；7 天有效、每账号最多 5 个，新会话淘汰最旧（created_at 稳定排序）。`api/cookies.py` 下发 `tw_session`：HttpOnly、SameSite=Lax、Path=/、Max-Age=604800，不设 Domain；`cookie_secure=True`（生产 HTTPS）时加 Secure。登出/重置清除 Cookie（Max-Age=0）。

`api/auth.py` 只解析 Cookie 头中恰好一个非空 tw_session；Authorization/Bearer、查询参数 token、账号 ID 一律不作为认证凭证（有专门测试）。浏览器端不依赖本地时间判断过期。

CSRF 在最外层 IdentitySafety 中间件：所有 /api/* 的 POST/PUT/PATCH/DELETE 要求 Origin 恰好一个且精确命中白名单，缺失/null/重复/大小写或尾斜杠差异都 403 CSRF_REJECTED；检查先于正文大小限制、认证与限频，恶意 Origin 不可能触达 413/429 路径。GET 豁免。CORS 只对精确白名单 Origin 开 `Access-Control-Allow-Credentials: true`，暴露 Retry-After，禁止通配符；工厂拒绝通配符配置。所有身份响应（含错误）no-store。

## 6. 限频实现及多实例验证

`application/rate_limit.py` 的 SharedRateLimiter 把计数器存进数据库（SQLite rate_limits 表 / Mongo rate_limits 集合），`hit` 用版本条件 CAS 递增，冲突重读重试（上限 8 次）；固定窗口以首次命中为锚，窗口过期重新计数；Retry-After 向上取整到窗口结束。容量上限 10000 键，满容量拒绝新键（fail-closed），已有键预算不受影响；cleanup 只删到期记录。键与 IP 都只存摘要；peer IP 只读 ASGI scope["client"]，不信任 X-Forwarded-For。

策略：验证码邮箱 1/60s + 5/h、IP 10/h；登录 IP+邮箱组合 5/min + 20/h。429 RATE_LIMITED 带 Retry-After。多实例验证：两个独立 create_app 实例（各自仓储对象）指向同一 SQLite 文件/同一 Mongo 库，共享同一预算；重启后计数保持；8 线程并发 hit 恰好放行配额数（真实 CAS 竞争，Barrier 对齐）。没有 Redis，也没有退回进程内存方案。

一个已固定的顺序事实：FastAPI 先做 Schema 校验再进路由体，因此畸形正文（422）不消耗邮箱键预算；有专门测试固定此行为，而不是假设"错误请求也计数"。

## 7. SQLite/Mongo 实际测试结果

真实 Mongo：本机 Docker 容器 twoworlds-mongo（MongoDB 8.0.34，127.0.0.1:27017），所有 mongo 参数组用真实库，每测试随机临时库并清理；没有 Mock 替代。专项（SQLite/Mongo 双适配均通过）：

- tests/application/test_identity.py：56 通过（注册/登录/重置/认证/撤销、哈希升级、dummy_verify 计数、五会话淘汰、并发注册唯一性、CAS 竞争与重试耗尽、时钟回退）。
- tests/application/test_verification.py：46 通过（摘要/单次/5 次锁定/到期边界/purpose 隔离/重发废旧/并发消费与重发/发送失败作废/防枚举）。
- tests/application/test_rate_limit.py：26 通过（窗口/Retry-After/跨实例共享/8 线程竞争/容量 fail-closed/清理/策略校验）。
- tests/api/test_identity.py + test_rate_limit.py + test_request_limits.py：82 通过（Cookie 属性、CSRF 六形态、防枚举 parity、限频端到端含不同 peer IP 的 ASGI 包装、正文 16KiB、CORS 凭证、真实 Mongo HTTP、跨应用文件登录）。
- tests/api/test_dev_launcher.py：19 通过（显式配置、console 取码注册、显式密钥重启后旧码仍可用、真实 CLI/TCP 子进程 SQLite/Mongo 注册建房）。
- tests/contracts/test_identity.py：7 通过（登录所有权、身份字段拒绝、同名不同账号、登出只当前、重置撤销全部会话）。

规格第十二节 44 项验收点全部有对应行为测试（映射见第 8 节后的附录）。

## 8. 修改前后测试统计

- 改动前基线（同环境全量）：**3 failed, 1199 passed, 0 errors, 0 skipped**（work/t0632-baseline.txt，1143.65s；3 项为既有 T12 WS 两项、T14 NPC 一项，均在 tests/contracts/test_platform.py）。
- 改动后全量（真实 Mongo）：**3 failed, 1324 passed, 0 errors, 0 skipped**（work/t0632-final4.txt，1318.74s）。失败 ID 与基线逐项相同，无新增失败；新增 125 项全部通过。
- 中途诊断（如实记录）：
  - 对已适配的 5 个 API 测试文件单独运行发现 6 项失败（257 通过），全部是 TestClient cookie jar 与 CSRF 顺序的测试装配问题，不是业务缺陷：无显式 Cookie 的"无凭证"请求会自动带上最近注册的会话；无 Origin 的 POST 先被 CSRF 拒绝（403）而非 401。修复方式：无凭证断言统一用非会话 Cookie（`other=none`）覆盖 jar，POST 补精确 Origin；未削弱任何安全断言。修复后 6 项复验通过；contracts 套件 36 通过/3 既有失败。
  - 首次完整全量还暴露 3 项测试自身问题（共 4 个参数化失败）：pairs 测试仍引用已删除的 `recovery` 凭证命名空间；Mongo 微秒往返测试把 `created_at` 改成精确值却漏改 `email_verified_at`，触发"验证时间不得早于创建时间"的模型不变量；仓储契约竞争测试的 Barrier 包装每次 CAS 都等待，落败方重试时对方已返回导致 15 秒超时。均只改测试装配，保留原断言与安全意图；修复后逐项复验通过，最终全量无新增失败。
- ruff check src tests：All checks passed；ruff format 通过；uv lock --check --offline：Resolved 30 packages；git diff --check：无空白错误（仅 CRLF 提示）。

## 9. 新提交 SHA

实现提交与收尾文档提交的 SHA 见本轮交付回复；分支 `codex/t06-3-2-email-auth-backend`。

## 10. PR 链接

PR 创建后链接见本轮交付回复，目标 `codex/bootstrap`。未合并、未启用自动合并。

## 11. 尚未解决的问题

- 前端仍是恢复密钥旧界面，与新后端不兼容；T06.3.3 替换前浏览器无法走新注册流程。
- 旧匿名演示库未重置（规格禁止静默删库）；T06.3.4 负责重置并重新注册。
- 真实 SMTP 服务未联调（发送失败路径用注入故障验证）；生产邮件可达性未验证。
- WS 仍只有设计契约（Cookie 握手），未实现；QA-I04 的 WS 失效验证未验收。
- 多实例限频验证为同机两个应用实例共享同库，未做生产负载/多进程部署试验。
- Mongo 生产认证/TLS/复制集/备份未验证；本轮未重建发行包。

## 12. 建议首先阅读的 5 个代码文件

1. `backend/src/twoworlds/domain/persistence.py` — Account/验证码/限频三个记录模型与约束。
2. `backend/src/twoworlds/application/identity.py` — register/login/reset_password 的 CAS 编排与防枚举。
3. `backend/src/twoworlds/application/verification.py` — 验证码生命周期（HMAC 摘要、尝试数、作废）。
4. `backend/src/twoworlds/api/app.py` — IdentitySafety 中间件：CSRF → 正文限制 → no-store 的顺序。
5. `backend/tests/identity_support.py` — 测试如何注册/登录/扮演多身份，是读懂全部新测试的钥匙。

## 附：完整注册流程（用户视角 → 代码路径）

1. 用户输入邮箱，前端（未来 T06.3.3）调 `POST /api/verification-codes {email, purpose:"register"}`。路由先查三组数据库限频键，通过后 VerificationService 生成 6 位码、存 HMAC 摘要、经 EmailCodeSender 发信；响应恒 202。开发模式 console 适配器把码打印到本机控制台。
2. 用户收到邮件（开发时看控制台），输入验证码、密码（10–128 字符）与昵称，调 `POST /api/accounts`。
3. 路由校验严格 Schema 后，先 consume 验证码（常量时间比较、尝试数、单次、purpose），通过才进入 IdentityService.register；register 先校验输入并计算 Argon2id 哈希，再检查邮箱唯一性——已注册此时才 409，随后生成首个会话 token（只存摘要）并创建账号。验证码消费与账号创建是两次独立的原子操作（前者 CAS，后者靠邮箱唯一约束）。
4. 成功 200 返回 `{account:{id,email,display_name}, session:{expires_at}}`，Set-Cookie 下发 tw_session（HttpOnly/SameSite=Lax/7 天）。token 明文只存在于 Cookie，不进 JSON/日志/存储。
5. 页面加载调 `GET /api/me`：auth.py 从 Cookie 取 token → 摘要查账号 → 显式判断过期 → 返回当前账号概要与到期时间。浏览器据此判断登录态，不读本地时间。
6. 之后所有状态变更请求自动带 Cookie，并须通过精确 Origin 校验；登出 `DELETE /api/sessions/current` 只撤销当前会话并清 Cookie，其他设备不受影响。

## 附：规格 44 项验收点 → 测试映射（摘要）

密码与账号 1–9：application/test_identity.py 注册/规范化/重复/哈希存储/登录/错误与未知邮箱/升级/并发注册唯一性（RegistrationBarrier 逼出真实唯一约束竞争，恰好一方成功）。验证码 10–19：application/test_verification.py 全部条目（含并发消费、发送失败、防枚举 parity）。会话 20–28：api/test_identity.py（自动登录、Cookie 属性、无/伪造 Cookie、过期、第六淘汰、登出只当前、重置撤销全部）与跨应用文件登录/重启测试。CSRF 与限频 29–38：api/test_identity.py CSRF 参数化六形态 + CORS 凭证；api/test_rate_limit.py 邮箱/IP/组合/多实例共享。数据库 39–44：storage 共享契约双适配、test_mongo_contract.py 邮箱唯一索引、验证码原子消费与限频原子竞争（application 层真实 CAS）、dev/identity 重开数据库测试。