# T06.2 · HTTP 身份接口与安全策略

日期：2026-11-14。仅后端身份HTTP；没有房间/存档/游戏命令/NPC API、WS、前端、OAuth、密码或生产部署。

## 基线与文件

PR #15 已合并；fetch后最新codex/bootstrap为 `90fb8fd44c8b955dffde519d29872e94042f94c0`，从此建立 `codex/t06-2-http-identity`。独立工作树 `F:\two-worlds-agent-game\work\pr-t01-1-schema` 开始干净；主目录用户学习修改和旧本地提交未覆盖/推送。

新增 api/app.py、auth.py、errors.py、rate_limit.py、routers/{__init__,accounts,sessions}.py、schemas/{__init__,identity}.py，新增 tests/api/{conftest,test_identity,test_rate_limit}.py 和本报告。修改后端README、任务/交接、pyproject与uv.lock。原IdentityService、凭证工具、仓储、领域、tests/contracts均未修改。

FastAPI **0.132.0** 从dev移入运行时，httpx/pytest/ruff仍留dev。通过uv重新锁定并同步，原24包的版本逐一相同，没有升级。编辑过程中曾误移除FastAPI，发现后立即修正，再次uv锁/同步恢复原版本；最终差异只改变依赖归属，不含该中间状态。Python3.12.4、PyMongo4.19.0、MongoDB8.0.34。

## 接口与白名单

| 方法/路径 | 输入 | 成功返回 |
| --- | --- | --- |
| POST /api/accounts | 仅display_name，复用领域DisplayName | 200：account{id,display_name}、recovery_key、session{token,expires_at} |
| POST /api/sessions/recover | 仅recovery_key，严格字符串1～128字符 | 200：同一account、新session{token,expires_at}；不再返回恢复密钥 |
| GET /api/me | Authorization: Bearer session_token | 200：account{id,display_name}、当前session{expires_at}；不返回任何明文凭证 |
| DELETE /api/sessions/current | Authorization: Bearer session_token | 204空正文，只撤销当前设备 |

创建示例请求为 `{"display_name":"旅人"}`；恢复请求为 `{"recovery_key":"<仅示意，不是真实凭证>"}`。响应示意：

```json
{
  "account": {"id": "account_example", "display_name": "旅人"},
  "recovery_key": "<仅创建时返回>",
  "session": {"token": "<当前会话凭证>", "expires_at": "2026-11-21T00:00:00Z"}
}
```

所有请求模型strict、extra=forbid，不忽略account_id/player_id/user_id/role等字段。恢复请求秘密字段repr=False。响应由专用Schema逐字段构造，禁止直接dump AccountRecord，不输出摘要、内部sessions数组、Mongo字段或其他设备token。

## 装配与认证

`create_app(repository=..., ai_mode="demo", allowed_origins=[...])` 兼容原测试接缝。应用实例各持有IdentityService和RateLimiter；不在模块导入时连接数据库，不读取真实AI密钥、不调用模型，也不默认选择SQLite。注入repository由该app的lifespan在关闭时close；多实例共享文件应各自构造Repository，不将同一已关闭对象复用。

可注入identity_clock、rate_clock以及rate_limit/window/max_keys，均仅供可信Python装配使用，不接受客户端配置。ai_mode仅保留既有工厂参数兼容性，本轮没有AI功能。

auth.py只读取唯一Authorization头；要求Bearer加单个token。缺失、重复头、错误格式、错误用途、账号ID等统一401。URL查询token不会被当作认证来源。IdentityService完成摘要及有效期/撤销/淘汰/时钟水位检查，API据已认证账户精确找到当前摘要的expires_at，不能误取其他设备期限。

allowed_origins精确匹配，拒绝通配符、含用户密码或路径/查询的来源配置；CORS不启用credentials，仅允许GET/POST/DELETE和Authorization/Content-Type。默认不允许任何跨域来源。限频和未知错误在CORS之外生成时仍只为已配置来源补响应头；不反射任意Origin。

