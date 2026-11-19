# TwoWorlds 后端

后端已有两剧本领域、SQLite/Mongo仓储、身份与房间/存档/命令/受保护媒体HTTP。T10.2新增下方开发专用HTTP启动器，复用既有服务和权限规则，完成前端房间/书架的真实SQLite/Mongo联调。正式发布库仍为空，不将草稿或测试媒体发布为产品内容。[本轮报告](../docs/reports/t10-2-identity-room-library.md)记录实际验证；下文历史阶段的未实现描述以各阶段交付时间为准。

## 1. 先看这几个文件

1. `pyproject.toml`：包名、Python要求、构建方式、依赖和检查工具配置。
2. `.python-version`：让支持该文件的工具优先选择Python3.12，避免误用本机`py`启动器默认的3.14。
3. `src/twoworlds/__init__.py`：Python包入口；目前只有包说明，导入不会连接数据库或调用模型。
4. `uv.lock`：uv生成的依赖解析结果，提交后按锁文件同步；不要手工改其中的版本和校验值。

安装名`twoworlds-api`是分发包名称，代码中使用`import twoworlds`。`src`布局让运行与测试通过已安装的包访问源码，避免仅因当前目录碰巧在搜索路径里而导入成功。

## 2. 模块如何对应架构

| 路径 | 将来负责什么 | 当前状态 |
| --- | --- | --- |
| src/twoworlds/api | HTTP、WS路由、请求模型与认证适配 | 身份/房间/目录/存档/命令回执/受保护媒体已实现；WS待后续 |
| src/twoworlds/application | 身份、房间、存档、对话的流程编排 | IdentityService、PairService及SaveService生命周期/命令已实现；对话待后续 |
| src/twoworlds/domain | 确定性规则与可见性投影 | 灯塔规则、个人投影、线索分享、公共历史与回顾 |
| src/twoworlds/content | 草稿校验、快照发布、哈希与Metadata目录、包资源读取 | T01内容基础设施已实现；灯塔未发布，真实媒体与许可尚缺 |
| src/twoworlds/ports | 仓储、文本、语音等适配接口 | Repository Protocol 与 EmailCodeSender 已定义；文本/语音适配接口待实现 |
| src/twoworlds/storage | Mongo、SQLite与原子提交适配 | 严格 JSON、SQLite 事务及 Mongo 单文档 CAS/索引已实现，真库契约通过 |
| src/twoworlds/ai | 受限LangGraph文本流程与Provider | 仅模块边界 |
| src/twoworlds/realtime | 订阅、个人快照和连接协议 | 仅模块边界 |
| tests/contracts | 已迁移的身份、命令与平台行为要求 | 邮箱身份7项及房间竞争契约通过；后续存档/平台契约待T08等 |
| tests/content | 字段/引用/媒体声明与加载/发布边界 | 74个Schema+36个加载+36个正式内容+45个发布检查通过；不是完整游戏验收 |
| tests/domain | 真实内容驱动的领域行为 | 规则 123 项、投影 90 项、剧本重建 10 项、分享与回顾 29 项通过 |
| tests/storage | 同一共享契约切换适配器，真实约束/故障验证 | T08.1 SQLite组44、真实Mongo组50通过，均含32项共享契约 |

模块之间的接口将在对应任务中定义，现在不放假API、空服务类或模拟的通关实现。

## 3. 从项目根目录使用

先准备Python3.12和uv，然后在`F:\two-worlds-agent-game`执行：

```powershell
uv sync --project backend --python 3.12 --locked --no-python-downloads
uv run --project backend --locked python -I -c "import twoworlds; print(twoworlds.__file__)"
uv run --project backend --locked python -m pytest --version
uv run --project backend --locked ruff check backend/src
```

`uv sync`把包与开发工具装进`backend/.venv`，不修改全局Python依赖。`--locked`要求现有锁文件与配置一致；需要明确更新依赖时再运行lock并审阅变更。`--no-python-downloads`要求使用本机已安装的Python，找不到时会报错，而不是另行下载解释器。

第二条命令应打印本项目`backend/src/twoworlds/__init__.py`的绝对路径。`-I`排除当前目录和用户Python路径的干扰；能导入说明本项目确实已安装到所选环境。

`twoworlds.api.app.create_app(repository=..., ai_mode="demo", allowed_origins=[...], email_sender=..., verification_secret=...)` 已实现，注册邮箱身份、房间、目录、存档、命令回执与受保护媒体接口。T06.3.2起`email_sender`与`verification_secret`必填，没有默认邮件适配器或内置验证码密钥。仓储必须由调用方显式传入，导入模块不连接数据库，也不自动回退SQLite。应用退出时关闭传入仓储；多个应用应各自持有指向同库的独立仓储对象。没有模块级app，不要运行`uvicorn twoworlds.api:app`；开发专用TCP入口见第17节。

## 4. 构建与验证

```powershell
uv build --project backend --python 3.12 --no-python-downloads --no-sources --out-dir backend/dist
```

