# T01.2.1 · 按版本加载剧本

日期：2026-10-29。本轮只实现版本加载器；正式灯塔内容、发布冻结与公开目录属于后续子环节。用户要求执行T01.2，按学习约定先完成其中一个可验证环节。

## 设计与步骤

入口为`ScriptLoader(root).load(script_id, content_version) -> ScriptVersion`。root由服务端受信任配置指定，必须是现有目录；ID和版本复用Schema的Identifier/Version约束。唯一文件布局为`root/<script_id>/<content_version>.json`，没有latest别名或缺版回退。

读取前解析规范路径并检查仍在root内，阻止静态符号链接/目录联接越界；只读取普通文件，单文件上限1MiB。目录须由受信任发布流程管理，本实现不承诺抵抗有本机写权限者在检查和读取间替换目录；不替代后续发布冻结和文件系统权限。

严格读取UTF-8 JSON：拒绝重复键、NaN/Infinity、非法编码/语法，再调用现有ScriptVersion校验，最后要求metadata的ID/版本与请求相同。每次读取独立返回冻结定义，不缓存、不执行规则或代码、不读取声明的媒体文件。

统一错误ScriptLoadError提供code；区分CONTENT_INVALID_ROOT、CONTENT_INVALID_REFERENCE、CONTENT_NOT_FOUND、CONTENT_PATH_FORBIDDEN、CONTENT_READ_FAILED、CONTENT_TOO_LARGE、CONTENT_INVALID_JSON、CONTENT_INVALID_SCHEMA、CONTENT_IDENTITY_MISMATCH。默认消息不回显绝对磁盘路径、剧情正文或底层异常详情；开发排查可直接对已知内容使用Schema。

- [x] 先写加载/缺版/路径/JSON/Schema/标识错误的真实文件测试，确认缺实现失败。
- [x] 在content/loader.py实现只读加载器与明确错误；不改Schema或引入新依赖。
- [x] 验证本轮测试、既有74例、全量中原38项缺实现失败、Ruff/锁及打包检查。
- [ ] 更新阅读/复现/交接，提交到codex主题分支并创建PR；完成即停。

## T01.2拆分

1. T01.2.1：本轮版本加载器与测试。
2. T01.2.2：正式灯塔四场景内容；媒体文件/来源按实际交付记录。
3. T01.2.3：发布不可覆盖保护、公开目录边界及版本/打包集成验证。

测试仍使用minimal.json小样，不把它放入正式scripts目录，不宣称已有灯塔剧本或可游玩服务。

## 实际验证

环境：Python3.12.4，依赖沿用uv.lock，无新增依赖。

| 检查 | 实际结果 |
| --- | --- |
| 基线Schema测试 | 74 passed |
| 加载器实现前 | 36 failed，缺twoworlds.content.loader |
| 加载器实现后（严格路径解析可用的扩展权限环境） | 36 passed，含真实Windows目录联接越界测试 |
| 完整后端 | 110 passed、38 failed；JUnit共148项，0 errors、0 skipped，38项均缺api.app/storage.sqlite，保留既有Starlette/AnyIO弃用提示 |
| Ruff检查/格式、uv lock --check | 检查通过；21个Python文件格式正确；22包锁一致 |
| wheel构建与真实安装 | 离线构建成功；6包独立环境安装wheel，模块从site-packages导入，不含FastAPI/pytest；合法版本可加载、缺版明确拒绝 |
| wheel内容/依赖 | 包内loader.py逐字节等于当前源码，不含work/tests/outputs/IDE数据；6包依赖检查通过 |

普通沙箱首轮为34失败/2通过，原因是Windows严格路径解析的GetFinalPathName操作被拒绝：exists/is_dir可用，但resolve(strict=True)抛PermissionError。没有改用宽松解析绕过它；根与候选文件都保持strict=True，解析失败时拒绝读取。同一组测试在扩展权限环境下全部通过。正常本机PowerShell/后续CI仍须具备实际文件读取与路径解析权限。

wheel已成功构建，但首次uv pip独立离线解析缺少registry缓存；随后先按现有锁文件同步运行依赖，再用--no-deps替换项目包为同一wheel，完成实际安装验证，没有联网更新依赖。硬链接不可用时uv自动复制文件，不影响结果。

本轮代码/测试在`F:\two-worlds-agent-game\work\pr-t01-1-schema`，分支`codex/t01-2-1-version-loader`；原学习目录的IDE设置、空根pyproject及旧分支保留。包产物、环境、demo和JUnit均在被忽略的work下，未发布PyPI。

收尾文档检查：20份Markdown、117个可检查本地链接、JSON示例/代码块通过；2个原始聊天链接按既有“仅保留本机”约定排除，不把原始记录上传。准备同步的10个本轮交付路径与原目录无冲突，原有Schema注释、IDE和空模板不在覆盖集合。

## 阅读顺序与自己试

1. [loader.py](../../backend/src/twoworlds/content/loader.py)的ScriptLoader.load：请求标识 → 规范路径 → 有界读取 → 严格JSON → Schema → 标识一致。
2. ScriptLoadError与错误表：调用方用code区分不存在、内容错误和读取故障，不用解析人类消息。
3. [test_loader.py](../../backend/tests/content/test_loader.py)：先看成功/缺版两例，再看重复键和真实目录联接；仅PermissionError分支使用文件边界故障注入。

例子：请求schema_example的1.0.0，只能读取schema_example/1.0.0.json。即便2.0.0存在，缺少1.0.0时也不能自动改读2.0.0，否则旧存档的内容版本会被替换。

在检出本分支的项目根目录（当前实际工作树如上）执行：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content/test_loader.py -q --basetemp=work/pytest-loader-local
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q --basetemp=work/pytest-content-local
```

预期分别为36通过、110通过。basetemp是pytest会清空重建的专用目录，不存笔记；并行运行用不同目录。若在Codex受限执行环境看到CONTENT_INVALID_ROOT，先核对严格路径解析权限，不把已有目录误当作不存在。

也可以自己运行小样（只有测试内容与媒体声明，不提供实际素材）：

```powershell
New-Item -ItemType Directory -Force work/loader-demo/scripts/schema_example | Out-Null
Copy-Item -LiteralPath backend/tests/content/fixtures/minimal.json -Destination work/loader-demo/scripts/schema_example/1.0.0.json
.\backend\.venv\Scripts\python.exe -c "from twoworlds.content.loader import ScriptLoader; print(ScriptLoader('work/loader-demo/scripts').load('schema_example', '1.0.0').metadata.title)"
```

本轮没有游戏服务地址。T01.2.2才编写灯塔四场景；T01.2.3再做发布不可覆盖、目录和内容资源打包集成。本环节完成后停止，不后台继续。