## 错误、缓存与日志

所有身份JSON错误使用 `{error:{code,message,retryable}}`。IdentityError映射如下，401含WWW-Authenticate: Bearer：

| code | HTTP | retryable |
| --- | --- | --- |
| UNAUTHENTICATED | 401 | false |
| INVALID_INPUT | 422 | false |
| CONCURRENT_UPDATE | 409 | true |
| DEPENDENCY_UNAVAILABLE / GENERATION_FAILED / CLOCK_ERROR | 503 | true |
| RATE_LIMITED | 429 | true，带Retry-After |
| INTERNAL_ERROR | 500 | true |

RequestValidationError只返回固定INVALID_INPUT，不序列化Pydantic原始输入/错误对象。未知内部错误不返回异常原文，不记录请求、异常栈或凭证。未知路由404和错误方法405同样使用安全JSON信封。CORS预检使用标准CORS协议响应。

纯ASGI安全层为所有HTTP响应写Cache-Control:no-store，包括成功200、204、401/422/429/503、未知500和CORS预检。未知500在开始响应前捕获并转换，避免默认TestClient把内部错误重新抛给调用方。未实现流式业务；已开始响应后发生的错误不能再伪造新成功响应。

没有应用请求/响应正文、Authorization、秘密或摘要日志。caplog在INFO级别核对创建/恢复/查询流程中随机凭证和摘要不出现。这个结论只覆盖本轮应用代码及测试日志；独立HTTP服务器、代理或生产访问日志的配置未部署/验证，不能据此宣称外部日志绝对不泄露查询参数。

## 单进程限频

创建和恢复分别按 `(路径, ASGI客户端IP)` 计数，每60秒最多5次。读取peer地址，不解析任意X-Forwarded-For；真实代理部署还需审查ASGI服务器的可信代理配置。

限频位于请求校验/业务之前，错误恢复密钥和非法请求体也消耗额度，不用恢复密钥作为键。固定窗口按首次请求开始，Retry-After对剩余秒数向上取整，边界到期即可继续。默认使用monotonic；测试注入时间若回退则夹至已见水位，不重置窗口。

每app独立Lock与OrderedDict，锁仅保护限频计数，不替代数据库CAS。按窗口开始顺序清理过期记录，上限10000个键；容量满时新来源返回429直到最早窗口到期，而不是驱逐活跃计数制造绕过。无后台线程、无Redis、不跨应用实例共享。公开多实例部署需要共享或边缘限频，当前实现不能提供分布式保证。

## 验证方法与结果

先新增测试复现缺应用模块（2 failed/26 errors）。初实现HTTP和原身份契约34通过；补重复认证头、非法JSON和当前设备期限后36通过；加真实Mongo HTTP流程后37通过（新HTTP/限频31项、原身份契约6项）。不修改原契约或跳过测试。

跨设备测试使用两个依次启动的独立FastAPI应用、独立SQLiteRepository、同一真实文件。第一应用创建后关闭，第二应用恢复并查询原account_id，数据库账户数仍为1。Mongo另有真实HTTP创建/恢复/me/撤销验证。

测试覆盖响应白名单/摘要持久化、不回显秘密、错误用途/额外字段、过期/撤销/第六会话淘汰、重复登出401、当前设备期限、所有no-store状态、CORS、异常映射与未知500、限频线程竞争/满额/清理/窗口/独立接口及XFF不绕过。

### 最终统计

下表专项分别执行，不相加作为全量数；0 errors、0 skipped。全量与原契约有1条既有警告，未通过改测试消除。

