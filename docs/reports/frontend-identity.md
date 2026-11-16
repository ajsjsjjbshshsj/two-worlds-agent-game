# T10.1 · Vue 工程与身份系统

2026-11-16。用户附件为本轮已授权规格；只执行T10.1，不使用子代理，不实现T10.2。

交付：[PR #23](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/23)，目标codex/bootstrap，打开、未合并。本环节结束，等待用户学习/审查。

## 基线与实施设计

PR #22已合并，重新fetch后origin/codex/bootstrap为a12a72d780dba81aea8ad515302d994d1f9546a3。从该提交在已有干净隔离工作树创建codex/t10-1-frontend-identity；主目录未提交的学习修改不触碰。

本轮采用原生fetch、Pinia setup store、单一路由身份页。与引入Axios或大型UI框架相比，此范围无需额外客户端/组件依赖；与把请求塞进页面相比，HTTP、身份生命周期和一次性密钥视图分别可测试。附件已明确接口、布局方向和边界，本轮依既定设计实施，不另设许可检查点。

视觉：深蓝#091725、面板#11283a、雾蓝#b8ccd7、暖金#e3bd7a、正文#eef3f5、次文字#a7bac7；中文衬线标题与系统无衬线正文、等宽密钥。本机字体回退，无外部字体或服务；双轨道静态线条对应两人世界，桌面两栏/窄屏单栏，控件至少44px，无动画、音频或假功能入口。

## 本轮实施计划

- [x] 工程配置、精确依赖与package-lock；核对Node/npm兼容。
- [x] HTTP/身份/页面行为红测，验证失败原因后实现。
- [x] http.ts：GET/POST/DELETE、Bearer、204、no-store/omit、超时与安全错误。
- [x] api.ts：按后端真实四接口定义类型及响应校验。
- [x] identity.ts：创建、恢复、启动验证、401清理、网络保留、登出与内存降级。
- [x] Identity.vue/路由/样式：一次性密钥确认、复制与手动备用、加载/错误/结果未知。
- [x] 类型检查、单元测试、构建、后端身份回归、可用环境下的页面检查。
- [x] 更新文档与交接，提交/上传独立PR，停止等待审查。

## 验证记录

初查Node20.19.0、npm10.8.2；PowerShell中的无扩展npm命中系统目录而无法运行，改用现有npm.cmd，不修改全局安装。现有registry为npmmirror，安装命令将显式使用官方registry，不改全局配置。后端只有显式注入Repository的create_app工厂，没有uvicorn依赖或独立TCP入口，真实前后端HTTP联调暂不可用；本轮不增加后端依赖/启动器、不自动降级SQLite。浏览器/前端单测的模拟响应不能当成真实联调。

## 工程与文件职责

| 文件 | 作用 |
| --- | --- |
| frontend/package.json、package-lock.json、tsconfig.json、vite.config.ts、.prettierrc.json、.gitattributes、.env.example | npm精确依赖、strict类型/构建/单测/格式、Windows检出保持LF、公开API地址配置；无代理硬编码 |
| frontend/index.html、src/main.ts、App.vue、router/index.ts | zh-CN、禁止Referrer、Vue/Pinia/Router装配，只有根路由身份页 |
| frontend/src/types/api.ts | 创建/恢复/me/登出契约；未知响应校验后仅提取白名单账号/期限/凭证 |
| frontend/src/services/http.ts | 原生fetch，GET/POST/DELETE、Bearer、204、安全错误、取响应与读正文超时，不自动重试 |
| frontend/src/stores/identity.ts | 账号/token/到期显示、初始化/忙碌/错误状态；401清理、网络保留、登出撤销确认 |
| frontend/src/views/Identity.vue、styles/main.css | 一次性密钥仅页面内存；表单、复制、确认、恢复/登出/错误与响应式排版 |
| frontend/tests/http.spec.ts、identity.spec.ts、components/Identity.spec.ts、fixtures.ts | HTTP13、Store14、页面13个行为测试及明确测试凭证 |
| frontend/README.md、README.md、docs/04、开发进度与交接、本报告 | 启动说明、验收边界、T10.1/10.2拆分与阅读顺序 |

没有修改任何后端源码、后端测试或Python依赖；`git diff origin/codex/bootstrap -- backend/src backend/tests backend/pyproject.toml backend/uv.lock`为空。无Pair/Library/Game页面、API服务器、自动SQLite回退、WS、PWA、音频、动画或AI。

## 具体数据流与安全边界

1. 页面提交显示名，按Python的Unicode码点长度做1–40校验 → Store.create → POST `/api/accounts`。服务端是身份权威，前端不接受account_id/player_id/role认领。
2. `createdIdentity()`检查返回字段，Store保存account、token和expires_at；审查补强后sessionStorage还保存非敏感pending状态（见下文）。恢复密钥返回到页面局部ref，不进入Pinia `$state`，不写storage/URL/日志。
3. 密钥优先展示，手动复制备用始终可用。复制按钮不承诺系统之外的备份；确认保存或卸载清除页面明文。恢复输入在请求结束后清除（包括错误）。
4. 页面刷新先从sessionStorage取token再GET `/api/me`，成功才置为已认证；本地过期日期不替代服务端认证判断。401清掉账号和token，断网/503保留未验证token并提供手动重试。
5. DELETE `/api/sessions/current`得到204才视为撤销成功。网络错误保留当前身份并明确提示撤销尚未确认；401清除已经无效的本地身份。不自动续期、重试或撤销其他设备。
6. Store串行化正在进行的身份操作，页面禁用重复提交。HTTP没有自动重试；创建超时/网络断开/无法解析成功响应/5xx显示“服务端可能已创建”，不承诺丢失密钥后能找回。
7. sessionStorage拒绝访问时仅内存保留会话，并提示刷新后可能需恢复，不用localStorage替代。sessionStorage仍可被同源脚本访问，不声称本轮完成XSS/生产安全部署。
8. HTTP明确no-store/omit、拒绝重定向、token仅Authorization。保留状态码、业务code与retryable；错误文案本地固定，原始异常/正文不回显或记录。401/422/429/503各有可理解提示，结果格式错误独立分类。

## 精确版本与依赖校验

实际安装并锁定：Vue3.5.45、Vue Router4.6.5、Pinia3.0.4；Vite7.3.8、plugin-vue6.0.11、TypeScript5.9.3、vue-tsc3.3.14、Vitest4.1.12、Vue Test Utils2.4.6、jsdom26.1.0、Node类型22.20.5、Prettier3.6.2。Prettier仅负责源码学习可读性，非UI/运行依赖。package-lock所有下载指向显式官方registry，未改用户全局镜像源。

安装初期Vue Test Utils2.6.0经js-beautify2/nopt10/abbrev5要求高于现有Node版本，npm报告EBADENGINE。检查依赖来源后改为兼容的2.4.6，并通过`npm ci --engine-strict`验证，未强装不兼容树或升级全局Node。保留whatwg-encoding/glob开发依赖弃用提示。[Vite7 Node要求](https://v7.vite.dev/guide/migration)、[Vitest4要求](https://v4.vitest.dev/guide/migration.html)、[Pinia setup store](https://pinia.vuejs.org/core-concepts.html)作版本/分层核对依据，最终以实际安装和执行为准。

附加官方npm审计：`npm.cmd audit --registry=https://registry.npmjs.org --json`返回4项moderate（editorconfig、glob、js-beautify、minimatch，均开发依赖）；`--omit=dev`为0。初次审计因用户镜像未实现安全端点而404，已显式改用官方端点，不计为安全通过。未执行强制跨主版本覆盖以消除审计输出。开发依赖问题是已知限制，不宣称全树无漏洞。

## 初始交付实际执行结果（审查后的当前结果见下节）

所有前端命令在frontend目录执行；下表退出码为该项结果，不用后续成功命令遮盖前面失败。

| 实际命令 | 结果 | 退出码 |
| --- | --- | --- |
| `node --version` / `npm.cmd --version` | v20.19.0 / 10.8.2 | 0 |
| `npm.cmd install --save-exact vue@3 vue-router@4 pinia@3 --registry=https://registry.npmjs.org --no-fund --no-audit` | 安装运行依赖，之后精确版本入锁 | 0 |
| dev依赖安装后，`npm.cmd install --save-dev --save-exact @vue/test-utils@2.4.6 --registry=https://registry.npmjs.org --engine-strict --no-fund --no-audit` | 排除EBADENGINE不兼容版本 | 0 |
| `npm.cmd install --engine-strict --registry=https://registry.npmjs.org --no-fund --no-audit` | up to date，无engine警告 | 0 |
| `npm.cmd ci --engine-strict --registry=https://registry.npmjs.org --no-fund --no-audit` | 干净安装185包，锁可复现 | 0 |
| `npm.cmd run typecheck` | vue-tsc严格检查通过 | 0 |
| `npm.cmd run test:unit` | **40通过、0失败/跳过**，3文件（13/14/13）；干净安装后1.38秒 | 0 |
| `npm.cmd run build` | 39模块构建成功，JS112.82kB/gzip44.26kB，CSS4.84kB；非部署 | 0 |
| `npm.cmd run format:check` | 全部匹配源文件格式通过 | 0 |
| backend：`.venv/Scripts/python.exe -m pytest tests/api/test_identity.py -q -p no:cacheprovider --basetemp=work/t101-identity --junitxml=work/t101-identity.xml` | **30通过、0失败/错误/跳过**，2.40秒，含真实Mongo；1条原anyio弃用警告 | 0 |
| `npm.cmd audit --registry=https://registry.npmjs.org --json` | 开发依赖4项moderate，运行依赖0；详见上文 | 1 |
| `npm.cmd audit --omit=dev --registry=https://registry.npmjs.org --json` | 运行依赖0项 | 0 |

红测顺序：先HTTP12失败（请求未实现），Store9失败/2已有空状态通过，页面10失败（表单不存在）；实现后33通过。补强慢正文超时、401登出、503保留、刷新不重显密钥、40码点名称、超长恢复输入及重叠请求后40通过。初次类型检查发现测试catch结果unknown未收窄，修正为instanceof后严格检查通过。未删除/跳过/弱化测试。

本轮只跑后端要求的身份专项，不重跑T09.2全量或宣称后端全绿。历史1138项1131通过/3后续失败/4环境错误及四项复验通过保留为历史证据，不是本轮结果。

## 浏览器检查与联调限制

真实启动 `npm.cmd run dev -- --port 5173 --strictPort`，仅127.0.0.1。用本机Edge的CDP设置1440×1000及390×1000视口：innerWidth分别1440/390，scrollWidth分别1440/375，无横向溢出；当前创建页三个按钮各48px高、宽均大于44px。已查看两张实际截图。最初直接Edge window-size得到的窄屏截图受窗口宽度约束，未把它当390px证据，改用CDP真实覆盖后核验。屏幕截图和临时浏览器配置在忽略的backend/work，不进入PR。

只实测本机Edge与初始创建页布局；复制分支/错误/身份完整交互由Vue Test Utils验证，不冒称跨浏览器E2E、iPhone/Android真机、所有状态布局或真实账号注册联调。Vite预览检查后已停止。后端无独立TCP入口，不能运行不存在的uvicorn模块入口；本轮不修改后端来突破边界。没有正式上线地址。

## 学习阅读与下一环节

先看`types/api.ts`对照后端四响应，再看`http.ts`的request/error、`identity.ts`的create/initialize/logout、`Identity.vue`的一次性密钥分支，最后看对应测试。具体运行步骤见[前端README](../../frontend/README.md)。例如创建成功后账号和token进Store，密钥只交给页面；点击保存确认后清密钥，刷新再通过me恢复身份而非重新展示密钥。

未完成：真实HTTP联调、独立后端启动/部署、房间/邀请/书架/游戏页、WS/PWA/AI/音频/动画、生产安全与真机验收。下一任务T10.2只介绍房间与书架，本轮交付后立即停止，等待用户审查。

## Git交付核验

初始fetch成功；收尾时CLI默认路径连接重置，两条命令级IPv4路径分别重置/超时，未关闭TLS验证或改全局DNS/Git。通过GitHub连接器再次核实远端基线仍a12a72d，再上传本地已提交的25个文件，逐个blob SHA核对；生成的实现tree与本地完全相同：`eed43b5045513e83abf5efae18aa9532e156e893`。

本地实现提交`64bd98aa508800b414f450e585ce5af797a1ae3f`，远端实现提交`e10be1b4e873051994394a4d8424f776887c7172`；父基线/消息/tree一致，提交元数据不同。创建codex/t10-1-frontend-identity及PR #23，收尾文档继续更新同一PR，逐文件/tree核验。未修改已合并PR、未推送bootstrap、未force/合并/启用自动合并。后续聊天网络恢复后先fetch核对远端，不能直接推送本地不同元数据的提交历史。

## PR #23审查修复 · 未确认密钥与安全动态路径

本轮只处理用户指定的两点。远端PR仍打开，HEAD为d566cf830ce8e7c29b44d9a25c8879e84173a728；本地元数据不同但起点完整tree同为1b5c9fc976db81be57812ef964f30568abec8870，工作树干净。沿原分支追加修复，不覆盖主目录用户工作、不创建新PR、不用子代理。

### Pending与离开提醒

Store新增`recoveryKeyPending`与固定标记`twoworlds.recovery.pending=1`。先设置状态再接受创建返回的token；标记不含任何密钥、token、账号ID。页面仍是唯一保存恢复密钥的状态容器，sessionStorage拒绝写入时内存pending与原密钥、离开保护继续生效。

`watch(oneTimeKey, ..., {flush:'sync'})`只在密钥实际展示期间注册稳定的beforeunload处理器；`preventDefault()`与legacy returnValue请求原生确认。点击保存确认同时清pending与页面密钥、同步移除监听；卸载无条件移除监听并清页面密钥，**不**因此假装用户已经保存。刷新后的新页面读取pending，仍GET me验证会话，但以醒目警告区分“会话可用”和“恢复能力未确认”；绝不重新调用创建或伪造密钥，丢失密钥不可找回。没有密钥可丢的新页面不继续拦截离开。

成功恢复身份已经证明持有该次恢复密钥，清除pending；明确登出时清理此设备身份和pending，保留原有登出清空断言；网络登出失败不清理。启动me返回401仍保留未确认警告，不把失效会话当成正常身份。Storage拒绝读取/写入时只做内存降级，若强行刷新，浏览器存储不可用意味着无法承诺pending跨刷新保留。

原生弹窗由浏览器控制，需用户交互，移动端强制终止等路径不保证触发；不能自定义弹窗文案或承诺阻止所有关闭。[MDN beforeunload说明](https://developer.mozilla.org/en-US/docs/Web/API/Window/beforeunload_event)。该机制降低误操作风险，不等于持久化或备份密钥。

### Identifier路径

`http.request()`使用完整匹配的`/api/`前缀和逐段`[a-z][a-z0-9_]{0,63}`语法。允许数字/下划线动态资源段；拒绝点号、穿越、编码字符、query/fragment、空段、尾随斜杠、大写/非法首字符、超长段、反斜杠以及非API路径。额外比较匹配结果与原字符串，防止JavaScript `$`允许末尾换行的行为。校验发生在创建请求、fetch或任何网络访问之前，没有新增业务路由。

### 新增测试与实测

原40项保留，新增28项：HTTP22（5个安全路径/长度边界、17个非法路径）；Store1（pending读取与恢复清除）；页面5（创建/确认/离开、刷新丢失、卸载监听、storage不可用、刷新401仍警告）。原storage失败测试新增内存pending断言，没有降低任何断言。原登出2项一度因残留标记失败，修复明确登出清理逻辑后通过，未修改其“storage为空”的原断言。

| 实际命令（frontend目录） | 当前结果 | 退出码 |
| --- | --- | --- |
| `npm.cmd run test:unit`，新增红测后 | 10失败/55通过，复现两个缺陷 | 1 |
| `npm.cmd run typecheck` | strict通过 | 0 |
| `npm.cmd run test:unit`，修复及补强后 | **68通过、0失败/跳过**，HTTP35/Store15/页面18；1.32秒 | 0 |
| `npm.cmd run build` | 39模块；JS113.83kB/gzip44.64kB，CSS4.84kB | 0 |
| `npm.cmd run format:check` | 全部匹配文件通过 | 0 |
| 本机Edge CDP原生弹窗验证（本地忽略目录内脚本） | 离开/刷新均捕获beforeunload原生弹窗；取消离开保留密钥；确认后离开无弹窗；接受刷新后pending警告可见且创建请求数不增加 | 0 |

浏览器脚本第一次等待密钥超时，定位为目标按钮未滚入视口而未收到可信点击；修正脚本滚动后上述实测通过，未改业务来配合测试。该浏览器测试的API为明确响应桩，未增加后端接口或声称真实HTTP联调；非移动端/系统强制结束验收。预览/浏览器检查结束后关闭，本地辅助/日志不进入提交。

修改仅为三个前端源码、三份测试与相关报告/说明/进度文档。依赖锁、配置、后端源码/测试/依赖不变；不重跑或宣称后端全量通过。更新同一PR #23，不合并、不开始T10.2。
