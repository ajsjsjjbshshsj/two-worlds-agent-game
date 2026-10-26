# T00.3 · 旧测试契约修订

日期：2026-10-26。范围为正式测试目录、必要测试依赖、最小接口定名与来源记录；没有开始T01内容加载、规则、仓储、身份服务、前端或AI实现。

## 1. 从哪里迁入

历史来源为[旧test_platform.py](../../outputs/twoworlds/backend/tests/test_platform.py)，保留原文件；正式测试只有[backend/tests](../../backend/tests/README.md)这一套。原稿9个函数重写为3个文件、38个含参数化的测试条目。数量增加来自不同边界/结局的拆分，不代表完成了38项功能。

| 历史函数/假设 | 本轮处理 | 正式位置 / 后续QA |
| --- | --- | --- |
| account助手返回永久token | display_name创建；独立recovery_key与session.token；恢复新会话、同名不认领、登出 | test_identity.py；QA-I01～I04的一部分 |
| test_private_projection_and_forbidden_access | 动态取本人发现的线索文本，检查两角色响应无对方文本；外人读写/回执/voice无权 | test_platform.py；QA-P01部分 |
| test_asymmetric_complete_story | 删除731/248/星名与六步断言；独立灯塔/星轨轨迹、两种结局、灯塔分歧改选 | support.py与test_platform.py；QA-G01/G05/G07部分 |
| test_idempotency_and_conflicting_payload | args、receipt+save；旧版本重试返回当前投影；指纹包括原版本；另一actor同ID独立 | test_commands.py；QA-C02～C05部分 |
| test_concurrent_commands_have_one_winner | 同SQLite文件、两个应用实例；不同请求200/409，相同请求两端确认但仅一条新增版本 | test_commands.py；QA-C01/C05部分；T04/T05再验证数据库细节 |
| test_room_admits_only_one_partner | 两应用竞争B位，仅一人成功；赢家重复加入仍是原房间 | test_platform.py；QA-R01/R02部分 |
| test_independent_scripts_and_pair_saves | 同房同剧本唯一档；跨剧本/房间ID、版本、回执隔离，同actor同ID可在另一档使用 | test_platform.py；QA-S01/S04部分 |
| test_restart_and_cross_device_recovery | 关闭旧lifespan、重建应用、用恢复密钥换新会话；原身份/档/角色/回执保持 | test_platform.py；QA-I03/S02部分；不是实际跨设备验证 |
| test_websocket_auth_private_snapshots_and_reconnect | auth首帧显式type；允许Origin；A/B投影、重连最新版本、外人无快照且4404 | test_platform.py；QA-W01/W02部分；心跳/过期/迟到消息待T12 |
| test_ai_dialogue_cannot_mutate_game_and_is_private | talk.question；本人对话/示例标识；public/scene/devices不变；伙伴私聊不可见；voice disabled | test_platform.py；QA-A01/A03/A06部分；Provider输入捕获待T14 |

另外补入：严格动作参数与客户端role拒绝、未扫描安装/提前发车/无电维修/超预算不写入、未发现者不能分享、未满员不能游戏或NPC写入。这些仍是待实现的要求。

## 2. 固定的接口与取舍

- 线协议补充在[架构文档7.3与10.1](../03-技术架构与数据接口.md)：身份/会话/邀请字段、204登出、数组目录、本人回执查询，personal.clues/dialogue/devices与public.clues/ending。
- 动作沿用文档02，B航道图使用sea_chart；通用share_clue使用clue_id，talk使用question。两条通关轨迹不要求分享，也不固定最终version=6；每次真正接受的变化仍需恰好增加一个版本。
- 文档02补齐最小验收初态，避免第一步配置恰好与初态相同导致无变化错误。内容JSON/Schema仍由T01/T09实现。
- 测试装配使用api.app.create_app与storage.sqlite.SQLiteRepository，详见架构10.1。不会为了能运行测试先写假应用；缺失实现明示失败，不用skip/xfail/importorskip。
- FastAPI0.132.0与httpx0.28.1仅加入开发依赖，为TestClient装配所需；当前运行依赖仍为空。实际API实现时再提升FastAPI为运行依赖。间接版本由uv.lock固定，不使用全局已安装包。
- 整个请求复用含request_id/expected_version/kind/args；先查本人已接受回执，再判断旧版本。同ID改kind/args/原版本都冲突，另一身份或另一存档的同ID独立。

## 3. 验证记录

实际使用Python3.12.4。工程检查与产品行为状态分别记录：

