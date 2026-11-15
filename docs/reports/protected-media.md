# T08.3 · 受保护媒体资源读取

2026-11-15。本轮只做媒体读取，不开发星轨、前端、播放器、WS、AI或正式素材。

## 基线与文件边界

已核实PR #19合并，基线为`e28cb0b620e79384a12026081459c38003186c0f`。在原有干净隔离工作树`F:\two-worlds-agent-game\work\pr-t01-1-schema`从最新origin/codex/bootstrap建立`codex/t08-3-protected-media`。主目录用户未提交的领域/投影/文档修改全部保留，未委派子代理。

- `backend/src/twoworlds/application/saves.py`：read_media编排授权和读取；新增稳定MEDIA_NOT_FOUND业务错误。
- `backend/src/twoworlds/application/media.py`：冻结MediaContent二进制结果；服务端元数据的MIME白名单和格式签名筛查，不依赖FastAPI或数据库。
- `backend/src/twoworlds/api/routers/saves.py`：新增GET路由，复用current_identity，返回二进制Response及安全头。
- `backend/src/twoworlds/api/errors.py`：MEDIA_NOT_FOUND映射404，沿用统一JSON错误。
- `backend/tests/api/test_media.py`：真实HTTP/发布快照、SQLite/Mongo与临时PNG/WAV、合法命令与故障注入。
- `backend/tests/application/test_media.py`：白名单、格式签名和不支持格式的边界。
- `backend/tests/save_support.py`：测试发布工厂可定制临时内容副本/媒体字节，不改变默认行为，不绕过发布校验。
- `.gitignore`：排除backend/work临时测试库、XML与生成资源；不上传真实数据库、凭证、缓存或测试素材。
- 同步backend/README及docs/03、04、05、07、交接；正式内容Schema、JSON、发布登记、规则和仓储均未修改。

## 请求、响应与调用关系

```http
GET /api/saves/{save_id}/media/{asset_id}
Authorization: Bearer <有效session token>
```

成功200，正文为真实媒体字节，不是JSON/Base64。固定响应头：Cache-Control: no-store、X-Content-Type-Options: nosniff；Content-Type由受信任发布元数据及格式签名决定，不采用客户端Content-Type。无Location、ETag、Last-Modified、静态地址或内部素材路径。

```text
current_identity（每次验证会话）
  → SaveService._authorized_save（读完整存档、验证Pair成员、推导a/b）
  → PublicationStore.load(save.script_id, save.script_version)
  → project_save(state, script, role, public_history)
  → 当前presentation.background + cues[].assets的asset_id集合
  → 白名单命中才调用PublicationStore.read_media
  → media_content（MIME白名单/格式签名）
  → Router二进制Response
```

没有独立的媒体权限规则。素材audience、scene_ids、conditions与cue自己的conditions全部由现有投影判断；public素材同样不能跳过当前场景/cue条件。猜中隐藏ID仍404，和未知ID完全相同；客户端提供的role/account_id不能更改服务端角色。

例如B初始无法读取beam_90。A查日志、B查航道图、A设90°/pulse、B设amber后可以读取；A改180°再次不可读，恢复90°后锁定进入repair又不可读。该轨迹全部经真实命令HTTP接口，未直接修改存档数据库。另以临时内容副本给public海风增加仅cue层的条件，证明只检查asset.audience/conditions会出错，而接口按投影正确拒绝。

## 文件、类型与缓存边界

只传入asset_id，不把客户端字符串拼成磁盘路径；PublicationStore按精确版本登记查资源。沿用canonical_relative/safe_path、符号链接/Windows Junction拒绝、32MiB单文件读取上限、发布包大小上限和实际字节SHA-256核验。损坏或缺失不回退草稿/最新版。哈希不是签名；发布登记和服务器文件系统管理权限仍是受信任边界。

| Schema格式 | 响应MIME |
| --- | --- |
| .png | image/png |
| .jpg / .jpeg | image/jpeg |
| .webp | image/webp |
| .mp3 | audio/mpeg |
| .ogg | audio/ogg |
| .wav | audio/wav |
| .m4a | audio/mp4 |