构建产物包含wheel与源码归档；两者均排除tests/work/outputs/IDE/缓存/私人资料。`hatch_build.py`先复用现有Schema与发布库核验，再逐一收录草稿JSON、发布登记和已发布实际媒体；不收录未审核的草稿媒体和未登记杂项。sdist带构建钩子及必要配置，wheel不带钩子或测试。T01.2.3已实际检查清单、从sdist重建wheel、独立安装与临时测试媒体集成，详见[发布报告](../docs/reports/content-publication.md)。

T00.3后的测试运行方法与阅读顺序见[测试说明](tests/README.md)，来源映射见[基线修订报告](../docs/reports/baseline-changes.md)。执行`python -m pytest backend/tests/contracts --collect-only -q`可查看38个契约要求；目前身份6项已通过，命令13项、平台19项在未实现的`POST /api/pairs`返回404。后续任务将补齐相应应用服务和通道测试。

T01.1新增74个内容校验用例，当时全量收集为112个（74个已通过、38个仍缺实现）。可从项目根目录运行`.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q`；源码阅读顺序、测试专用JSON与边界见[Schema报告](../docs/reports/content-schema.md)。模型返回冻结定义，游戏状态另建；不要把包含私有线索的ScriptVersion整体发给客户端。

T01.2.1又新增36个加载测试，当时全量148项（110通过、38仍缺实现）。在检出当前分支的项目根运行`.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content/test_loader.py -q --basetemp=work/pytest-loader-local`可观察加载器；实际PR工作树为`F:\two-worlds-agent-game\work\pr-t01-1-schema`。严格路径权限与只读边界见[加载器报告](../docs/reports/content-loader.md)。

T01.2.2的正式内容位于`src/twoworlds/content/scripts/lighthouse/1.0.0.json`，以`content/scripts`为root即可按ID/版本加载。当时新增36个检查后，全量184项（146通过、38仍缺实现）。可运行`.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content/test_lighthouse_content.py -q --basetemp=work/pytest-lighthouse-local`；具体加载命令与字段阅读顺序见[正式内容报告](../docs/reports/lighthouse-content.md)。该环节只验证源码内容；后续发布验证见下段，实际媒体、游戏执行与服务入口尚无。

T01.2.3的入口依次为`content/publication.py`（审核、快照发布与目录）、`content/packaged.py`（包内with上下文）、`hatch_build.py`（构建时校验与文件收录）、`tests/content/test_publication.py`、`tests/packaging/verify_distribution.py`。新增45个检查，全量229项（191通过、38仍缺实现）。既有Schema、加载器和正式灯塔JSON未改；发布工具完成不表示灯塔已发布。

```powershell
@'
from twoworlds.content.packaged import packaged_content
with packaged_content() as content:
    print(content.load_draft('lighthouse', '1.0.0').metadata.title)
    print(content.catalog())
    print(len(content.audit_draft('lighthouse', '1.0.0')))
'@ | .\backend\.venv\Scripts\python.exe -I -X utf8 -
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content/test_publication.py -q --basetemp=work/pytest-publication-local
```

预期加载草稿、目录为`()`、媒体检查28项；测试45 passed。开发安装中的文件存在不等于打包完成；资源报告的`included_in_package`还需匹配已安装分发包RECORD的SHA256。安装验证与适合阅读的多行with示例见发布报告。

T02使用`domain.engine.create_initial_state(script)`初始化，再由`apply_command(state, script, actor_role, {kind,args})`返回可解包的`CommandResult(state,events)`。输入与嵌套值不可变，实际变化才version+1，所有事件绑定该新版本；错误抛`DomainError.code`。完整状态/事件只是服务端领域结果，不能直接作为玩家响应；actor_role须由后续身份/成员服务提供。

单独运行T02测试：`.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain/test_lighthouse.py -q --basetemp=work/pytest-t02-local`为123通过。阅读顺序：`domain/models.py` → `engine.py` → `mechanics/common.py` → `mechanics/lighthouse.py` → `tests/domain/test_lighthouse.py`。完整12步/不同探索顺序16步演示及拒绝/版本说明见[规则报告](../docs/reports/lighthouse-engine.md)。

T03.1 的 `project_save(state, script, role)` 使用与命令共用的 `engine.validate_state_and_script` 取得重建的冻结状态和剧本。投影从这对模型构造 `PlayerSnapshot`，包含本人和已共享线索、本人装置与观察、可用动作及获准媒体引用。运行 `.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain/test_projection.py -q --basetemp=work/pytest-projection-local` 可复跑 90 项投影测试。字段说明、A/B 比较示例、剧本重建回归和全量结果见报告。[投影报告](../docs/reports/player-projection.md)

## 5. 依赖策略

本阶段运行依赖为 Pydantic 2.14.1（内容 Schema）、PyMongo 4.19.0（同步 MongoClient）及 FastAPI 0.132.0（T06.2从dev移入）。PyMongo 的传递依赖 dnspython 为 2.9.2；uv锁定共24包，本轮逐一比较版本均未升级。pytest9.0.2、ruff0.15.4、httpx0.28.1仍为dev依赖。uvicorn、LangGraph等按后续任务加入，不依赖全局环境碰巧存在的包。

