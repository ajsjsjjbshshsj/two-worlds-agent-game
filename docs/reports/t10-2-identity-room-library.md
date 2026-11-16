# T10.2 · 身份生命周期、双人房间与剧本书架

## 开发计划与边界

基线为PR #24合并提交`650d1b3a5ef364842b9141670589317f474bf4a4`，PR #23亦已合并。用户本轮明确授权按顺序连续执行T10.2.1与T10.2.2；先通过身份安全测试，再开发房间/书架，两个功能提交、一个PR，完成后停止。不使用子代理。

- [x] T10.2.1：在`stores/identity.ts`分别跟踪read/write/remove/invalid；只清对应成功操作的瞬时错误，保留不可识别原数据和内存提醒。`Identity.vue`路由离开时明确确认，取消/后续导航失败不清密钥；卸载才清。先新增Store与真实Router测试，再执行原82测试、typecheck/build/format，形成第一个提交。
- [x] T10.2.2接口：保留`http.ts`路径白名单，单独允许`GET /api/saves`的`pair_id`参数。`types`逐字段解析目录/房间/存档概要，只从个人投影提取入口需要字段。`services/pairs.ts`、`library.ts`复用现有API；不改后端权限/并发规则。
- [x] T10.2.2状态：`stores/pairs.ts`只在内存持有邀请，启动先读fragment并立即replaceState清除；`stores/library.ts`按身份/房间隔离并用请求代次拒绝迟到响应。新档用目录精确版本，已有档继续原save_id，不升级或重新创建。401清会话并阻断私人页面。
- [x] 页面：身份页→房间列表/详情→书架→本人存档入口，受保护路由先验证身份；未确认新密钥不能自动加入。沿用夜蓝/雾蓝/暖金、中文衬线标题与系统正文，不新增字体/图片或动画。房间双席位与角色来自服务端，不冒称在线；空目录真实展示，无假卡片；存档页明确游戏交互将在T11接入。
- [x] 开发启动器：`backend/src/twoworlds/dev.py`显式环境选择sqlite或mongo，工厂生命周期关闭资源；Uvicorn只精确锁在dev组，默认127.0.0.1，明确Origin白名单、不自动降级、不输出敏感异常。正式发布库保持空。
- [x] 验证：原82测试保留；新增HTTP/Store/路由/页面测试，四项前端命令；开发启动器测试与后端回归；真实SQLite/Mongo TCP及双独立浏览器QA-U01/U02。书架非空数据仅来自隔离test-only发布库，不冒称正式上线或真机验证。
- 交付方式：同步两README、任务清单与交接，检查凭证/临时文件，两个功能提交推送同一新分支并创建PR，不合并、不开始T11。

技术取舍：继续用既有Pinia与Vue Router，不引入新的状态/UI框架；邀请不持久化、不进入query/path。SPA确认使用浏览器明确确认，只用于离开实际显示一次性密钥的页面；beforeunload继续保护刷新/关闭，两类事件各自负责，不在路由guard中提前清密钥。正式目录为空是正常状态，临时测试发布内容不进入生产目录。

## 验证记录

以下区分本轮真实结果、历史结果与未验证部分；计划勾选只依据本轮实测。

### T10.2.1 实测

新增6项存储、4项真实Vue Router测试，原82用例保留；首次红测6失败/2通过（另一次沙箱EPERM未执行测试，不作为业务失败）。实现后92通过、0失败/跳过。typecheck、build、format:check均退出0；构建39模块、JS119.54kB/gzip46.58kB。取消push/back、确认后卸载、后续guard取消仍保留密钥均覆盖。invalid警告保守保留到新页面重新检查，不因无关成功清除；不能识别的同ID原记录不覆盖/删除。

## 文件与调用关系

