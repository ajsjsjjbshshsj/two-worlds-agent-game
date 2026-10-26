# T00.1 · 工作区与开发环境检查报告

检查日期：2026-10-26，Asia/Shanghai；Git补充检查时间约20:47。  
项目目录：`F:\two-worlds-agent-game`。  
状态：**环境检查环节完成；存在后续待处理项；业务代码尚未开始。**

## 1. 本环节做了什么

读取 AGENTS.md、交接与当前任务，盘点文件和版本管理归属，检查解释器/依赖工具、Docker/Mongo条件、浏览器自动化及参考仓库版本。只执行本地检查和临时无界面浏览器验证，没有安装软件、初始化仓库、启动数据库或调用模型。

检查结果分为：可用、缺失、当前不可连接、未验证。工具安装与服务正在运行是不同结论；全局依赖存在也不代表本项目已有独立环境。

## 2. 结论与下一阶段影响

| 项目 | 实际结果 | 对后续开发的影响 |
| --- | --- | --- |
| 工作材料 | README、AGENTS、6份专题文档、架构图与原始材料存在 | 可进入工程整理 |
| 业务目录 | 根目录没有 backend、frontend | 尚无可启动应用或构建入口 |
| Git归属 | T00.1初查无.git并继承F:/；T00.2.1后续已建立独立.git | 当前Git根目录为本项目；详见[仓库设置报告](repository-setup.md) |
| 当前项目跟踪 | T00.1初查在父仓库未跟踪；T00.2.1已建立并推送独立仓库基线 | 原始聊天/缓存排除；当前同步结果见仓库报告 |
| Python | `python`为3.12.4，路径`D:\Python\python.exe` | 满足项目Python≥3.12的基线 |
| Python启动器 | `py`默认指向3.14；另有3.12和Anaconda3.9 | 后续明确选Python3.12，避免不同命令用了不同解释器 |
| 项目虚拟环境 | 根目录与backend下均无.venv，当前解释器不是虚拟环境 | 在T00.2按所选工具建立独立环境与锁定方式 |
| Node/npm | Node20.19.0，npm10.8.2，均可执行 | 前端工具可用；具体Vue/Vite依赖兼容仍需后续安装与构建验证 |
| uv/Git | uv0.11.2，Git2.45.1.windows.1 | 工具可运行，尚未进行安装/提交 |
| Docker | 首次引擎pipe不存在；20:55复核客户端/服务端均29.4.0，desktop-linux，OSType=linux | 当前引擎可连接；普通沙箱访问不足，需要相应执行权限。Mongo容器与协议仍未验证 |
| Mongo | PATH无mongod/mongosh；当前Python无pymongo；127.0.0.1:27017连接超时 | Mongo真库不可用性尚未由协议验证；后续需准备驱动和服务 |
| SQLite | Python标准库SQLite3.45.3 | 可用于明确选择的本地演示，未执行本项目仓储契约 |
| 浏览器自动化 | Playwright1.62.0经系统Edge完成本地HTML检查 | 可作为后续E2E的浏览器路径，但本项目E2E未运行 |
| 配套Chromium | Playwright要求revision1234，缓存只有1193 | 默认`chromium.launch()`配套文件缺失，后续选择Edge通道或准备匹配浏览器 |
| 参考仓库 | HEAD等于`211033c6785c29cbe79e053ebc5f3219e5f0051f`，分支main；`?? test/` | 与历史审查提交一致，但工作区有未跟踪目录，不可覆盖或清理 |

## 3. 工作区与改动边界

本环节开始时根目录为`docs/`、`outputs/`、`work/`、`AGENTS.md`、`README.md`。现有Python代码主要是历史后端测试草稿和架构图生成脚本；它们不代表TwoWorlds后端已实现。

不存在根级`.gitignore`、`pyproject.toml`、`uv.lock`、`package.json`或`package-lock.json`。旧依赖配置仍位于`outputs/twoworlds/backend/pyproject.toml`。

Git在项目内向上发现`F:\.git`，父仓库分支为`lesson-0002-component-request`。本轮只查询当前项目路径的status/ls-files，没有遍历或提交整个F盘，没有改变父仓库配置。

**后续建议：** T00.2在本项目目录明确建立独立Git边界，保留所有已有文件；实施前核对父仓库关系。不能直接在盘根仓库执行无范围的add、commit、reset、clean或push。这个建议尚未执行。