Hatchling 负责 Python 分发包构建，uv 负责解析、项目虚拟环境同步与工具执行；两者都不启动游戏服务。构建系统仍要求 Pydantic2.14.1，以便隔离构建复用发布校验；驱动和锁文件在 T05.1 更新，T05.2 没有修改任何依赖。包没有发布到 PyPI。


先从 `src/twoworlds/domain/persistence.py` 阅读 SaveRecord 的版本绑定，再看 `src/twoworlds/storage/serialization.py` 的读写校验和 `src/twoworlds/ports/repository.py` 的原子写入契约。测试位于 `tests/domain/test_persistence.py`，其中包含真实灯塔进度、公共历史、两角色回执和中文对话的 JSON 往返。[复现命令](../docs/reports/persistence-models.md)

## 6. SQLite 演示仓储（T04.2）

`SQLiteRepository(path)` 显式打开文件并建表，每次操作使用独立连接；调用完成提交，异常回滚。账户 JSON 与会话摘要索引同一事务更新，存档的状态/历史/对话/回执放在同一 JSON 聚合中，以版本条件原子替换。关闭后重新打开同一文件可恢复。SQLite 不替代生产 Mongo，也不提供 HTTP 身份认证。

从当前检出分支的项目根运行：

```powershell
$env:TWOWORLDS_TEST_BACKEND='sqlite'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_sqlite.py backend/tests/storage/test_repository_contract.py -q --basetemp=work/pytest-storage-local
```

预期 41 项通过。建议依次阅读 `ports/repository.py` → `storage/sqlite.py` 的 `_transaction`、`compare_and_swap_save` → `tests/storage/test_repository_contract.py` → `tests/storage/test_sqlite.py`。并发测试使用两个独立实例、同一临时数据库文件；SQL 触发器注入故障验证真实回滚。详细结构、复验和未完成边界见 [SQLite 报告](../docs/reports/sqlite-repository.md)。

## 7. MongoDB 环境（T05.1）

T05.1 已通过 PR #13 合并，只准备环境和同步驱动。环境版本、真实验证命令和生产差异见 [MongoDB 环境报告](../docs/reports/mongo-environment.md)。仓储和索引已在下方 T05.2 单独实现，不把环境验证当作仓储证据。

实际本机服务为 MongoDB 8.0.34，专用容器 `twoworlds-mongo`、数据卷 `twoworlds-mongo-data`，仅发布 `127.0.0.1:27017`，重启策略 unless-stopped。推荐 `mongo:8.0` 下载未完成，本轮采用已缓存官方 `mongodb/mongodb-atlas-local:8.0` 镜像，只运行 mongod，并将健康检查改为 Mongo Ping。真实 Ping、中文文档增查改删、容器重启后的持久化及临时库清理通过；不能据此称 Mongo 仓储已完成。

Mongo URI 通过进程环境变量 `MONGO_URI` 传入，不在 Python 源码或 Git 中保存凭证。连接时使用 `MongoClient(os.environ["MONGO_URI"])`；环境验证操作只写随机命名的临时数据库，完成后清理。不要将驱动安装或 Ping 成功当作仓储 CAS/并发契约通过。

先阅读 `pyproject.toml` 的驱动声明，再看 `uv.lock` 的实际锁定版本、环境报告中的容器/真实验证过程，最后回到 T05.2 的仓储边界。Docker 运行隔离的 MongoDB 服务，MongoDB 保存文档，PyMongo 让 Python 访问数据库，uv 管理本项目的依赖和虚拟环境。

## 8. MongoRepository（T05.2）

使用 `MongoRepository(uri, database_name)` 显式创建仓储，初始化 Ping 和稳定索引，不可用即失败。Account/Pair/Save 分别存一个完整文档；模型 id 映射 _id，时间为 UTC 固定六位微秒字符串，读写完整重验。条件 replace 将 Save 状态、历史、对话和回执同次提交；无需给当前 standalone 增设副本集或多文档事务。

```powershell
$env:MONGO_URI='mongodb://127.0.0.1:27017/?directConnection=true'
$env:TWOWORLDS_TEST_BACKEND='mongo'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_repository_contract.py -q
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/storage/test_mongo_contract.py -q
$env:TWOWORLDS_TEST_BACKEND='sqlite'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q
```

前两条分别为30/17通过；最后全量557通过、38项原API失败，退出码1。共享契约默认 sqlite，设置 mongo 后使用真库；两种专项各自固定适配器。完整测试包含真实 Mongo 专项，需 MONGO_URI、Docker 和缓存测试镜像（默认 mongodb/mongodb-atlas-local:8.0，TWOWORLDS_TEST_MONGO_IMAGE 可指定已准备镜像，不自动拉取）。缺数据库会明确失败，不使用 mock/skip。

每个 Mongo 测试使用自己的随机库，factory 每次新建 MongoClient，结束只清理本测试库。真实断连测试仅停止带本轮随机名/标签且完整ID匹配的临时 Mongo 容器，共享 twoworlds-mongo 不停止。阅读顺序：`ports/repository.py` → `storage/indexes.py` → `storage/mongo.py` → `tests/storage/conftest.py` → 共享契约/Mongo专项。完整证据、方法说明与生产未验证项见 [Mongo 仓储报告](../docs/reports/mongo-repository.md)。T06.1 已由PR #15合并；T06.2已由PR #16合并。


