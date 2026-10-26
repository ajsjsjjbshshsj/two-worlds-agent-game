# T00.2.2 · 后端工程目录与 Python 包布局

日期：2026-10-26，Asia/Shanghai。状态：**工程基础已完成并验证，等待用户观察后继续。**

## 1. 本轮完成什么

建立唯一的`backend/src/twoworlds`正式包位置，配置Python3.12、Hatchling打包、uv锁文件与项目虚拟环境；准备8个职责子包和测试目录说明。没有实现API、游戏规则、数据库、AI或视听播放器，也没有建立前端。

当前仍在`F:\two-worlds-agent-game`的`codex/bootstrap`分支工作。本轮是既有干净分支上的工程准备，不另建worktree，以保持用户学习时的文件路径一致；没有改动其他仓库。

## 2. 目录与作用

```text
backend/
├─ .python-version           # 选择本机Python3.12系列
├─ pyproject.toml            # 分发包、构建、依赖与工具配置
├─ uv.lock                   # uv生成的可审阅依赖锁定
├─ README.md                 # 安装、检查与学习说明
├─ src/twoworlds/
│  ├─ __init__.py            # 包入口，目前不启动服务
│  ├─ api/__init__.py        # HTTP/WS适配边界
│  ├─ application/__init__.py # 业务用例编排边界
│  ├─ domain/__init__.py      # 纯游戏规则边界
│  ├─ content/__init__.py     # 版本化剧本与媒体清单边界
│  ├─ ports/__init__.py       # 外部能力接口边界
│  ├─ storage/__init__.py     # 数据库存储边界
│  ├─ ai/__init__.py          # 受限AI文本工作流边界
│  └─ realtime/__init__.py    # 订阅与个人快照边界
└─ tests/README.md            # 说明后续测试迁移范围
```

本机另有被忽略的`backend/.venv`与`backend/dist`，用于开发和构建；`work/uv-cache`和`work/wheel-verification/.venv`用于下载缓存与独立wheel验证。这些不进入Git。

## 3. 配置选择与来源

| 项目 | 选择 | 原因与范围 |
| --- | --- | --- |
| 分发包名 | twoworlds-api，0.1.0 | 沿用旧草稿名称；Python导入名为twoworlds |
| 源码布局 | src/twoworlds | 用实际安装验证导入，不靠当前工作目录 |
| Python要求 | >=3.12，开发工具优先3.12；实测3.12.4 | 避免误用本机py默认的3.14；其他版本未逐个验证 |
| 构建 | hatchling==1.27.0 | 为src布局提供可安装wheel与源码归档 |
| 开发依赖 | pytest==9.0.2、ruff==0.15.4 | 沿用旧草稿开发工具版本，装入项目环境 |
| 运行依赖 | 当前为空 | 尚无业务代码；API、Mongo和LangGraph依赖在对应任务中加入并验证 |
| 索引 | 显式https://pypi.org/simple | 锁文件不携带机器私有源或凭证 |
| 测试导入 | importlib模式 | 使用安装后的包，不加临时pythonpath |
| 依赖锁 | backend/uv.lock，8个包条目 | 包含本项目editable条目与7个开发工具/传递依赖 |

**设计决定：** 不一次性照抄旧草稿的全部运行依赖。这样当前环境只服务本环节，后面每次增加外部能力都能解释用途、看到锁文件变化。代价是后续任务需要明确补齐所需依赖；不能把本轮环境称为完整FastAPI/Mongo/AI运行环境。

旧草稿`outputs/twoworlds/backend/pyproject.toml`未修改，SHA256仍为`1fddb6a5ce260a69aa063b05f792c7731b0f0a39e725e1f8803ac3da76baff2f`。旧测试未复制或迁移，T00.3再修订其会话、动作与回执契约。

## 4. 实际执行与结果

### 4.1 锁定与安装

```powershell
uv lock --project backend --python D:\Python\python.exe --no-python-downloads --cache-dir work/uv-cache
uv sync --project backend --python D:\Python\python.exe --no-python-downloads --locked --link-mode copy --cache-dir work/uv-cache
```

实际命令使用项目与缓存的绝对路径；此处以项目根目录为起点缩写。成功解析并安装8个包到`backend/.venv`：本项目0.1.0、pytest9.0.2、ruff0.15.4、colorama0.4.6、iniconfig2.3.1、packaging26.3、pluggy1.7.0、pygments2.21.0。