不扩展Schema为.mp4文件或新kind。额外的文件头检查用于拒绝明显错格式（如PNG声明却是HTML），**不是完整媒体解析器、恶意文件扫描器或可播放性证明**。PNG/WAV真实字节通过HTTP验证，其他格式仅验证MIME与签名映射，不虚报浏览器解码或设备体验。

Range、If-None-Match和If-Modified-Since本轮不触发206/304，鉴权通过后始终返回完整200。无论成功、认证失败、成员/素材拒绝还是内容故障，现有IdentitySafety/错误处理均返回no-store。没有新增日志输出或外部上传。

权限基于请求读取到的已提交状态；后续状态变化影响下一次请求，无法撤回已合法发给客户端的字节。本轮不实现前端Blob撤销、Service Worker缓存排除、带宽/并发优化、流式传输或断点续传。

| 情况 | HTTP / 错误码 |
| --- | --- |
| 未登录、无效/过期/撤销会话 | 401 UNAUTHENTICATED |
| 缺存档或非成员 | 404 SAVE_NOT_FOUND |
| 未知或当前投影不可见asset_id | 404 MEDIA_NOT_FOUND |
| 存档绑定发布版本缺失 | 404 SCRIPT_NOT_FOUND |
| 媒体缺失、损坏、路径链接或格式不符 | 503 CONTENT_UNAVAILABLE |
| 仓储不可用 | 503 DEPENDENCY_UNAVAILABLE |

业务错误统一`{error:{code,message,retryable}}`。带斜线等无法匹配路由的攻击路径由现有统一404 NOT_FOUND拒绝，也不返回媒体或磁盘信息。读取前后比较完整SaveRecord，覆盖GameState、版本、PublicHistory、DialogueTurn和所有CommandReceipt，未写入存档。

## 实测记录

下表为T08.3首次交付的历史实测；PR #20本次小范围审查修复的独立结果见文末，不把旧全量结果写成本轮重跑。

环境使用项目Python3.12.4、既有锁中的FastAPI/PyMongo等，无依赖变更。真实Mongo连接为`mongodb://127.0.0.1:27017`，既有twoworlds-mongo容器健康，仅本地绑定；测试使用现有随机数据库工厂隔离/清理，不操作其他容器或业务库。

先写HTTP测试：接口不存在时确认失败为404（期望200）。最初沙箱内Windows路径resolve导致PublicationStore初始化错误，是环境失败；获自动批准后在项目临时目录运行真实验证，未改变发布路径防护来迎合沙箱。uv离线检查也需沙箱外解释器缓存访问。

| 验证 | 实际结果 |
| --- | --- |
| 首轮真实媒体HTTP专项 | 60通过、0失败：SQLite30、Mongo30；208.21秒 |
| 格式白名单专项 | 15通过、0失败；不等同全格式解码测试 |
| 加强字节/日志与跨版本角色断言后复验 | 12通过、0失败（SQLite6、Mongo6），48项未选中；48.85秒 |
| 最终完整后端 | 988项：979通过、9后续失败、0错误、0跳过；736.62秒；1条既有anyio弃用警告 |
| 原命令专项（全量中执行） | API66 + application12 = 78通过、0失败，无回归 |
| 全部API / application（全量中执行） | 274 / 115通过，均0失败 |
| 全部领域 / 内容（全量中执行） | 308 / 191通过，均0失败 |
| 全部仓储（全量中执行） | 62通过、0失败；SQLite专项12、共享契约32、Mongo专项18 |
| Mongo共享仓储契约 | 32通过、0失败；15.01秒，真实随机数据库 |
| Ruff check / format | 通过；86个Python文件格式一致 |
| uv lock --check --offline | 通过，24包；锁文件未改 |

