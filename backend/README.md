# TwoWorlds 后端

当前已有可安装Python包、T01.1内容Schema和T01.2.1只读版本加载器；110个内容测试通过，38个契约仍因缺业务实现而失败。正式灯塔内容、游戏规则、API路由、数据库和AI调用尚未实现。后端项目根目录为本目录，正式源码只有`src/twoworlds`这一处。

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
| src/twoworlds/domain | 确定性规则与可见性投影 | 仅模块边界 |
| src/twoworlds/content | 剧本结构/引用校验与按版本读取 | Schema与加载器已实现，正式内容/发布/目录待后续 |
| src/twoworlds/ports | 仓储、文本、语音等适配接口 | 仅模块边界 |
| src/twoworlds/storage | Mongo、SQLite与原子提交适配 | 仅模块边界 |
| src/twoworlds/ai | 受限LangGraph文本流程与Provider | 仅模块边界 |
| src/twoworlds/realtime | 订阅、个人快照和连接协议 | 仅模块边界 |
| tests/contracts | 已迁移的身份、命令与平台行为要求 | 38个可收集条目；缺少业务实现，尚未通过 |
| tests/content | 字段/引用/媒体声明与加载边界 | 74个Schema+36个加载测试通过；不是完整游戏验收 |

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

构建产物应包含wheel与源码归档。wheel只包含`twoworlds`源码及包元信息，不包含项目原始聊天、密钥、环境目录或根目录的历史资料。具体本轮执行命令与结果见[工程布局报告](../docs/reports/backend-layout.md)。

T00.3后的测试运行方法与阅读顺序见[测试说明](tests/README.md)，来源映射见[基线修订报告](../docs/reports/baseline-changes.md)。执行`python -m pytest backend/tests/contracts --collect-only -q`可查看38个契约要求；执行这些用例目前会报告缺少T04/T08实现。收集成功不表示行为通过，T01～T14将按阶段实现并补齐更低层测试。

T01.1新增74个内容校验用例，因此当前全量收集为112个（74个已通过、38个仍缺实现）。可从项目根目录运行`.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q`；源码阅读顺序、测试专用JSON与边界见[Schema报告](../docs/reports/content-schema.md)。模型返回冻结定义，游戏状态另建；不要把包含私有线索的ScriptVersion整体发给客户端。

T01.2.1又新增36个加载测试：当前全量148项（110通过、38仍缺实现）。在检出当前分支的项目根运行`.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content/test_loader.py -q --basetemp=work/pytest-loader-local`可观察本轮；当前实际工作树为`F:\two-worlds-agent-game\work\pr-t01-1-schema`。小样加载方法、严格路径权限与只读边界见[加载器报告](../docs/reports/content-loader.md)。尚无正式scripts/lighthouse文件或游戏服务入口。

## 5. 依赖策略

本阶段运行依赖为Pydantic2.14.1，用于内容Schema；开发依赖锁定pytest9.0.2、ruff0.15.4、FastAPI0.132.0和httpx0.28.1。后两项供TestClient测试装配使用；实际API实现时再将FastAPI提升为运行依赖。uvicorn、LangGraph和pymongo等在对应实现环节加入，不依赖全局环境恰好存在这些包。

Hatchling负责Python分发包构建，uv负责解析、环境同步与工具执行；两者都不启动游戏服务。当前包和构建只在本地验证，没有发布到PyPI。
