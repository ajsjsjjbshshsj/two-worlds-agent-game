# T01.2.3 · 内容发布、公开目录与资源集成打包

2026-11-01。范围只含内容层，不实现T02、HTTP、投影、数据库、前端或AI。

## 设计与执行计划

PR #5已核实在2026-11-01合并；从最新远端`codex/bootstrap`的`3828658b414e0a49944a4e7c3f5e457ddef93ad3`建立`codex/t01-2-3-content-publication`，复用现有干净隔离工作树。主目录的个人设置、旧本地提交和未提交文件保留。

选择本地文件快照发布，无额外服务器/运行依赖：

- 草稿仍在`content/scripts/<id>/<version>.json`，预期媒体位于`content/assets/<MediaAsset.path>`。
- 已发布库在`content/published`，`registry.json`声明登记格式；每个`<id>/<version>/release.json`为明确版本登记，绑定原始JSON和每个实际媒体的SHA256及人工审核记录。
- 独立版本目录包含`scripts/<id>/<version>.json`、`assets/<MediaAsset.path>`和登记。先在同文件系统的隐藏暂存目录完成校验、复制和刷盘；持有跨进程独占版本锁后，原子重命名整个目录登记。正常失败清除暂存/锁，不出现半份已登记内容。
- 同版本存在即拒绝；新版本另建目录。加载与目录读取均重新核验所有哈希；哈希不是签名，受信任的登记与文件系统管理员仍是边界。
- 媒体审查绑定实际文件哈希、审核人和许可证据；非空source/license文本不等于已授权。公开Metadata同样须人工确认；程序不自动验证版权或任意自然语言中的秘密。
- 目录仅返回现有`ScriptMetadata`，按ID和数值版本稳定排序，列出全部明确已发布版本，不猜latest。
- 通过`importlib.resources.files/as_file`将包内内容目录在上下文内交给现有安全加载器；支持Python3.12的目录资源上下文。区分草稿加载与发布加载，加载器/Schema/正式灯塔JSON保持不变。
- 正式灯塔缺28项媒体，必须保持未发布、目录为空；其JSON仍作为服务端待发布内容随包供审查。测试成功发布与媒体打包仅使用隔离临时内容，不混入正式包。

执行清单（本轮三个子项由用户明确一起授权，完成T01.2.3才停）：

- [x] 核对约定、最新远端、PR #5和146个内容基线。
- [x] 先写发布/完整性/目录/资源报告测试并确认缺实现失败。
- [x] 实现发布库、审核/哈希与资源检查、包内访问；保留已有安全边界。
- [x] 修改构建白名单，实际构建wheel/sdist、检查内部清单、独立安装与临时媒体集成验证。
- [x] 跑新增/全部内容/全量后端、Ruff和离线依赖；21份Markdown、152个本地链接/代码块/JSON与TOML检查通过，2个原始聊天本机链接按约定排除。
- [ ] 更新进度和学习入口，提交、推送并创建PR供用户手动合并，停止等待审查。