| 命令/检查 | 实际结果 | 能证明什么 |
| --- | --- | --- |
| `uv add --project backend --dev fastapi==0.132.0 httpx==0.28.1 ...` | 离线缓存缺FastAPI；随后从公共PyPI安装并锁定成功，共22包 | 测试依赖已落入本项目环境，不是业务API完成 |
| `python -m pytest backend/tests --collect-only -q` | 38个条目收集成功，退出0 | 测试可发现、测试依赖/包导入可用 |
| `python -m pytest backend/tests -q --tb=line --basetemp=work/pytest-t00-3-full --junitxml=work/t00-3-results.xml` | 38 failed、0 errors、0 skipped，退出1；均为缺T04/T08两个模块 | 正确暴露未实现；尚未进入HTTP行为断言，不能证明断言已有效检验业务 |
| 全新`work/contracts-clean/.venv`按锁离线sync，隔离导入、pytest收集 | 22包安装成功，导入本项目，38条目收集成功 | 不依赖旧虚拟环境或全局Python包 |
| `uv pip check --python work/contracts-clean/.venv/Scripts/python.exe --offline` | 22包依赖一致，通过 | 元数据兼容性；不是整个Web栈功能验证 |
| `uv lock --project backend --check --offline` | 22包锁一致，通过 | pyproject与锁文件匹配 |
| `ruff check backend/src backend/tests`、`ruff format --check backend/src backend/tests` | 检查通过，16个Python文件格式正确 | 语法/静态规范通过 |
| `python work/check_t00_3.py` | 16份Markdown、90个本地链接、JSON/代码块通过；22个测试函数；JUnit确认38失败、0错误、0跳过；原稿哈希不变 | 产物完整性与失败分类，不是产品通过 |

干净环境随后也实际执行完整契约：使用`--basetemp=work/pytest-t00-3-clean-run`得到同样的38 failed、1 warning（退出1），JUnit确认没有setup errors或跳过。失败全部来自缺实现检查，后续行为断言尚未运行。

初次直接执行出现38个setup errors，原因是沙箱默认Temp无法创建pytest目录；改用项目内专用basetemp后明确变成上述38个未实现失败。没有把环境错误当作预期业务失败。专用临时目录由pytest清空重建，不存笔记；并行执行用不同目录。

干净环境首次sync被沙箱拒绝读取uv构建缓存；在扩展执行权限下用相同锁文件**离线**同步成功。TestClient导入出现Starlette0.52.1引用AnyIO4.15.1旧BlockingPortal别名的DeprecationWarning，未屏蔽；它不阻断收集，后续真实API/WS测试仍需确认运行兼容性。

旧测试SHA256保持`fffb377dc8057939b64e9cebc06c2db1e2ddf1c2faaa4d1c0dcf447461e8f54b`；旧pyproject保持`1fddb6a5ce260a69aa063b05f792c7731b0f0a39e725e1f8803ac3da76baff2f`。没有修改业务源码；本轮未重建T00.2.2的wheel，backend/dist旧产物不代表本次测试归档。

本轮文档链接/代码块/JSON、旧稿哈希与JUnit分类的收尾检查由本地一次性脚本`work/check_t00_3.py`记录；它与XML、临时目录、干净验证环境均在Git忽略范围，正式来源与结论保留在本文。本轮只保存本地，不推送或发布。

## 4. 尚未覆盖的实现级验收

T01/T02/T03补内容Schema/可达性、纯规则输入不变、完整投影与专用测试标记（HTTP/WS/AI/媒体各通道）、公开回顾。T04/T05补仓储故障注入、512额度、独立客户端/进程、真实Mongo、内容版本绑定。T06/T07补期限、摘要存储、5会话窗口、限频、邀请失效/刷新及恶意字段。T08补全错误码、受保护媒体及容量/API边界。T12补超时/Origin/过期撤销、心跳、在连接中的推送及恢复。T14捕获真实Provider测试替身的输入、超时/无效输出/生成中冲突，不联网计费。浏览器实际画面、音频、静音、字幕、去重与手机行为在T11～T16验证。

## 5. 学习检查点

先看support.py的command与Platform.accept，再看test_commands.py首例：A检查日志获得v1；B检查航道图推进至v2；A用原v0请求重试，收到accepted_version=1、duplicate=true和自己的v2快照。这同时解释“确认已成功”与“显示当前状态”为何需要分开。

再对照旧稿的同ID跨身份409，理解新稿为何允许B使用相同ID执行自己的合法操作。最后读conftest，理解收集测试、打开真实应用、运行行为断言是三个不同阶段。

完成本环节后停止。建议下一环节T01：内容版本、Schema与加载；不自动执行，也不实现后续业务来消除本轮预期红色测试。