| 验证范围 | 通过 | 失败 | 退出码 |
| --- | ---: | ---: | ---: |
| 新HTTP/限频31项 + 原身份契约6项 | 37 | 0 | 0 |
| 原身份服务（SQLite/Mongo各22） | 44 | 0 | 0 |
| SQLite专项11 + 共享契约30 | 41 | 0 | 0 |
| 真Mongo专项17 + 共享契约30 | 47 | 0 | 0 |
| Domain | 308 | 0 | 0 |
| Content | 191 | 0 | 0 |
| 首轮全量（并行专项期间） | 637 | 33 | 1 |
| 串行全量复验（670项） | 638 | 32 | 1 |
| Ruff check | 通过 | 0 | 0 |
| Ruff format --check | 68文件通过 | 0 | 0 |
| uv lock --check --offline | 24包一致 | 0 | 0 |

首轮多出的失败为既有 `tests.content.test_publication::test_windows_rename_retry_is_bounded_and_never_creates_a_partial_record[False]`：预期3次rename调用、实际4次。该测试先注入2次PermissionError，随后调用真实Windows rename；代码会对winerror 5/32做有界重试，多一次底层可重试错误是可能原因，未定位到具体外部占用者，不能断言其根因。单独复验该组2通过/43未选中，随后串行全量该用例通过。原测试和publication实现完全未改，首轮记录保留，不隐藏为通过。

本地忽略目录中的JUnit证据为work/t062-{http,identity,sqlite,mongo,domain,content,all,all-serial}.xml；旧基线为work/t061-clock-all.xml。这些临时文件不进PR；本报告保留统计和逐项比较。

### 实际执行命令

在独立工作树根目录、项目Python3.12.4中运行（测试文件写入work临时目录）：

```powershell
$env:MONGO_URI='mongodb://127.0.0.1:27017/?directConnection=true'
$env:TWOWORLDS_TEST_BACKEND='sqlite'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/api backend/tests/contracts/test_identity.py -q --tb=short -p no:cacheprovider --basetemp=work/t062-http --junitxml=work/t062-http.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/application/test_identity.py -q --tb=short -p no:cacheprovider --basetemp=work/t062-identity --junitxml=work/t062-identity.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_sqlite.py backend/tests/storage/test_repository_contract.py -q --tb=short -p no:cacheprovider --basetemp=work/t062-sqlite --junitxml=work/t062-sqlite.xml
$env:TWOWORLDS_TEST_BACKEND='mongo'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_mongo_contract.py backend/tests/storage/test_repository_contract.py -q --tb=short -p no:cacheprovider --basetemp=work/t062-mongo --junitxml=work/t062-mongo.xml
$env:TWOWORLDS_TEST_BACKEND='sqlite'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain -q --tb=short -p no:cacheprovider --basetemp=work/t062-domain --junitxml=work/t062-domain.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q --tb=short -p no:cacheprovider --basetemp=work/t062-content --junitxml=work/t062-content.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short -p no:cacheprovider --basetemp=work/t062-all --junitxml=work/t062-all.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content/test_publication.py -k windows_rename_retry_is_bounded -q -p no:cacheprovider --basetemp=work/t062-rename-recheck
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short -p no:cacheprovider --basetemp=work/t062-all-serial --junitxml=work/t062-all-serial.xml
.\backend\.venv\Scripts\ruff.exe check backend/src backend/tests backend/hatch_build.py
.\backend\.venv\Scripts\ruff.exe format --check backend/src backend/tests backend/hatch_build.py
uv lock --check --offline --project backend --cache-dir F:/two-worlds-agent-game/work/uv-cache
```

依赖变更使用uv锁定及离线sync，不改全局Python。所有24包版本与基线uv.lock逐一比较一致。收尾时Ruff直接遍历backend会遇到已有backend/work缓存目录拒绝访问（format退出1，虽打印68文件已格式化）；不改目录权限，改为显式检查全部源码、测试和构建钩子，两个命令均退出0。文档链接/代码块通过；交接中既有原始聊天链接只在主目录存在，独立工作树不含被忽略的原聊天文件，本轮未上传。

### 历史失败逐项比较