技术依据：[Python3.12资源访问](https://docs.python.org/3.12/library/importlib.resources.html)明确支持目录`as_file`上下文；[Hatch构建文件选择](https://hatch.pypa.io/1.13/config/build/)用于限定包内文件。这些只支持实现选择，不代表产物已经通过检查。

## 实测记录

环境：Windows、Python3.12.4、Pydantic2.14.1、pytest9.0.2、Ruff0.15.4、uv；原开发锁仍为22包。无新增运行依赖，uv.lock未变；构建系统显式复用既有运行依赖Pydantic2.14.1，避免在Hatch钩子里重复实现Schema/哈希校验。

| 项目 | 实际结果 |
| --- | --- |
| 改动前内容基线 | 146 passed |
| 首31个新增用例先执行 | 31 failed，缺publication/packaged模块，非装配错误 |
| 首次实现 | 20 passed、11 failed；登记继承审核类后，多出的format/id/version被误当额外审核字段，诊断后仅选择审核字段重新严格校验，31通过 |
| 扩展故障与资源检查 | 暴露Windows目录rename的WinError5；有界重试后通过，持续失败仍拒绝并清理 |
| 已发布assets根联接回归 | 先1 failed（错误跟随内部assets联接）；改为基于release检查内部根，随后通过，未修改旧加载器 |
| 真实Git暂存往返 | 先1 failed（快照CRLF被转LF）；为发布路径设置-text后，原始字节保持一致，避免推送/检出破坏已登记哈希 |
| 最终全部内容 | 191 passed（新增45项），0 errors/0 skipped |
| 最终全部后端 | 191 passed、38 failed、0 errors/0 skipped；1条既有Starlette/AnyIO弃用警告 |
| 38项失败原因核对 | 全为缺twoworlds.api.app/storage.sqlite，未到HTTP行为断言；没有删除、skip、xfail或假服务 |
| Ruff check / format --check | 检查通过，28个Python文件格式通过（含构建钩子和独立打包验证工具） |
| uv lock --check --offline | 22包锁一致；运行依赖与既有Schema/loader/正式灯塔JSON/测试小样不变 |
| 首轮两个发行格式与安装验证 | 正式wheel 20文件、sdist 24文件；临时测试wheel 26文件、sdist 30文件；从sdist重建wheel逐文件字节相同；两套独立运行环境通过，损坏媒体构建被拒绝 |

最终完整JUnit：`work/publication-content-release.xml`（191项）、`work/publication-all-release.xml`（229项）。这些是本地证据，不提交日志/产物；文档与代码收尾后的发行产物复核见下方“最终构建清单”。

### 具体实现与修改文件

| 文件 | 职责 |
| --- | --- |
| [publication.py](../../backend/src/twoworlds/content/publication.py) | 审核模型、资源审计、初始化/发布/读取/目录与快照验证 |
| [_publication_files.py](../../backend/src/twoworlds/content/_publication_files.py) | 稳定错误码、严格路径/JSON/有限读取与独占新写/文件刷盘 |
| [packaged.py](../../backend/src/twoworlds/content/packaged.py) | importlib.resources上下文、草稿与发布分离、RECORD收录核对 |
| [registry.json](../../backend/src/twoworlds/content/published/registry.json) | 空发布库的格式登记；不是灯塔已发布的记录 |
| [hatch_build.py](../../backend/hatch_build.py)、[pyproject.toml](../../backend/pyproject.toml) | 构建时复用运行校验，只收录明确文件，排除测试/私人工作资料 |
| [.gitattributes](../../.gitattributes) | 发布快照路径保留原始字节，不随Git换行设置改变哈希 |
| [test_publication.py](../../backend/tests/content/test_publication.py) | 45个真实文件/快照/并发/故障/目录/资源边界检查 |
| [verify_distribution.py](../../backend/tests/packaging/verify_distribution.py) | 真构建、产物清单、从sdist重建、独立安装和测试媒体集成 |
| README、后端/测试README、docs03/04/05与交接 | 当前实际状态、学习入口、验收结果；本报告记录设计/证据 |

Schema、_references、原ScriptLoader、正式灯塔1.0.0、minimal.json、旧测试和uv.lock均未修改。

### 发布流程与边界

`ReleaseApproval`绑定JSON SHA256、审核人、Metadata已审标志及每个媒体的asset_id/path/SHA256/许可证据。`MediaAsset.source/license`非空不能替代审核。发布者应保存真正的授权记录后再提供审核对象；本轮只有明确标为自制测试用途的临时资源，没有给灯塔填写任何假审批。

`publish`先核验现有库，使用`.locks/<id>/<version>`目录独占同版本发布；在`.stage-*`内复制独立文件（不硬链接草稿），写入release.json，再对暂存快照完整复核。文件刷盘后，唯一提交点是同文件系统的原子目录rename。目标版本存在便拒绝；错误/缺资源/中断写入/提交失败均不会产生半份登记。Windows在保持同一锁和同一原子动作下最多尝试5次，总等待100毫秒；没有覆盖/拷贝式降级。

仓库的发布快照路径显式设置Git `-text`，保存原始JSON/媒体字节；否则全局JSON的LF转换会使已登记SHA256失效。测试使用真实隔离Git仓库和core.autocrlf=true，证明暂存前后字节一致，不操作本项目真实索引。

读取只访问明确版本，先确认登记，再校验原始JSON和全部媒体；从已经核验的同一份JSON字节解析，避免验哈希后重读另一份JSON。发布新版本会先核验旧库，已发布JSON/媒体被改动时不会继续发布。资源路径必须归属`id/version/`；内部assets根也做链接/目录联接检查，不把它当成可任意重配置的外部输入。

限制：这是受信任本地文件系统上的内容管理协议，所有发布者须遵守同一锁。不防御拥有目录写权限、同时改文件及登记的恶意管理员；SHA256不是签名。未证明断电持久性、网络文件系统行为或崩溃恢复。进程被强制终止可能留下隐藏暂存和锁；它们不进入目录/包，管理员须核对后处理，程序不擅自抢锁或删除已有版本。

### 公开目录与四种资源状态

`catalog()`重验已登记版本后返回`tuple[ScriptMetadata, ...]`，按ID与数值版本排序，多个版本都明确列出；无latest回退。未发布源目录不会被扫描。测试放入独特私线索/旁白标记，发布两个不同私密版本后目录仍只有Metadata；篡改已发布线索会使哈希检查失败，不会通过目录回显正文。

这证明字段与登记边界，不声称程序能自动识别简介中任意秘密；公开简介/角色介绍的人工审核绑定整个JSON哈希。没有FastAPI路由，内部read_media也不是玩家媒体授权接口，后续仍需T03/T08。

| 状态 | 怎么判断 | 灯塔当前结果 |
| --- | --- | --- |
| declared | 正式JSON存在该MediaAsset | 28项true |
| file_present | 规范根内普通文件确实存在 | 28项false |
| license_reviewed | 审核人/许可证据与该文件SHA256匹配 | 28项false |
| included_in_package | 文件内容与已安装分发包RECORD成员SHA256匹配；仅源文件检查为None | 正式安装包28项false |

构建只打包服务端草稿JSON和已登记快照，不自动收录草稿资源。正式灯塔1.0.0缺实际媒体，因此发布被明确拒绝，正式包目录为空；不能被称为可玩已发布版本。

### 构建与独立安装的实测方法

直接离线隔离构建先因默认缓存缺Hatchling元数据、项目缓存缺pydantic-core的解析元数据失败。改为在新构建环境按既有锁离线安装5个运行校验依赖，再用项目已有缓存安装Hatchling及4个工具依赖，随后显式使用该独立环境构建（不借用全局或开发环境），没有联网下载或改锁。

在当前PR工作树根实际执行的关键命令（主目录复现时路径按检出位置调整）：

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$PWD/work/publication-build/.venv"
uv sync --project backend --no-dev --no-install-project --locked --offline --cache-dir F:/two-worlds-agent-game/work/uv-cache --python D:/Python/python.exe --no-python-downloads --link-mode copy
uv pip install --python work/publication-build/.venv/Scripts/python.exe --offline --cache-dir F:/two-worlds-agent-game/work/uv-cache hatchling==1.27.0
uv build --project backend --offline --no-build-isolation --python work/publication-build/.venv/Scripts/python.exe --no-python-downloads --no-sources --out-dir work/publication-dist
```

构建钩子在构建时以独立包名加载本次构建源码，不改sys.path，不借开发安装；复用发布库校验并按登记选择每个资源。wheel只含包与元数据；sdist另含钩子/配置/README/锁，可在无原项目目录的提取目录重建。Hatch自动加入的.gitignore不是IDE/私人文件。

完整产物验证工具的实际命令：

```powershell
.\backend\.venv\Scripts\python.exe backend/tests/packaging/verify_distribution.py --build-python work/publication-build/.venv/Scripts/python.exe --cache-dir F:/two-worlds-agent-game/work/uv-cache --output work/publication-verification
```

该工具要求新output目录，不删除旧资料；依次构建正式包、复制到隔离项目发布packaging_example测试内容、植入不应打包的canary文件并检查两种产物、从正式sdist重建wheel，然后分别建立两个仅6包的运行环境（本项目+5个运行依赖）安装wheel。运行时cwd为空目录、Python -I、没有pytest/FastAPI，实际导入来自site-packages；草稿与已发布测试内容均按明确版本读取，缺版明确失败。测试媒体字节与登记匹配，并真实出现在RECORD中；修改测试发布媒体后构建失败、无新产物。

初轮证据在`work/publication-verification/verification.json`；文档/安全边界收尾后已对同一工具改用`--output work/publication-verification-release`再次完整运行成功，最终证据为该目录的verification.json。临时项目中的PNG是本地编码的真实1像素图，WAV用标准库写入；它们仅用于集成，不是灯塔的图像/音频，也没有声称实际播放体验或正式许可已通过。

### 自己观察与测试

项目根运行（可直接使用原开发环境，无付费调用）：

```powershell
@'
from twoworlds.content.packaged import packaged_content
with packaged_content() as content:
    print(content.load_draft('lighthouse', '1.0.0').metadata.title)
    print('published catalog:', content.catalog())
    checks = content.audit_draft('lighthouse', '1.0.0')
    print('declared:', len(checks), 'existing:', sum(x.file_present for x in checks))
'@ | .\backend\.venv\Scripts\python.exe -I -X utf8 -
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content/test_publication.py -q --basetemp=work/pytest-publication-local
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q --basetemp=work/pytest-publication-content-release --junitxml=work/publication-content-release.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short --basetemp=work/pytest-publication-all-release --junitxml=work/publication-all-release.xml
.\backend\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/hatch_build.py
.\backend\.venv\Scripts\python.exe -m ruff format --check backend/src backend/tests backend/hatch_build.py
uv lock --project backend --check --offline
```

预期：跨时灯塔、目录`()`、28声明/0文件；44/191个内容检查通过，全量后端仍有38个缺实现失败。严格路径测试在本机需要相应读取权限，不要关闭校验；pytest的basetemp是会重建的专用临时目录，不放学习笔记。

### 建议阅读顺序与下一步

先看本报告的草稿/发布目录区别，再读`ReleaseApproval`与`PublicationStore.publish`，顺着`_validate`到`catalog`，理解为什么错误内容不能进入目录；随后看`packaged_content`与RECORD核对、`hatch_build.py`的明确收录，最后看故障/篡改测试及独立打包验证工具。

例如先发布测试alpha/1.0.0，再修改源草稿，已发布读取仍来自自己的快照；改发布快照中的一个媒体字节，load/catalog及继续发布都会拒绝。这个例子是文件/版本协议，不涉及游戏规则。

下一环节是T02：用确定性Python规则验证灯塔动作、前置、错误不变、双向因果和共同选择；本轮不执行。真实灯塔媒体、许可/体验、HTTP/WS、数据库、AI、真机和部署均未实现/未验证。当前没有可玩地址。完成本轮PR后停止，等待用户审查和明确继续。

## 最终构建清单

2026-11-01最终重跑成功。正式产物在`work/publication-verification-release/formal/`，仅本地验证、不上传PyPI。两个运行环境均无pytest/FastAPI，实际导入site-packages；包内草稿、已发布临时内容、实际临时媒体和缺版拒绝均通过。开发环境22包/独立构建环境10包兼容，锁一致。

| 产物 | 文件数 | SHA256 |
| --- | --- | --- |
| 正式wheel | 20 | `3f5daf8216df8b59599ebbc22f41975dcdbb5d7687371469ca217de044872596` |
| 正式sdist | 24 | `8438704fa693af02d8bafd74e325be9b09e6e1dd93fde95c9e4a10d4b2acd19b` |
| 临时测试wheel | 26 | `3efa692cd0f334d232e2d6723656e384e1695d97cf64ff8e9efb84a2ad1762aa` |
| 临时测试sdist | 30 | `e9896dc16700085df1eb7141b44d800ae49939ef49ea4134055895110f708584` |

### 正式wheel完整文件清单

```text
twoworlds/__init__.py
twoworlds/ai/__init__.py
twoworlds/api/__init__.py
twoworlds/application/__init__.py
twoworlds/content/__init__.py
twoworlds/content/_publication_files.py
twoworlds/content/_references.py
twoworlds/content/loader.py
twoworlds/content/packaged.py
twoworlds/content/publication.py
twoworlds/content/published/registry.json
twoworlds/content/schema.py
twoworlds/content/scripts/lighthouse/1.0.0.json
twoworlds/domain/__init__.py
twoworlds/ports/__init__.py
twoworlds/realtime/__init__.py
twoworlds/storage/__init__.py
twoworlds_api-0.1.0.dist-info/METADATA
twoworlds_api-0.1.0.dist-info/RECORD
twoworlds_api-0.1.0.dist-info/WHEEL
```

### 正式sdist完整文件清单

```text
twoworlds_api-0.1.0/.gitignore
twoworlds_api-0.1.0/.python-version
twoworlds_api-0.1.0/PKG-INFO
twoworlds_api-0.1.0/README.md
twoworlds_api-0.1.0/hatch_build.py
twoworlds_api-0.1.0/pyproject.toml
twoworlds_api-0.1.0/src/twoworlds/__init__.py
twoworlds_api-0.1.0/src/twoworlds/ai/__init__.py
twoworlds_api-0.1.0/src/twoworlds/api/__init__.py
twoworlds_api-0.1.0/src/twoworlds/application/__init__.py
twoworlds_api-0.1.0/src/twoworlds/content/__init__.py
twoworlds_api-0.1.0/src/twoworlds/content/_publication_files.py
twoworlds_api-0.1.0/src/twoworlds/content/_references.py
twoworlds_api-0.1.0/src/twoworlds/content/loader.py
twoworlds_api-0.1.0/src/twoworlds/content/packaged.py
twoworlds_api-0.1.0/src/twoworlds/content/publication.py
twoworlds_api-0.1.0/src/twoworlds/content/published/registry.json
twoworlds_api-0.1.0/src/twoworlds/content/schema.py
twoworlds_api-0.1.0/src/twoworlds/content/scripts/lighthouse/1.0.0.json
twoworlds_api-0.1.0/src/twoworlds/domain/__init__.py
twoworlds_api-0.1.0/src/twoworlds/ports/__init__.py
twoworlds_api-0.1.0/src/twoworlds/realtime/__init__.py
twoworlds_api-0.1.0/src/twoworlds/storage/__init__.py
twoworlds_api-0.1.0/uv.lock
```

### 临时测试包额外文件

仅在隔离测试项目生成。完整清单为上面的正式包路径集合加以下各自6项（wheel共26项、sdist共30项），实际文件数与该并集已核对；不进入正式包。

wheel额外项：

```text
twoworlds/content/published/packaging_example/1.0.0/assets/packaging_example/1.0.0/b_voice.wav
twoworlds/content/published/packaging_example/1.0.0/assets/packaging_example/1.0.0/ending_bg.png
twoworlds/content/published/packaging_example/1.0.0/assets/packaging_example/1.0.0/opening_bg.png
twoworlds/content/published/packaging_example/1.0.0/release.json
twoworlds/content/published/packaging_example/1.0.0/scripts/packaging_example/1.0.0.json
twoworlds/content/scripts/packaging_example/1.0.0.json
```

sdist额外项：

```text
twoworlds_api-0.1.0/src/twoworlds/content/published/packaging_example/1.0.0/assets/packaging_example/1.0.0/b_voice.wav
twoworlds_api-0.1.0/src/twoworlds/content/published/packaging_example/1.0.0/assets/packaging_example/1.0.0/ending_bg.png
twoworlds_api-0.1.0/src/twoworlds/content/published/packaging_example/1.0.0/assets/packaging_example/1.0.0/opening_bg.png
twoworlds_api-0.1.0/src/twoworlds/content/published/packaging_example/1.0.0/release.json
twoworlds_api-0.1.0/src/twoworlds/content/published/packaging_example/1.0.0/scripts/packaging_example/1.0.0.json
twoworlds_api-0.1.0/src/twoworlds/content/scripts/packaging_example/1.0.0.json
```

正式包20/24项中无实际媒体，无已发布灯塔登记；临时测试包才含3个测试媒体。两个格式均无tests/work/outputs/IDE/缓存/私人canary；无关资源即使被放入已发布资源目录也不会被构建收录。