下载和安装仅用于本地开源开发工具，没有修改全局Python环境、上传项目或调用模型。锁文件的editable路径为`.`，registry为公开PyPI，不含本机项目绝对路径或认证信息。

### 4.2 安装后的导入与代码检查

在`backend/.venv/Scripts/python.exe -I`中导入包，结果：

- Python3.12.4，环境为本项目backend/.venv。
- 分发包版本0.1.0；源码路径为`F:\two-worlds-agent-game\backend\src\twoworlds\__init__.py`。
- api、application、domain、content、ports、storage、ai、realtime八个子包均可导入。
- pytest --version返回9.0.2，仅验证工具可运行，不表示业务测试通过。
- Ruff检查通过，格式检查显示9个Python文件已符合格式。

还实际执行了Backend README中的uv run隔离导入与Ruff命令（增加offline和本地cache-dir参数），结果与直接使用虚拟环境一致。

### 4.3 构建与独立wheel安装

执行`uv build --no-sources --offline`，使用相同项目配置、本机Python与本地缓存；成功构建源码归档，并从源码归档生成wheel：

| 产物 | 大小 | SHA256 |
| --- | --- | --- |
| backend/dist/twoworlds_api-0.1.0-py3-none-any.whl | 5244字节 | 62b3b78f25215c4cfb01a8b38dff2d7b6182aa81bd9a88519c01f71e771d9b81 |
| backend/dist/twoworlds_api-0.1.0.tar.gz | 8368字节 | fcdecc1f888a5bea3201f88cdf7d4a6f084863b4d2cec551eb55515b08df15da |

这两个哈希对应本轮构建，不保证后续修改README、源码或构建依赖后仍相同。

另建`work/wheel-verification/.venv`，离线安装生成的wheel，再以`-I`导入。结果路径为该临时环境的`Lib/site-packages/twoworlds/__init__.py`，分发版本0.1.0。这证明验证使用了构建产物，没有从backend/src碰巧取到源码。

检查归档内容：wheel共12项，包含9个Python模块与元信息；源码归档16项。归档没有根项目原始聊天、outputs、虚拟环境或缓存文件。没有发布到PyPI或其他服务。

普通沙箱首次构建因uv在Windows临时目录更新工具程序PE资源被拒绝；扩展执行权限后，同一配置离线构建成功。处理的是构建工具访问条件，没有修改源码来绕过业务问题。

### 4.4 锁与环境完整性

`uv lock --check --offline`通过；`uv pip check`检查8个已安装包并报告依赖兼容。`.gitignore`实际匹配backend/.venv、backend/dist、work/uv-cache和临时wheel验证环境。

收尾检查还确认：构建归档中的README、pyproject、uv.lock、.python-version、测试说明及wheel里的Python源码与当前文件逐字节一致；14份相关文档的链接、代码块与JSON示例通过。旧依赖草稿哈希未变，没有提前创建前端或迁入旧测试。

## 5. 你可以按这个顺序学习

1. 先看[pyproject.toml](../../backend/pyproject.toml)：build-system说明“怎么打包”，project说明“这个包是谁”，dependency-groups说明“开发时用什么工具”。
2. 再看[包入口](../../backend/src/twoworlds/__init__.py)与各子包：目录对应职责，不代表功能已经写完；目前import不会启动服务。
3. 看[后端README](../../backend/README.md)第3节，从项目根目录执行导入命令，观察实际路径。
4. 最后看[uv.lock](../../backend/uv.lock)：这是工具解析的结果，不需要先逐行读完；重点观察版本、source和哈希如何记录。

例如`uv run --project backend --locked python -I -c "import twoworlds; print(twoworlds.__file__)"`先选择backend项目与它的环境，再在隔离导入模式中寻找twoworlds。输出src路径来自editable安装；安装wheel后的输出则来自site-packages，这是两种安装方式的区别。

## 6. 本环节出口

本轮只验证工程包和工具链，尚无测试用例、API入口、游戏场景、Mongo连接或模型调用。没有把“pytest能运行”写成“游戏测试通过”。

下一步为T00.3：审阅并修订旧测试契约，再迁移到backend/tests。**当前环节完成后停止，等待用户观察文件并明确要求继续。**