**T00.2.1后续更新：** 用户明确要求创建本地与GitHub仓库后，已在本目录建立独立.git并创建GitHub空私有仓库；父仓库没有修改。上段保留初查建议，当前执行情况见[仓库设置报告](repository-setup.md)。

参考仓库没有修改、切分支或清理。本次`status --short`只显示`?? test/`，其内容未作为本项目素材复制。

## 4. 已执行的工具检查

### 4.1 解释器与命令行

实际执行了以下命令：

```powershell
Get-Command python,py,node,npm.cmd,uv,git,docker,mongod,mongosh -ErrorAction SilentlyContinue
python --version
py --list-paths
node --version
npm.cmd --version
uv --version
git --version
```

| 工具 | 路径/结果 |
| --- | --- |
| python | D:\Python\python.exe，3.12.4 |
| py | C:\Windows\py.exe，默认C:\Python314\python.exe |
| node/npm | C:\nvm4w\nodejs\，20.19.0 / 10.8.2 |
| uv | D:\Python\Scripts\uv.exe，0.11.2 |
| git | C:\Program Files\Git\cmd\git.exe，2.45.1.windows.1 |
| docker | C:\Program Files\Docker\Docker\resources\bin\docker.exe，29.4.0 |
| mongod/mongosh | 本次Get-Command没有找到PATH入口；不能据此断言磁盘上完全没有安装 |

### 4.2 当前Python的包元数据

通过`importlib.metadata.version()`读取；这是版本元数据检查，不是所有包都能协作运行的证明。

| 包 | 当前全局解释器 | 旧草稿声明/备注 |
| --- | --- | --- |
| pip | 26.1.1 | 安装工具 |
| pytest | 9.0.2 | 与旧草稿一致 |
| ruff | 0.12.9 | 旧草稿为0.15.4，存在差异 |
| fastapi | 0.132.0 | 与旧草稿一致 |
| uvicorn | 0.41.0 | 与旧草稿一致，extras未单独验证 |
| pydantic | 2.12.5 | 与旧草稿一致 |
| httpx | 0.28.1 | 与旧草稿一致 |
| langgraph | 1.0.8 | 与旧草稿一致，实际图未运行 |
| pymongo | 当前解释器未安装 | 旧草稿为4.11.3 |
| playwright | 1.62.0 | 使用系统Edge通道验证成功 |
| Pillow | 12.3.0 | 架构图生成辅助，不是业务运行依赖 |

后续使用项目虚拟环境，不通过修改全局包来凑齐草稿版本。是否沿用旧锁定版本在T00.2/T00.3核对兼容后决定；本轮没有从网络查询或安装新版依赖。

### 4.3 Docker与本机Mongo条件

```powershell
docker context show
docker version --format 'Client={{.Client.Version}} Server={{if .Server}}{{.Server.Version}}{{end}}'
```

结果：`desktop-linux`；Client29.4.0，Server无版本，错误指出`dockerDesktopLinuxEngine`命名管道不存在。普通执行与扩展只读权限复核均得到同样结果，因此记录为“选定Docker引擎当前不可连接”，不宣称整个Docker未安装。

**20:55复核更新：** 用户指出当前可以连接后，重新检查。普通沙箱错误变为permission denied；扩展只读权限下`docker version`返回Client=29.4.0、Server=29.4.0，`docker info`返回OSType=linux、ServerVersion=29.4.0。当前结论更新为“Docker引擎可连接，普通沙箱有访问限制”。此前命名管道不存在是当次检查结果；本轮没有启动或重启Docker，也不推断是谁改变了服务状态。Mongo容器运行和数据库协议不因Docker可连接就自动算通过。

用Python socket对`127.0.0.1:27017`做2秒连接尝试，结果为TimeoutError。没有使用凭证连接其他地址，也没有Mongo协议ping成功证据。

Windows服务查询在普通环境受到Service Control Manager访问限制，不能据此判断系统服务是否存在。补充的27017监听查询没有产生条目，命令也未正常完成为成功结果，不作为“确定没有任何Mongo服务”的依据。

### 4.4 浏览器验证

