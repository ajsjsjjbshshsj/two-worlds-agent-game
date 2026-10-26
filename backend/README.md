# TwoWorlds 后端

当前是T00.2.2交付的可安装Python包骨架，业务规则、API路由、数据库和AI调用尚未实现。后端项目根目录为本目录，正式源码只有`src/twoworlds`这一处。

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
| src/twoworlds/content | 版本化剧本、媒体清单的加载与校验 | 仅模块边界 |
| src/twoworlds/ports | 仓储、文本、语音等适配接口 | 仅模块边界 |
| src/twoworlds/storage | Mongo、SQLite与原子提交适配 | 仅模块边界 |
| src/twoworlds/ai | 受限LangGraph文本流程与Provider | 仅模块边界 |
| src/twoworlds/realtime | 订阅、个人快照和连接协议 | 仅模块边界 |
| tests | 后续迁移与新增行为测试 | 只有测试范围说明，尚无测试用例 |

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

当前没有游戏服务启动入口，不要运行并不存在的`uvicorn twoworlds.api:app`。旧草稿的`create_app`和`SQLiteRepository`尚未实现，旧测试也尚未迁移。

## 4. 构建与验证

```powershell
uv build --project backend --python 3.12 --no-python-downloads --no-sources --out-dir backend/dist
```

构建产物应包含wheel与源码归档。wheel只包含`twoworlds`源码及包元信息，不包含项目原始聊天、密钥、环境目录或根目录的历史资料。具体本轮执行命令与结果见[工程布局报告](../docs/reports/backend-layout.md)。

`tests/`当前没有用例，执行pytest收集可能显示“没有测试”；这不表示产品测试通过。当前阶段用包安装/隔离导入、构建和代码检查验证工程基础，T00.3再处理旧测试契约。

## 5. 依赖策略

本阶段运行依赖为空；开发依赖锁定pytest9.0.2和ruff0.15.4。旧草稿列出的FastAPI、uvicorn、pydantic、httpx、LangGraph和pymongo仅作后续选型输入，在对应实现环节加入并锁定、验证，不依赖全局环境恰好存在这些包。

Hatchling负责Python分发包构建，uv负责解析、环境同步与工具执行；两者都不启动游戏服务。当前包和构建只在本地验证，没有发布到PyPI。
