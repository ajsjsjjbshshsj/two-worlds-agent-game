# 测试目录

2026-10-29：`content/test_schema.py`有74个测试通过，T01.2.1的`content/test_loader.py`新增36个加载测试通过。全量148项，实际110通过、38因缺后续实现失败。下面38专指contracts，不是全部测试。Schema与加载器阅读入口分别见[Schema报告](../../docs/reports/content-schema.md)、[加载器报告](../../docs/reports/content-loader.md)。

T00.3已将历史平台测试的意图修订为`contracts/`下的可执行要求。它们不是已通过的产品测试：目前应用工厂和SQLite仓储尚未实现，执行会明确失败；没有skip、xfail或假服务把它们变绿。

## 建议阅读顺序

1. [support.py](contracts/support.py)：从`command()`看请求，从`Platform.accept()`看`receipt + save`响应，再看两种不同的通关轨迹。
2. [test_commands.py](contracts/test_commands.py)：原请求重试、同ID改内容、另一身份同ID、两应用竞争。
3. [test_identity.py](contracts/test_identity.py)：恢复密钥与期限会话分离、客户端不能指定身份、登出撤销。
4. [test_platform.py](contracts/test_platform.py)：两剧本、角色隔离、分享、存档恢复、WS和示例NPC要求。
5. [conftest.py](contracts/conftest.py)：如何用真实应用和临时数据库装配测试，缺实现为何失败。

`client_factory`只延迟导入尚未实现的应用/仓储，让pytest先完整收集测试。调用工厂后若缺少这两个已知模块，使用pytest.fail报告；其他依赖/导入错误仍原样暴露。工厂不会自行提供业务实现，也不会连接Mongo、调用付费模型或外部追踪。

## 自己运行

在项目根目录执行：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/contracts --collect-only -q
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_commands.py -k old_version_retry -q --tb=short --basetemp=work/pytest-local
```

第一条应列出38个参数化后的测试条目；它只证明可收集。第二条目前应失败并打印`契约尚无业务实现（T04/T08）`；这是刻意保留的未实现信号。以后T04/T08完成后，该检查才会进入实际HTTP行为断言。完整执行在第二条中去掉`-k old_version_retry`并将文件路径改成`backend/tests`，现阶段仍是红色。

`work/pytest-local`是专用临时目录，pytest运行时会清空重建，不要在其中存学习笔记；并行测试应选择不同临时目录。本轮沙箱默认Temp无法创建pytest目录，因此显式使用项目内目录；不是更改业务行为。若控制台中文乱码，可先执行`$env:PYTHONIOENCODING = 'utf-8'`。

pytest采用importlib导入方式，依赖安装后的`twoworlds`包，不设置旧稿的`pythonpath=["."]`。临时SQLite文件由pytest提供，每例隔离；竞争测试明确开两个应用/仓储实例，重启测试先关闭旧应用再重建。真正的数据库事务、故障注入、独立连接与Mongo双进程测试仍在T04/T05补齐，线程竞争本身不证明数据库原子性。

## 覆盖边界

这38例继承并细化旧9个函数的主要测试意图，不等于全部67项QA都已编码。会话到期/限频/5会话窗口、512回执容量、数据库故障、版本升级、Provider输入捕获、受保护媒体与浏览器播放/缓存等，在对应任务补齐。当前没有真实API、数据库、图像/音频或AI行为通过证据。

来源、逐项迁移关系、固定的最小线协议及执行证据见[T00.3基线修订报告](../../docs/reports/baseline-changes.md)。`outputs/`原稿保持原样，仅本目录继续开发。