配套浏览器注册文件显示：Playwright要求`chromium-1234`与`chromium_headless_shell-1234`，版本151.0.7922.34；本机缓存目录有1193而没有要求的1234。期望的默认Chromium可执行文件不存在。

系统Edge和Chrome可执行文件存在。实际以Playwright启动无界面Edge，创建临时页面并调用：

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True, timeout=12000)
    page = browser.new_page()
    page.set_content("<title>TwoWorlds environment check</title><h1>ready</h1>")
    print(browser.version)
    print(page.title())
    print(page.locator("h1").inner_text())
    browser.close()
```

实际输出：Edge156.0.4314.42；标题`TwoWorlds environment check`；h1为`ready`；浏览器探针退出码0。没有加载外部网页或实际游戏。

普通沙箱内的首次浏览器探针没有及时完成，已中止该次会话；扩展执行权限的本地探针通过。后续浏览器测试需要同等执行条件，不能把权限问题记录成应用错误。系统Chrome没有实际启动验证。

## 5. Git与参考版本核实

实际执行的只读命令包括：

```powershell
git --no-optional-locks -C 'F:\two-worlds-agent-game' rev-parse --show-toplevel
git --no-optional-locks -C 'F:\two-worlds-agent-game' rev-parse --is-inside-work-tree
git --no-optional-locks -C 'F:\two-worlds-agent-game' branch --show-current
git --no-optional-locks -C 'F:\two-worlds-agent-game' status --porcelain=v1 --untracked-files=normal -- .
git --no-optional-locks -C 'F:\two-worlds-agent-game' ls-files -- .
git --no-optional-locks -C 'F:\ai-agent-game\philoagents-course' rev-parse HEAD
git --no-optional-locks -C 'F:\ai-agent-game\philoagents-course' status --short
```

Git初次在普通权限下受到F盘父目录访问限制，扩展只读权限后查询成功。额外直接读取参考仓库`.git/HEAD`及其指向的分支文件，与Git返回的提交值一致。

## 6. 关键现有文件基线

在修改任何业务或草稿之前记录SHA256，用于确认本轮没有改动这些材料：

| 文件 | SHA256 |
| --- | --- |
| outputs/twoworlds/backend/tests/test_platform.py | `fffb377dc8057939b64e9cebc06c2db1e2ddf1c2faaa4d1c0dcf447461e8f54b` |
| outputs/twoworlds/backend/pyproject.toml | `1fddb6a5ce260a69aa063b05f792c7731b0f0a39e725e1f8803ac3da76baff2f` |
| work/generate_architecture.py | `4cd736f50ea6c4e3cd180514e4d6cd00965e962ec80b58386391d8d836441edc` |

## 7. 需要你学习和观察的点

1. **解释器与虚拟环境：** 机器有多个Python；`python`与`py`默认不一样。独立环境可以让项目依赖不受全局包变化影响。
2. **客户端与服务端：** `docker --version`可用不等于Docker引擎可连接；装了数据库驱动也不等于数据库运行。
3. **Git的向上查找：** 当前文件夹没.git时，Git会继续寻找父目录；所以先确认根目录，再做版本操作。
4. **浏览器包与浏览器本体：** Playwright包安装成功，配套浏览器仍可能缺失；本机Edge可以通过明确通道使用。
5. **检查与产品验证：** 本地HTML可运行只证明浏览器工具链可用，不证明TwoWorlds游戏可以运行。

你可以在项目终端运行`python --version`、`py --list-paths`、`node --version`和`docker version`，对照本报告观察；这些命令不会启动或安装数据库。Git相关命令只用上面限定范围的只读形式。

## 8. 本环节出口与后续

T00.1的完成条件是“已如实核实并记录环境与工作区”，不是“所有环境组件已经准备完毕”。本轮没有应用测试、仓储测试、前端构建或E2E通过记录。

报告写入后执行Python文档检查：5份新增/更新文档的本地链接和代码块结构通过；第6节三个现有源码/配置文件SHA256与检查前一致；确认没有创建backend、frontend或项目.git，交接状态已记录为T00.1完成待观察。

下一建议为T00.2：整理独立Git边界、工程目录、Python3.12包布局与依赖策略。Docker/Mongo准备、配套Chromium安装与测试契约迁移分别列入后续需要时处理，不在本环节顺带执行。

**本环节完成后停止，等待用户看完报告并明确要求继续。**