## 9. 身份服务（T06.1，历史；已被 T06.3.2 邮箱账号取代）

> 本节与第10节记录的恢复密钥/Bearer 身份是历史实现证据。2026-11-18 用户决定改为邮箱+密码账号；T06.3.2 已删除恢复密钥后端并替换为第18节的 Cookie 认证，不保留兼容分支。

IdentityService只依赖Repository Protocol，不依赖SQL/PyMongo。接口为create_account(display_name)、recover(recovery_key)、authenticate(token)、revoke(token)。创建响应含一次性恢复密钥和初始会话；恢复只返回新会话。秘密字段默认不出现在repr中；HTTP使用专用白名单Schema且不记录请求或响应正文。

生产凭证随机部分为secrets.token_urlsafe(32)，两个用途有不同前缀且独立生成；持久化只存SHA-256摘要。7天会话、最新5个按created_at稳定排序保留。恢复/撤销最多8次CAS尝试，每次冲突都重读并合并；失效token重复撤销返回UNAUTHENTICATED，数据不再变化。时钟和随机源可注入，默认实现安全。

```powershell
$env:MONGO_URI='mongodb://127.0.0.1:27017/?directConnection=true'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/application/test_identity.py -q
```

本轮实际44项通过（SQLite/Mongo各22项）。需要真实Mongo，缺环境会明确失败，不用mock代替并发证据。完整回归与文件阅读顺序见[身份报告](../docs/reports/identity-service.md)。T06.1已合并，HTTP接口见下节；房间API见T07；游戏业务API未实现。

## 10. HTTP 身份接口（T06.2，PR #16已合并；历史，已被第18节取代）

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| POST | /api/accounts | 仅接收display_name；返回account、一次性recovery_key、初始session |
| POST | /api/sessions/recover | 接收recovery_key；原account与新session，不再返回恢复密钥 |
| GET | /api/me | Bearer会话认证；只返回account及当前会话expires_at |
| DELETE | /api/sessions/current | 撤销当前会话，204空正文；重复请求401 |

所有身份响应（含错误）设置`Cache-Control: no-store`。严格请求模型拒绝额外身份字段；响应不包含摘要、完整AccountRecord或其他设备会话。认证只读取Authorization，不接受查询参数token或账号ID。统一错误结构为`{error:{code,message,retryable}}`，输入422、认证401、CAS冲突409、依赖/时钟503、未知错误安全500；异常原文不返回、不记录。

创建和恢复分别按peer IP每60秒5次，错误请求也计数；429带向上取整的Retry-After。每应用限频表最多10000键并清理到期记录，满容量拒绝新键；这是单进程策略，公开多实例需共享或边缘限频。默认不信任X-Forwarded-For，代理部署需独立配置可信来源。CORS仅允许精确配置的HTTP/HTTPS origin，无通配符和cookie凭证。

HTTP正文最多16384字节。Content-Length超限时不读取正文；无长度、分块或伪造较小长度时，仍逐块检查实际字节，超限立即返回413 `REQUEST_TOO_LARGE`（retryable=false、no-store），不读取尾部、不执行身份业务。合格正文使用有界缓冲后交给FastAPI解析；现有先限频的顺序保留。CORSMiddleware与外层自生成429均向允许的Origin暴露`Retry-After`，未授权Origin没有Access-Control-Allow-Origin。

在当前检出的工作树根目录复验（包含真实Mongo HTTP流程）：

```powershell
$env:MONGO_URI='mongodb://127.0.0.1:27017/?directConnection=true'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/api backend/tests/contracts/test_identity.py -q -p no:cacheprovider --basetemp=work/pytest-http-local
```

T06.2合并基线的身份HTTP与契约62项通过（身份30、限频10、正文限制16、原身份契约6），包含两个独立应用关闭/重开同一SQLite文件后恢复同一账号。工厂可注入identity_clock、rate_clock与限频参数，HTTP客户端不能设置这些选项。阅读顺序：schemas/identity.py → auth.py/routers → errors.py → rate_limit.py → app.py → tests/api。[报告](../docs/reports/identity-http.md)含完整命令、T06.2历史失败逐项比较、首次Windows文件重试偶发失败及复验记录。尚无独立监听或公开演示地址；WS、前端缓存与T08接口未实现；T07见下节。本轮完成后等待审查，不自动继续。


## 11. 双人房间与邀请（T07，PR #17已合并）

四个端点均要求有效Bearer会话并返回no-store：

| 方法/路径 | 请求 | 200响应 |
| --- | --- | --- |
| POST /api/pairs | 无正文、null或空对象 | {id,role:"a",invite_token,invite_expires_at} |
| POST /api/pairs/{id}/invite | 同上，仅A且B空 | 与创建相同；旧邀请立即失效 |
| POST /api/pairs/join | 仅{invite_token} | {id,role:"b"} |
| GET /api/pairs | 无 | 直接数组[{id,role,member_count}]，仅本人房间，id升序 |