| 文件 | 职责 |
| --- | --- |
| frontend/src/stores/identity.ts、views/Identity.vue | 四类告警、密钥SPA离开保护，既有多身份提醒/会话分离；成功后连接房间入口 |
| frontend/src/router/index.ts、main.ts | 显式Router工厂、保护私人路由；Vue Router读取地址前先提取/清理邀请fragment |
| frontend/src/types/resources.ts | 严格验证公开房间/元数据/存档摘要字段，从既有个人投影仅提取入口需要字段；不保留完整规则或私人游戏数据 |
| frontend/src/services/http.ts | 原路径白名单不变；独立query选项仅允许GET /api/saves的合法pair_id；固定本地错误文案 |
| frontend/src/services/pairs.ts、library.ts | 现有八接口的类型化适配，Bearer头/no-store/omit，不直接操作数据库 |
| frontend/src/stores/pairs.ts | 房间列表、创建/刷新/确认加入、邀请内存生命周期与认证切换隔离；服务端确认满员后清除无用邀请 |
| frontend/src/stores/library.ts | 同房间剧本与存档关联、目录最新元数据、旧档精确版本、迟到响应/页面切换隔离 |
| frontend/src/views/Pairs.vue、PairRoom.vue、Library.vue、SaveEntry.vue | 房间操作、成员状态、书架、当前角色进度入口；不包含T11的游戏操作 |
| frontend/src/components/SpaceShell.vue、InvitePanel.vue、styles/main.css | 认证空间外壳、邀请分享与复制/手动备用、沿用夜蓝/雾蓝/暖金响应式样式 |
| frontend/tests/storage-warnings.spec.ts、route-leave.spec.ts | T10.2.1新增10项，实际Vue Router而不是模拟返回导航成功 |
| frontend/tests/resources-http.spec.ts、pairs-library.spec.ts、rooms-pages.spec.ts、resource-fixtures.ts | T10.2.2新增33项，固定HTTP响应桩、Store/Router/页面边界；不冒称真HTTP |
| backend/src/twoworlds/dev.py、pyproject.toml、uv.lock | 显式开发工厂与回环监听、精确dev依赖Uvicorn0.54.0，只新增click8.5.1，原版本均保留 |
| backend/tests/api/test_dev_launcher.py | 16项工厂/配置/真实SQLite/Mongo/独立CLI TCP/敏感日志检查 |
| README、两端README、任务清单、交接、本报告 | 本轮现状、复现、测试和下一学习检查点 |

后端api/app.py、所有Router/PairService/SaveService/Repository/领域规则和正式发布目录没有修改。前端package.json/package-lock以及原82测试文件/fixture亦完全未改。types/api.ts的身份契约沿用，只新增独立公开资源类型文件。

具体例子：A创建房间→现有PairService绑定A、返回短暂邀请→pairs Store再GET本人列表→A复制fragment链接→B先在内存接收并清地址→创建/恢复身份（新建必须先确认密钥）→B明确点击加入→现有join_pair原子占位→各自手动刷新成员状态→书架同时GET目录与本房间存档。业务权限仍在后端；前端只负责安全调用与准确展示。

## 身份存储与路由保护

pendingStorageIssues为read/write/remove/invalid四个独立状态，pendingStorageWarning由全部当前问题合成。读/写/删成功只清各自类别，不能用一次成功读取清写入失败。invalid保持保守提醒，不因无关操作清除；新页面才重新检查。对同身份key中无法解析的原记录，新增/确认逻辑也不覆盖或删除。故障时内存提醒与密钥离开保护仍在，不能保证存储被禁用/清理后的重开。

onBeforeRouteLeave只决定是否允许导航，不清密钥。取消push/back或后续beforeResolve拒绝时页面仍持有原密钥和beforeunload。确认并实际卸载后才清页面局部密钥，Pending仍在。已确认保存后不再弹窗；SPA不会触发浏览器unload，未把两者叠加成重复确认。原生beforeunload的可信交互/移动系统终止限制仍适用。

旧计划曾写“Token也不进入Pinia”，与已合并身份Store及最新任务“Token保留sessionStorage、不迁移localStorage”不一致。本轮不重构身份架构，已纠正文档：Token保留既有内存/Pinia与sessionStorage；Recovery Key始终不进入Pinia/持久化。account_id仅标识，不是认证凭证。

## 邀请与书架边界

- 邀请使用独立tw_invite_命名空间。main在Router创建前captureInvite，立即replaceState去除fragment；Router也处理后续带邀请的导航。不会自动POST加入。刷新后内存邀请丢失，页面明确要求重开原链接，不在storage留“凭证备份”。
- token、恢复密钥、邀请不进入query/path/普通日志。邀请只在明确分享界面显示；刷新邀请先丢弃旧显示，结果不明提示先刷新列表/重新生成，不承诺网络取消会回滚服务器写入。
- 房间卡片来自GET /api/pairs的id/role/member_count，不伪造在线；A且1人时才提供邀请刷新。INVITE_INVALID、PAIR_FULL、PAIR_NOT_FOUND、DEPENDENCY_UNAVAILABLE、401均使用固定安全文案，不回显服务器正文。
- GET /api/scripts始终真实读取PublicationStore目录。正式registry仍只有格式登记，空数组正常展示，未硬编码两张卡片。多个已发布版本每剧本取数值最新的元数据并按ID排序，避免9.0.0大于10.0.0的字典序错误或重复卡片。
- GET /api/saves?pair_id=...摘要按pair_id+script_id关联；进度为未开始/进行中/已完成，显示本人角色、场景、进度版本、绑定内容和更新时间。目录新版本不等于存档升级；旧档只GET原save_id，验证响应仍是旧版。目录下架的已有存档仍提供原入口。
- 新建只在两人加入后POST真实content_version，返回版本也必须匹配。SaveEntry再次GET当前身份个人投影，仅保留id/pair/script/role/scene/version/completed；没有制作空白游戏页或假机关。
- 身份Token变化清私人列表/已发邀请/入口；按请求代次忽略迟到列表和读档响应；离开书架/入口重置上下文。没有实现WebSocket、后台轮询或游戏命令API前端。