本地临时JUnit/日志位于backend/work/t083-*，全部忽略，不上传。最终回归包含新增媒体HTTP60项（SQLite30/Mongo30）与格式15项、原78项命令、SQLite/Mongo仓储、内容、投影/规则与身份。全量运行期间额外强化日志和新版角色断言，对这12项另以最新测试文件复验通过；生产代码未再改动。逐项比较旧work/pr19-review-all.xml的913个用例：新增75、移除0、新增失败0、消失失败0、错误0、跳过0。没有删除/skip/xfail或降低原断言。本地结果不等同GitHub Actions通过。

全量9个失败与上一阶段ID和原因一致，均在tests/contracts/test_platform.py；旧契约其余29项通过：

| 用例 | 归属 / 真实阻塞 |
| --- | --- |
| test_starline_has_a_distinct_cooperative_solution[rescue_detour] | T09，建星轨档404 SCRIPT_NOT_FOUND |
| test_starline_has_a_distinct_cooperative_solution[return_station] | T09，建星轨档404 SCRIPT_NOT_FOUND |
| test_invalid_role_or_prerequisite_changes_neither_projection[unscanned-rail] | T09，建星轨档404 SCRIPT_NOT_FOUND |
| test_invalid_role_or_prerequisite_changes_neither_projection[early-dispatch] | T09，建星轨档404 SCRIPT_NOT_FOUND |
| test_power_budget_rejects_the_entire_allocation | T09，建星轨档404 SCRIPT_NOT_FOUND |
| test_scripts_and_pairs_have_independent_saves_and_receipts | T09，建星轨档404 SCRIPT_NOT_FOUND |
| test_websocket_uses_auth_frame_and_personal_projection_on_reconnect | T12，握手WebSocketDisconnect |
| test_outsider_websocket_never_receives_a_snapshot | T12，握手WebSocketDisconnect |
| test_demo_npc_is_private_and_cannot_change_game_facts | T14，talk返回422 UNKNOWN_ACTION |

复现命令（PowerShell，在backend目录；为每次运行选用尚不存在的basetemp目录）：

```powershell
$env:MONGO_URI='mongodb://127.0.0.1:27017'
.venv/Scripts/python.exe -m pytest tests/api/test_media.py tests/application/test_media.py -q -p no:cacheprovider --basetemp=work/t083-local
$env:TWOWORLDS_TEST_BACKEND='mongo'
.venv/Scripts/python.exe -m pytest tests/storage/test_repository_contract.py -q -p no:cacheprovider --basetemp=work/t083-local-mongo
Remove-Item Env:TWOWORLDS_TEST_BACKEND
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=work/t083-local-all --junitxml=work/t083-local-all.xml
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/python.exe -m ruff format --check src tests
uv lock --check --offline
```

## 学习和自己验证

阅读顺序：SaveService.read_media → projection._presentation → PublicationStore.read_media/_record → application/media.py → routers/saves.py与tests/api/test_media.py。

先运行`test_http_commands_change_asset_and_cue_visibility_then_scene`，观察两身份HTTP请求：inspect maintenance_log / sea_chart → set_emitter 90/pulse → set_filter amber → B GET beam_90为200，而A GET同ID仍404 → 改180°，B再读也404。`test_visible_binary_headers_and_complete_save_unchanged`同时比较实际文件字节、安全头和完整数据库聚合。

可在pytest上述测试的get_media或granted处设置断点，分别查看a.headers/b.headers、save['id']和response；不要把明文凭证复制到报告、日志或Git。也可在自己明确已审核的本地发布库启动应用后，使用两个Bearer身份请求同一路径；**本轮未启动独立TCP服务，没有提供实际演示地址**。默认正式库为空，直接对默认应用建灯塔档会拒绝，不能跳过发布/许可检查。

## 未完成项与交付检查点

正式灯塔28项素材仍缺文件/许可，正式发布库保持为空。所有临时合成素材标注test-only并在pytest临时目录按真实审核/封存流程发布，未声称正式授权。QA-M03只有后端媒体授权/no-store部分具备证据；正式public构建产物/预载、Service Worker、前端播放、手机实际播放、完整QA-M03与QA-M07均未完成。