成员与角色来自认证后的Account，额外成员/角色字段422。A不能加入自己房间；第三人加入已满房间409。非A刷新404，满员A刷新409。32随机字节的tw_invite_凭证与session/recovery分开，只存SHA-256摘要，有效24小时，准确到期时刻失效。已加入B持同一邀请重试为幂等读取，即使后来过期也不重复写入。

PairService只依赖Repository Protocol。创建/刷新最多8次尝试；唯一冲突重生凭证，CAS冲突重读。刷新与加入竞争由Pair版本和数据库条件决定，未成功提交不会返回新凭证。两个适配器新增list_pairs_for_member，完整校验每条记录；没有数据库迁移或新索引。

PairError按INVITE_INVALID/PAIR_NOT_FOUND→404、PAIR_FULL/CONCURRENT_UPDATE→409、依赖/生成/时钟错误→503映射统一错误，前3项不可直接重试，后4项retryable=true。模块导入不连接数据库，每app独立PairService；pair_clock可注入，未设置时复用identity_clock（或使用UTC系统时钟），客户端不能设置时钟/重试策略。

复验示例（MONGO_URI设置为你当前可用的本地真Mongo；本轮隔离环境见报告）：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/application/test_pairs.py -q
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/api/test_pairs.py -q
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/api/test_pairs.py -k 'compete' -q
```

阅读security/credentials.py → ports/repository.py及两个list实现 → application/pairs.py → api/schemas/pairs.py与routers/pairs.py → 两个测试文件。竞争测试用独立真实Repository与应用，Barrier仅对齐真实写入，未用Mock替代数据库。QA-R01～R03取得证据；QA-R04游戏写入/NPC、T08、WS、前端和生产部署未实现，不能宣称完整游戏可玩。本轮完成后停止等待用户审查。


## 12. 剧本目录与存档生命周期（T08.1）

`GET /api/scripts`公开返回已发布ScriptMetadata数组；默认包内发布库为空，结果为`[]`。正式灯塔缺媒体/许可，不能自动把草稿当可售内容。

登录后使用`POST /api/saves`，严格输入`{pair_id,script_id,script_version}`，例如选择目录中的`lighthouse`/`1.0.0`。这要求服务器已由内容管理流程发布该精确版本；省略版本422、未发布/缺版404。服务端验证Pair成员并通过纯规则生成初始状态，客户端不能提交state/role。重复同版本返回同一档；不同版本409且不升级。

`GET /api/saves`直接返回本人可见摘要数组，可选`?pair_id=...`；`GET /api/saves/{id}`返回PlayerSnapshot加id/pair_id，按认证身份推导A/B。两人共用Save，但各自设备、观察、已发现线索与合法分享由project_save过滤，完整state不进入响应。外人或缺档404，四接口均no-store。

SaveService仅依赖Repository和PublicationStore。应用工厂可显式注入publication_store，默认在lifespan打开包内发布库并保持资源生命周期；save_clock可注入且默认复用identity_clock/UTC系统时间。Repository只增加list_saves_for_pair；唯一建档复用既有数据库约束，没有新增命令CAS/回执逻辑。

阅读顺序：application/saves.py的_role/create_save/_snapshot → api/schemas/saves.py与routers/saves.py → 两仓储的list_saves_for_pair → tests/api/test_saves.py中的CreationBarrier和关闭重开测试。完整命令、真实Mongo及历史失败见[报告](../docs/reports/saves-lifecycle.md)。

```powershell
# 在本工作树运行；Mongo用自己的可用本地URI
$env:MONGO_URI='mongodb://127.0.0.1:27017/?directConnection=true'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/application/test_saves.py backend/tests/api/test_saves.py -q
# 只观察SQLite的新API流程
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/api/test_saves.py -k 'sqlite and create_read_list' -q
```

测试使用正式灯塔JSON的临时发布副本和明确标记的测试PNG/WAV，未提供正式素材、独立TCP地址或完整可玩前端。游戏命令、幂等回执、操作同步、WS、受保护媒体、AI均待后续。本环节结束后停止，等待用户审查。


## 13. 游戏命令与本人回执（T08.2）

`POST /api/saves/{id}/commands`接受`{request_id,expected_version,kind,args}`。例如A在v0提交`inspect {target:maintenance_log}`，B读取v1再提交`inspect {target:sea_chart}`。服务从Bearer及Pair推导角色，客户端不能传role/account_id/state/completed；所有响应no-store。

成功返回`{receipt:{request_id,status:accepted,accepted_version,duplicate},save:个人快照}`。幂等完整范围为save_id+actor_id+request_id；同账号跨存档可独立复用UUID。同一存档内同请求重试保留原save_id及整个原载荷，即使B已推进世界，仍返回原接受版本和当前A投影。同一存档同actor换原版本、kind或args的同ID请求409 REQUEST_ID_REUSED。`GET /api/saves/{id}/receipts/{request_id}`只查询该存档当前actor；没有返回`{accepted:false}`，有则只返回accepted/request_id/accepted_version。外人404，不泄露伙伴回执。

调用链：严格GameCommand → 认证/Pair授权 → 同聚合查询回执与指纹 → 版本/容量/满员 → 精确发布剧本/纯规则 → 新状态与公共历史/回执整档CAS → 个人快照。CAS失败只重读确认同请求或409 VERSION_CONFLICT，不自动把业务动作重放到新版本。512条完整保留，旧请求/读档可用，新命令409 SAVE_COMMAND_LIMIT。未满员422 PAIR_NOT_READY；规则拒绝422，存储故障503。

读取application/commands.py的规范指纹、application/saves.py的submit_command/_duplicate，再看routers/saves.py和tests/api/test_commands.py的真实并发、两结局、512上限与应用重开测试。仓储原CAS/表/索引未改，没有新增依赖或模型调用。

```powershell
# 位于本工作树；需要真实本地Mongo的用例读取MONGO_URI
$env:MONGO_URI='mongodb://127.0.0.1:27017/?directConnection=true'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/api/test_commands.py -k 'full_lighthouse and sqlite' -q
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/application/test_commands.py backend/tests/api/test_commands.py -q
```

测试工厂自动创建并封存临时内容副本，不发布到正式包。生产默认发布目录仍为空，不能把这些测试PNG/WAV当正式素材。原契约辅助已适配精确版本，业务断言不改；后续星轨/WS/NPC失败保留。完整证据和手动调用顺序见[报告](../docs/reports/commands-receipts.md)。以上是T08.2交付记录；用户随后单独授权的T08.3见下一节。

## 14. 受保护媒体读取（T08.3）

`GET /api/saves/{save_id}/media/{asset_id}`带当前身份Bearer。current_identity验证会话；SaveService.read_media验证Pair成员并推导a/b、加载绑定的精确发布版本，调用project_save后只接受当前presentation.background或cues[].assets中的ID，再调用PublicationStore.read_media核验路径/链接/哈希并读字节。素材条件与cue条件统一由投影判定，public也不能越过场景/条件。

成功返回二进制200、服务端MIME白名单、Cache-Control: no-store与X-Content-Type-Options: nosniff。MIME/文件头筛查不是完整媒体解码器；当前支持Schema既有的PNG/JPEG/WebP、MP3/OGG/WAV/M4A。未知与不可见素材均404 MEDIA_NOT_FOUND，外人/缺档404 SAVE_NOT_FOUND，缺绑定版本404 SCRIPT_NOT_FOUND，资源损坏/缺文件/格式不符503 CONTENT_UNAVAILABLE；其他认证和依赖错误沿用现有统一结构。

Range/条件头本轮忽略，仍逐次鉴权并完整200，无206、304、静态重定向或缓存。读取不会新增回执或修改状态。正式发布库保持空，不提供独立演示地址；前端播放、缓存/Blob清理、手机体验与正式资源许可尚未实现/验证。

在backend目录执行以下测试，以临时真实封存PNG/WAV观察双身份授权；无需先发布正式灯塔，也不能用测试素材填补正式内容：

```powershell
$env:MONGO_URI='mongodb://127.0.0.1:27017'
.venv/Scripts/python.exe -m pytest tests/api/test_media.py tests/application/test_media.py -q -p no:cacheprovider --basetemp=work/media-learning
```

`--basetemp`每轮选用新目录。建议在test_http_commands_change_asset_and_cue_visibility_then_scene设断点，观察A/B凭证请求同一个beam_90如何随HTTP操作得到404→200→404。测试中的完整SaveRecord前后相等验证只读。[报告](../docs/reports/protected-media.md)列出结果、失败基线和复现命令；只完成T08.3后停止，不自动开始T09或T10。

## 15. 星轨内容与纯规则（T09.1）

`content/scripts/starline/1.0.0.json`定义全新四场景、两角色设备与条件链。`domain/engine.py`显式注册灯塔和星轨，仍使用同一apply_command入口；`mechanics/starline.py`仅增加功率预算/错误轨道检查、各自观察及状态不变量。条件、参数、有限效果、投票及版本递增继续复用原有引擎/common，没有第二份API或引擎。

例如B提交engine=true、sonar=true时成本为6，先抛POWER_BUDGET_EXCEEDED，三个设备、完整GameState及版本都不变；有效方案为声呐/灯4单位，扫描和装轨后再切换到引擎/灯4单位。A不经B扫描不能猜装bridge_2，B不经A选轨不能接车，双方同票才结束。

```powershell
.venv/Scripts/python.exe -m pytest tests/domain/test_starline.py tests/content/test_starline_content.py -q
```

无需数据库或AI即可观察纯规则。建议读正式JSON → engine._MECHANICS → starline.check_action → common.apply_effect/settle_votes → test_starline.py的TRACE及accept/reject。星轨25项媒体仅有明确“待制作、待核验、禁止生产发布”的声明；正式发布库为空，默认HTTP仍不能创建星轨正式存档。T09.1的历史结果见[领域报告](../docs/reports/starline-engine.md)；T09.2只在临时合法测试发布库验证HTTP与跨档，不代表正式发布、播放或手机体验完成。

## 16. 双剧本存档隔离与HTTP集成（T09.2）

复用既有路由、SaveService和两个仓储，测试工厂分别封存真实灯塔/星轨1.0.0，PNG/WAV、哈希与审核明确为test-only。测试通过注册/邀请、灯塔部分推进、星轨两种结局、回到灯塔、关闭应用与仓储后重开、恢复身份来检查完整聚合。真实封存2.0.0测试版本验证旧内容、规则和媒体仍按1.0.0读取，不存在的原版本不回退。没有实现版本迁移。

```powershell
$env:MONGO_URI='mongodb://127.0.0.1:27017'
.venv/Scripts/python.exe -m pytest tests/api/test_save_isolation.py -q -p no:cacheprovider --basetemp=work/t092-learning
.venv/Scripts/python.exe -m pytest tests/domain/test_recap.py tests/domain/test_projection.py -q -p no:cacheprovider --basetemp=work/t092-learning-domain
```

`--basetemp`选新目录。先读tests/save_support.py，再读test_save_isolation.py的完整流程、recap.py的四个星轨里程碑、starline.observations的发现门槛。DialogueTurn仅验证仓储内各存档/角色的记录归属及重开，真实私聊HTTP/NPC未实现。完整命令、双适配器结果、历史失败对比与恢复边界见[本轮报告](../docs/reports/starline-save-isolation.md)。本轮交付后停止等待审查，不自动开始T10。


## 17. 开发专用HTTP启动器（T10.2）

新增 `src/twoworlds/dev.py`。导入没有模块级app、数据库连接或自动启动；显式调用create_dev_app后才创建Repository，既有应用lifespan负责关闭。唯一新增依赖是dev组的精确Uvicorn0.54.0及其click8.5.1，已有依赖版本未升级。它是[开发ASGI服务器](https://uvicorn.dev/settings/)，不是生产部署方案。

先显式选择本地演示SQLite，在工作树backend目录启动：

```powershell
cd F:/two-worlds-agent-game/work/pr-t01-1-schema/backend
uv sync --locked --group dev
New-Item -ItemType Directory -Path work -Force
$env:TWOWORLDS_STORAGE_BACKEND='sqlite'
$env:TWOWORLDS_SQLITE_PATH='work/dev.sqlite3'
$env:TWOWORLDS_ALLOWED_ORIGINS='http://127.0.0.1:5186'
$env:TWOWORLDS_EMAIL_MODE='console'
$env:TWOWORLDS_DEV_PORT='8016'
.venv/Scripts/python.exe -m twoworlds.dev
```

启动后仅监听127.0.0.1:8016。DEV_PORT可省略，默认8000；未开放自定义host、0.0.0.0、代理IP信任或WebSocket。关闭访问日志和普通服务器异常日志，启动失败只输出固定安全提示，不能把隐藏异常误认为启动成功。用浏览器/HTTP请求GET /api/scripts检查，正式库当前应返回[]。缺配置或数据库故障不会自动切换SQLite/内存。

T06.3.2起邮件模式必须显式选择：`TWOWORLDS_EMAIL_MODE=console`只用于本地开发，把验证码打印到开发控制台；`smtp`需要`SMTP_HOST/SMTP_PORT/SMTP_USERNAME/SMTP_PASSWORD/SMTP_FROM`环境变量，缺失即启动失败。`TWOWORLDS_VERIFICATION_SECRET`可注入持久验证码密钥；省略时开发入口生成一次性临时密钥，重启后未使用的验证码作废。生产HTTPS设`TWOWORLDS_COOKIE_SECURE=1`给会话Cookie加Secure。

真实Mongo开发需另选适当的本地数据库，URI只通过当前进程环境注入，不进入源码/日志/Git：

```powershell
$env:TWOWORLDS_STORAGE_BACKEND='mongo'
# 在本机安全设置 MONGO_URI，此处不提交真实连接凭证。
$env:MONGO_DATABASE='twoworlds_dev'
$env:TWOWORLDS_ALLOWED_ORIGINS='http://127.0.0.1:5186'
$env:TWOWORLDS_EMAIL_MODE='console'
$env:TWOWORLDS_DEV_PORT='8016'
.venv/Scripts/python.exe -m twoworlds.dev
```

必须同时提供MONGO_URI和MONGO_DATABASE，SQLite路径不能作为Mongo失败回退。只配置精确HTTP/HTTPS Origin，不用通配符；T06.3.2起对精确白名单Origin启用`Access-Control-Allow-Credentials: true`以携带会话Cookie。前端设置公开VITE_API_BASE_URL并启动5186，见[前端README](../frontend/README.md)。以上python模块启动方式已由独立进程TCP测试分别验证SQLite/Mongo，浏览器流程亦通过同一工厂真实连接；本轮临时服务验收后已关闭。

正式发布目录不变，空目录是预期；仅测试代码可显式向工厂注入临时PublicationStore，CLI不接受草稿或自动发布参数。后端PairService、SaveService、身份、Repository与规则语义未变，未新增业务接口。

```powershell
# 先由本机环境提供 MONGO_URI；Mongo用例会创建并清理随机临时库。
.venv/Scripts/python.exe -m pytest tests/api/test_dev_launcher.py -q
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/python.exe -m ruff format --check src tests
uv lock --check --offline
```

专项16通过（包括两个真实CLI/TCP子进程）；完整回归、正式空目录与test-only书架、学习顺序见[T10.2报告](../docs/reports/t10-2-identity-room-library.md)。没有声称正式发布、生产部署、WS、游戏场景或真机验收完成。

## 18. 邮箱账号认证（T06.3.2，取代第9/10节的恢复密钥身份）

2026-11-18 用户决定：移除匿名身份与恢复密钥，首版只做邮箱+密码。`POST /api/sessions/recover`、恢复密钥生成/摘要与Bearer认证已删除，不保留兼容分支；旧匿名数据不迁移，也不在启动时静默删库。

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| POST | /api/verification-codes | {email,purpose:register/reset} → 恒202 `{status:"accepted"}`；发送失败也202，不揭示邮箱是否注册 |
| POST | /api/accounts | {email,code,password,display_name} → 200 account+session，Set-Cookie；409只在有效验证码之后 |
| POST | /api/sessions | {email,password} → 200 account+session；失败统一401 INVALID_CREDENTIALS |
| POST | /api/password-resets | {email,code,new_password} → 204，撤销该账号全部会话并清Cookie |
| DELETE | /api/sessions/current | 撤销当前会话、清Cookie，204 |
| GET | /api/me | 当前账号概要与当前会话expires_at |

安全要点：密码10–128字符，Argon2id（m=64MiB,t=3,p=4）哈希，登录成功且参数落后时CAS内升级；未知邮箱登录做dummy_verify均衡时序。验证码6位数字、10分钟、单次使用、最多5次尝试，只存HMAC-SHA256摘要（密钥经`verification_secret`注入，常量时间比较），重发作废旧码，register/reset用途隔离。会话token 32字节随机、只存SHA-256摘要，7天、每账号最多5个；Cookie `tw_session` HttpOnly/SameSite=Lax/Path=/Max-Age=604800，生产加Secure，不设Domain。所有状态变更请求在最外层中间件校验精确Origin白名单（缺失/重复/不匹配403 CSRF_REJECTED），先于正文限制与认证；CORS只对精确Origin开allow-credentials。

限频改为数据库共享原子计数器（`application/rate_limit.py` + 两仓储的rate_limits集合/表），多应用实例共用同一预算，不用进程内存方案：验证码按邮箱1/60秒+5/小时、按IP 10/小时；登录按IP+邮箱5/分钟+20/小时，另加按IP整体30/分钟+300/小时（防止换邮箱反复触发Argon2id）；429带Retry-After。固定窗口、容量10000键fail-closed、到期清理；peer IP只读ASGI scope，不信任X-Forwarded-For。FastAPI先做Schema校验再进路由，因此无效正文不消耗邮箱键预算（有专门测试固定此顺序）。

邮件适配器必须显式注入：`security/mailer.py`的console（仅开发，stdout打印）与smtp（全部配置来自环境变量，强制TLS与超时，只抛净化的EmailSendError）；`build_email_sender`要求`TWOWORLDS_EMAIL_MODE=console|smtp`，无默认回退。T06.3.2审查修复起，投递在进程内后台执行器中运行：`POST /api/verification-codes` 恒202且不等SMTP，reset未知邮箱同样落库但永不投递，发送失败按本次发行`issue_id`条件作废、不误伤重发后的新码；后台任务不持久化，进程退出会丢失未完成发送，生产需持久队列。

阅读顺序：`domain/persistence.py`（AccountRecord/VerificationCodeRecord/RateLimitRecord）→ `security/passwords.py`、`security/credentials.py` → `application/verification.py`、`application/rate_limit.py`、`application/identity.py` → `api/cookies.py`、`api/auth.py`、`api/limits.py`、`api/routers/{verification,accounts,sessions,password_resets}.py` → `api/app.py`的IdentitySafety中间件 → `tests/identity_support.py`与各测试。

```powershell
# 在backend目录；Mongo用例需要真实本地Mongo
$env:MONGO_URI='mongodb://127.0.0.1:27017/?directConnection=true'
.venv/Scripts/python.exe -m pytest tests/application/test_identity.py tests/application/test_verification.py tests/application/test_rate_limit.py -q -p no:cacheprovider --basetemp=work/t0632-app
.venv/Scripts/python.exe -m pytest tests/api/test_identity.py tests/api/test_rate_limit.py tests/api/test_request_limits.py tests/api/test_dev_launcher.py tests/contracts/test_identity.py -q -p no:cacheprovider --basetemp=work/t0632-http
```

应用层身份56、验证码48、限频26项通过；HTTP身份/限频/正文83项、开发启动器19项、身份契约7项通过，均含真实Mongo参数组。完整回归：改动前3 failed/1199 passed，安全审查修复后3 failed/1327 passed（失败ID相同，均为既有WS/NPC用例）；后台投递、issue作废、登录IP上限、防枚举与未验证项见[T06.3.2报告](../docs/reports/t06-3-2-email-auth-backend.md)。前端登录页替换（T06.3.3）与浏览器产品验收（T06.3.4）未开始；WS仍只有设计契约。本轮完成后停止等待审查。