## 开发HTTP启动器

create_dev_app不在导入时连接数据库；先验证显式存储模式、精确Origin及所需配置，再创建SQLiteRepository或MongoRepository，复用原create_app和关闭生命周期。没有Mongo缺失自动降级。仅测试可显式注入临时PublicationStore，CLI不接收自动发布或草稿参数。

main默认127.0.0.1:8000，TWOWORLDS_DEV_PORT可选，本轮浏览器用8016。Uvicorn关闭访问日志、普通异常日志、代理IP信任及WS；配置/连接异常只显示固定安全错误，不输出凭证或URI。仅dev组精确锁定[Uvicorn0.54.0](https://pypi.org/project/uvicorn/0.54.0/)，遵循[官方工厂/监听配置](https://uvicorn.dev/settings/)，不是生产部署方案。逐条环境变量与启动命令见[后端README](../../backend/README.md#17-开发专用http启动器t102)。

## 本轮实际验证

环境：Windows，Python3.12.4、Node20.19.0/npm10.8.2。既有Docker29.4.0、Mongo8.0.34服务，回环27017；URI仅进程环境提供。无新建/删除既有Mongo容器或卷，测试仅清各自随机临时库。uv增加开发依赖时重建本项目editable包，有跨磁盘hardlink降级copy提示，未影响安装；没有升级已有包。

| 实际命令 | 结果 | 退出码 |
| --- | --- | --- |
| frontend: npm.cmd run typecheck | TypeScript strict通过 | 0 |
| frontend: npm.cmd run test:unit | 125通过、0失败/跳过，9文件；最新3.83秒 | 0 |
| frontend: npm.cmd run build | 56模块；JS143.49kB/gzip53.95kB、CSS7.82kB/gzip2.35kB | 0 |
| frontend: npm.cmd run format:check | 全部匹配文件通过 | 0 |
| backend: uv add --dev uvicorn==0.54.0 | 锁26包，仅新增Uvicorn/click，本地editable重建 | 0 |
| backend: .venv/Scripts/python.exe -m pytest tests/api/test_dev_launcher.py -q -p no:cacheprovider --basetemp=work/t102-dev-final --junitxml=work/t102-dev-final.xml | 16通过、0失败/错误/跳过；5.20秒，含SQLite/Mongo独立真实TCP进程 | 0 |
| backend: .venv/Scripts/python.exe -m ruff check src tests | All checks passed | 0 |
| backend: .venv/Scripts/python.exe -m ruff format --check src tests | 92文件格式通过 | 0 |
| backend: uv lock --check --offline | 26包，锁一致 | 0 |
| 工作树: node backend/work/t102-browser.cjs sqlite | 三独立Edge上下文、真实SQLite TCP、QA-U01/测试QA-U02通过 | 0 |
| 工作树: node backend/work/t102-browser.cjs mongo | 三独立Edge上下文、真实Mongo TCP、QA-U01/测试QA-U02通过；随机库清理成功 | 0 |

原82项测试源码和fixture与650d1b3逐文件diff为空。最终125=原82+存储6+路由4+资源HTTP8+房间书架Store17+页面8。没有删除、skip、xfail或弱化历史断言；新书架测试最初按未排序fixture位置断言，目录按ID排序后改为按script_id查找，两项版本/完成断言保留，防止测试自身把位置当关联键。

红测证据：资源模块缺失时2个suite导入错误；页面工厂缺失时8项失败；目录多版本未聚合、创建响应内容版本不符、满员后邀请未清各有针对性失败，再修复并全量通过。最初沙箱Node realpath EPERM的运行没有进入测试，采用批准的项目环境重跑，不算业务红测。

### 完整后端回归与基线逐项比较

环境设置MONGO_URI为本机真库，TWOWORLDS_TEST_BACKEND=sqlite；运行：

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=work/t102-full --junitxml=work/t102-full.xml
```

单次结果1154项：**1151通过、3失败、0错误、0跳过**，964.08秒，退出1，保留1条既有anyio弃用警告。各组：API335通过、application115、content202、domain401、storage63、contracts35通过/3失败。默认共享仓储为SQLite；固定Mongo专项和双适配器API亦在全量中真实运行。

与T09.2的JUnit逐项比较：新增16项（全部本轮dev启动器）、移除0、新失败0；原3项失败不变。上轮4个Mongo初始化错误对应的测试本轮均通过，当前无环境错误；不改写历史1131通过/3失败/4错误的单次记录。

| 仍失败的tests/contracts/test_platform.py用例 | 实际原因 | 后续范围 |
| --- | --- | --- |
| test_websocket_uses_auth_frame_and_personal_projection_on_reconnect | WebSocketDisconnect | T12未实现 |
| test_outsider_websocket_never_receives_a_snapshot | WebSocketDisconnect | T12未实现 |
| test_demo_npc_is_private_and_cannot_change_game_facts | talk被规则拒绝UNKNOWN_ACTION | T14未实现 |

全量后串行设置TWOWORLDS_TEST_BACKEND=mongo，执行`.venv/Scripts/python.exe -m pytest tests/storage/test_repository_contract.py -q -p no:cacheprovider --basetemp=work/t102-mongo-contract --junitxml=work/t102-mongo-contract.xml`：**33通过**、0失败/错误/跳过，17.62秒，退出0。未使用Mock证明数据库事务/并发，也没有通过skip/xfail删除历史失败。原始日志/JUnit只在本地忽略目录，不上传。


## 真实浏览器验收方法

本地忽略目录backend/work/t102-browser.cjs和t102_qa_server.py启动自己的回环后端/Vite与Edge，三个独立browserContext各有独立session/localStorage；没有Fetch拦截或响应桩。A/B/C均通过实际页面创建身份，恢复密钥只在测试进程内存，不打印/写入测试结果。A复制真实fragment邀请；B打开后地址清理，确认保存新密钥后仍需点加入。双方手动刷新确认A/B和2人；C列表空，直接房间页不显示房间，查询该Pair存档及具体save均404。

先使用包内正式目录，实际书架为空并截图；再关闭本轮后端，显式注入隔离TEST-ONLY发布库启动。测试工厂封存灯塔1.0.0/2.0.0和星轨1.0.0，标题带[TEST-ONLY]，合成资源及审核全部来自原测试工厂，不进入正式登记。

通过真实API准备旧灯塔1.0.0档，再从页面继续该save_id，不能替换2.0.0；从页面新建星轨1.0.0。随后由QA脚本调用既有命令API完成12步真实星轨规则轨迹，为“已完成”卡片提供确定数据，**不是本轮实现游戏操作UI**。书架同时展示灯塔进行中、星轨已完成；B自己的入口为角色B；再建第二房间，两个故事均无档且等待搭档，不能复用前房进度。QA-U02非空部分明确test-only；正式内容发布仍是后续媒体/审核工作。

两适配器均实测1440px桌面scrollWidth1425、390px模拟scrollWidth390，无横向溢出；已查看SQLite窄屏截图。本轮浏览器/API/Vite均关闭，未停止既有5173服务或共享Mongo。SQLite临时文件、浏览器配置/截图/JSON与辅助脚本留忽略目录，不进入PR；Mongo随机测试库已清理。非跨浏览器、非iPhone/Android真机或完整游戏E2E。

## 未完成与学习检查点

正式目录仍为空，图片/音频/许可未准备或发布；没有T11机关/动画/音频、T12实时/WS、PWA、T14 NPC/AI、语音通话、支付或生产部署。未重跑npm审计，沿用历史开发4项moderate/运行0的记录，不宣称新审计通过。Storage不能保证被禁用/清理后的重开，不提供跨设备/跨标签页实时提醒同步。

阅读顺序：identity.pendingStorageIssues → Identity的onBeforeRouteLeave/onBeforeUnmount → resources白名单 → pairs/library服务与Store → Router/五个页面 → dev工厂与TCP测试 → 本轮43项前端测试。自试先按两端README启动，创建两身份并通过邀请进入同房，书架应为空；不要往正式目录复制测试内容。非空/完成/旧版学习可运行已有test_save_isolation.py或本轮响应桩测试，清楚区分测试内容。

Git：标准fetch出现连接重置/低速超时，改用GitHub API读取已审查Git对象（含签名payload），逐个SHA核对，重建的基线commit/tree与650d1b3完全一致；工作树干净后才从该基线建指定分支，未带入旧本地未审查历史。主目录不改。第一个功能提交为71477d7；第二提交记录房间/书架与完整交付文档，最终一个新PR、目标codex/bootstrap，由用户审查，不合并、不开始T11。

补充收尾核验：最终前端上再次串行运行SQLite/Mongo浏览器验收，两次均退出0并完成资源清理。diff/忽略规则检查通过，原82测试/fixture及后端业务代码无变化；前端构建JS未包含测试凭证、私人谜题标识。当前新文档链接/代码围栏有效；README/交接原有两处原始聊天链接指向本机忽略资料，在本工作树不存在，是既有历史限制，不伪称全仓库链接全部通过。