基线601通过/38失败（639项）；本轮新增31项，因此全量670项。38项旧失败消息完全相同：`Failed: 契约尚无业务实现（T04/T08）：twoworlds.api.app`。现有应用工厂使身份6项通过，其余32项均实际执行到`POST /api/pairs`，断言收到404，消息体为`{"error":{"code":"NOT_FOUND","message":"请求无法处理。","retryable":false}}`。不是本轮身份接口失败，也不能据此声称这些契约的后续步骤已经验证。串行复验新增失败ID为0、消失6项、剩余32项错误消息按上述方式变化。

| 原失败用例 ID | 本轮结果 |
| --- | --- |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[bad-id]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[boolean]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[client-role]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[extra-arg]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[legacy-value]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_commands::test_invalid_command_does_not_change_save_or_create_receipt[negative]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_commands::test_old_version_retry_confirms_receipt_and_returns_current_snapshot` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[args]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[kind]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_commands::test_same_actor_cannot_reuse_id_with_changed_payload[original-version]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_commands::test_same_request_id_is_independent_for_other_actor` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_commands::test_two_application_instances_compete_on_one_database[different]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_commands::test_two_application_instances_compete_on_one_database[identical]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_identity::test_client_cannot_claim_identity_or_role[account_id]` | 通过：身份 HTTP 已实现 |
| `tests.contracts.test_identity::test_client_cannot_claim_identity_or_role[player_id]` | 通过：身份 HTTP 已实现 |
| `tests.contracts.test_identity::test_client_cannot_claim_identity_or_role[role]` | 通过：身份 HTTP 已实现 |
| `tests.contracts.test_identity::test_display_name_does_not_restore_another_account` | 通过：身份 HTTP 已实现 |
| `tests.contracts.test_identity::test_logout_revokes_only_the_current_session` | 通过：身份 HTTP 已实现 |
| `tests.contracts.test_identity::test_recovery_proves_ownership_and_issues_a_distinct_session` | 通过：身份 HTTP 已实现 |
| `tests.contracts.test_platform::test_demo_npc_is_private_and_cannot_change_game_facts` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[early-dispatch]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[unpowered-repair]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[unscanned-rail]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_invalid_role_or_prerequisite_changes_neither_projection[wrong-role]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_lighthouse_requires_both_roles_and_agreed_ending[guide_now]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_lighthouse_requires_both_roles_and_agreed_ending[wait_tide]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_only_discovered_owner_can_share_the_designated_clue_text` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_outsider_websocket_never_receives_a_snapshot` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_power_budget_rejects_the_entire_allocation` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_private_projection_and_forbidden_access` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_restart_restores_identity_save_and_receipt` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_room_admits_only_one_partner_across_application_instances` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_scripts_and_pairs_have_independent_saves_and_receipts` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_starline_has_a_distinct_cooperative_solution[rescue_detour]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_starline_has_a_distinct_cooperative_solution[return_station]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_unfilled_room_allows_reading_but_no_game_or_npc_write[game-command]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_unfilled_room_allows_reading_but_no_game_or_npc_write[npc]` | 仍失败：POST /api/pairs → 404 NOT_FOUND |
| `tests.contracts.test_platform::test_websocket_uses_auth_frame_and_personal_projection_on_reconnect` | 仍失败：POST /api/pairs → 404 NOT_FOUND |


## 学习与边界

阅读schemas/identity.py → auth.py及routers → errors.py → rate_limit.py → app.py装配/ASGI安全层 → tests/api与未修改的contracts/test_identity.py。现有HTTP仅身份四个接口；TestClient已执行真实ASGI请求栈，没有启动独立TCP监听服务或提供公网地址。

文档03接口形状和工厂契约没有调整，因此本轮不改该设计文档；按本轮授权提前落地应用工厂，不因此实现其中尚属T07/T08的路由。QA-I01～I05取得HTTP证据；WS首帧、持续鉴权和过期关闭留T12，前端缓存排除留T10/T13。T06.1已在PR #15合并。本轮完成后停止，下一步只建议T07，不自动执行。

参考：[FastAPI异常处理](https://fastapi.tiangolo.com/tutorial/handling-errors/)。本轮使用固定项目版本，验证以本机测试为准。