不执行T09星轨、T10前端、T11播放、T12WS或T14NPC。实现提交`e66741c9db26c61e17442bceaa9125254366986e`已推送codex/t08-3-protected-media，创建[PR #20](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/20)，目标codex/bootstrap；收尾交接提交更新同一PR。等待用户手动审查合并，不开启自动合并。当前环节已停止。

## PR #20审查修复 · 同一状态下的私密媒体交叉访问

基于原PR分支codex/t08-3-protected-media的fdd0a43；核实远端与本地一致、PR打开且未合并，干净隔离工作树内只改测试及报告/交接。主目录用户工作保留，不创建新PR、不进入T09。

原报告的学习说明虽然描述了“A读取beam_90被拒绝”，动态HTTP测试当时没有实际执行这个请求。该文字不能代替自动化证据，本次补齐真实断言：

1. 通过原HTTP命令将同一存档推进到90°/pulse/amber，记录完整SaveRecord。
2. B读取beam_90，200且正文与发布资源原始字节完全一致。
3. 立即让A用自己的Bearer请求**同一save_id、同一asset_id**，得到404 MEDIA_NOT_FOUND；两次请求之间没有命令、重新建档或数据库修改。
4. A的拒绝正文不含原始媒体字节，Content-Type为JSON、no-store；正文逐字节等于A在同一存档请求未知asset_id的错误，字段仍为code/message/retryable。
5. save_id与已记录聚合的id相等，完整SaveRecord前后相等，覆盖状态、版本、历史和回执。后续原有改角度/切场景的拒绝断言继续保留。

交叉访问审查还发现：原emitter_click/receiver_tone拒绝用例只在未解锁时检查，无法单独证明角色隔离。因此在既有成功读取参数化测试中补上B背景future_station和A音效emitter_click，并对A/B两幅背景、两条已解锁私有音效分别执行“所属角色200 → 搭档404 → 与同一搭档的未知ID错误字节相等”。音效先由所属角色通过HTTP inspect解锁，整个对照复用同一存档/状态。新增两个参数组合在双适配器下形成4项新用例；未删除或弱化旧断言。

其他阶段的受众/场景过滤已有test_projection.py的7个阶段和两结局测试，本次一并回归；不声称已经对28项素材穷举全部HTTP轨迹。未发现需要修改生产授权逻辑的问题，application、router、projection、PublicationStore和正式资源均未修改。

| 本次执行 | 真实结果 |
| --- | --- |
| 指定动态测试（SQLite / Mongo） | 各1项通过，共2通过、0失败、0错误、0跳过；18.61秒 |
| 完整媒体与角色投影回归 | 169通过、0失败、0错误、0跳过；222.61秒；1条既有anyio弃用警告 |
| 其中媒体HTTP | 64通过：SQLite32、真实Mongo32；较首次60项新增4项，无旧用例移除 |
| 其中格式 / 领域角色投影 | 15 / 90通过，均0失败 |
| Ruff check / format --check | 通过，86个Python文件格式一致 |

命令在backend目录执行，MONGO_URI为本地真实Mongo，测试继续使用pytest临时封存PNG/WAV，无Mock、无正式发布写入：

```powershell
$env:MONGO_URI='mongodb://127.0.0.1:27017'
.venv/Scripts/python.exe -m pytest tests/api/test_media.py -k http_commands_change_asset_and_cue_visibility_then_scene -q -p no:cacheprovider --basetemp=work/pr20-cross-role-target --junitxml=work/pr20-cross-role-target.xml
.venv/Scripts/python.exe -m pytest tests/api/test_media.py tests/application/test_media.py tests/domain/test_projection.py -q -p no:cacheprovider --basetemp=work/pr20-cross-role-media --junitxml=work/pr20-cross-role-media.xml
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/python.exe -m ruff format --check src tests
```

本轮没有重跑全量后端、仓储或内容套件，首次交付979通过/9后续失败保留为历史证据，不能称本轮全量通过。只更新原PR #20，完成后停止等待审查。
