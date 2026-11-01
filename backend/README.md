# TwoWorlds 后端

当前已有内容基础设施与T02灯塔纯规则；123个领域、191个内容测试通过，另38个契约因缺API/SQLite实现失败。灯塔缺28项媒体和授权，仍未发布、目录为空；玩家投影、业务路由、数据库和AI尚未实现。后端项目根目录为本目录，正式源码只有`src/twoworlds`这一处。

## 1. 先看这几个文件

1. `pyproject.toml`：包名、Python要求、构建方式、依赖和检查工具配置。
2. `.python-version`：让支持该文件的工具优先选择Python3.12，避免误用本机`py`启动器默认的3.14。
3. `src/twoworlds/__init__.py`：Python包入口；目前只有包说明，导入不会连接数据库或调用模型。
4. `uv.lock`：uv生成的依赖解析结果，提交后按锁文件同步；不要手工改其中的版本和校验值。

安装名`twoworlds-api`是分发包名称，代码中使用`import twoworlds`。`src`布局让运行与测试通过已安装的包访问源码，避免仅因当前目录碰巧在搜索路径里而导入成功。

## 2. 模块如何对应架构

| 路径 | 将来负责什么 | 当前状态 |
| --- | --- | --- |
| src/twoworlds/api | HTTP、WS路由、请求模型与认证适配 | 仅模块边界 |
| src/twoworlds/application | 身份、房间、存档、对话的流程编排 | 仅模块边界 |
| src/twoworlds/domain | 确定性规则与可见性投影 | 灯塔纯规则已实现；玩家投影/分享/回顾留给T03 |
| src/twoworlds/content | 草稿校验、快照发布、哈希与Metadata目录、包资源读取 | T01内容基础设施已实现；灯塔未发布，真实媒体与许可尚缺 |
| src/twoworlds/ports | 仓储、文本、语音等适配接口 | 仅模块边界 |
| src/twoworlds/storage | Mongo、SQLite与原子提交适配 | 仅模块边界 |
| src/twoworlds/ai | 受限LangGraph文本流程与Provider | 仅模块边界 |
| src/twoworlds/realtime | 订阅、个人快照和连接协议 | 仅模块边界 |
| tests/contracts | 已迁移的身份、命令与平台行为要求 | 38个可收集条目；缺少业务实现，尚未通过 |
| tests/content | 字段/引用/媒体声明与加载/发布边界 | 74个Schema+36个加载+36个正式内容+45个发布检查通过；不是完整游戏验收 |
| tests/domain | 真实内容驱动的纯规则 | T02新增123项，含两个结局、54个可达世界、拒绝不变与依赖隔离 |

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

当前没有游戏服务启动入口，不要运行并不存在的`uvicorn twoworlds.api:app`。新契约的`twoworlds.api.app.create_app`和`twoworlds.storage.sqlite.SQLiteRepository`尚未实现，测试调用工厂时会明确失败。

## 4. 构建与验证

```powershell
uv build --project backend --python 3.12 --no-python-downloads --no-sources --out-dir backend/dist
```

构建产物包含wheel与源码归档；两者均排除tests/work/outputs/IDE/缓存/私人资料。`hatch_build.py`先复用现有Schema与发布库核验，再逐一收录草稿JSON、发布登记和已发布实际媒体；不收录未审核的草稿媒体和未登记杂项。sdist带构建钩子及必要配置，wheel不带钩子或测试。T01.2.3已实际检查清单、从sdist重建wheel、独立安装与临时测试媒体集成，详见[发布报告](../docs/reports/content-publication.md)。

T00.3后的测试运行方法与阅读顺序见[测试说明](tests/README.md)，来源映射见[基线修订报告](../docs/reports/baseline-changes.md)。执行`python -m pytest backend/tests/contracts --collect-only -q`可查看38个契约要求；执行这些用例目前会报告缺少T04/T08实现。收集成功不表示行为通过，T01～T14将按阶段实现并补齐更低层测试。

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

从项目根运行`.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain -q --basetemp=work/pytest-t02-local`应123通过。阅读顺序：`domain/models.py` → `engine.py` → `mechanics/common.py` → `mechanics/lighthouse.py` → `tests/domain/test_lighthouse.py`。完整12步/不同探索顺序16步演示及拒绝/版本说明见[规则报告](../docs/reports/lighthouse-engine.md)。本轮没有重建发行包，旧打包产物不作为本轮代码已安装的证据。

## 5. 依赖策略

本阶段运行依赖为Pydantic2.14.1，用于内容Schema；开发依赖锁定pytest9.0.2、ruff0.15.4、FastAPI0.132.0和httpx0.28.1。后两项供TestClient测试装配使用；实际API实现时再将FastAPI提升为运行依赖。uvicorn、LangGraph和pymongo等在对应实现环节加入，不依赖全局环境恰好存在这些包。

Hatchling负责Python分发包构建，uv负责解析、环境同步与工具执行；两者都不启动游戏服务。构建系统额外显式要求同版本Pydantic2.14.1，以便隔离构建复用发布/Schema校验；运行依赖没有增加，uv.lock保持不变。当前包只在本地构建/安装验证，没有发布到PyPI。
