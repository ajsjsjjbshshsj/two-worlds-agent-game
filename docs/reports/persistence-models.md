# T04.1 · 持久化聚合模型与严格序列化

2026-11-10 · 从 PR #10 的 `3440088` 复核，目标分支基线为 `c7fe2f0`。提交仍在 `codex/t04-sqlite-persistence` 分支。[PR #10](https://github.com/ajsjsjjbshsj/two-worlds-agent-game/pull/10)

## 复核结果

- 六种记录使用冻结模型。已有实例也要重新验证，GameState 和 PublicHistory 通过普通字段重建。时间仅接受带时区的 datetime 或 ISO 字符串，统一为 UTC，拒绝数字时间戳及转换溢出。邀请到期时间必须晚于建房时间。对话答案使用现有 Text 的 2000 字符存储上限，并允许架构约定的 fallback 标记。[persistence.py](../../backend/src/twoworlds/domain/persistence.py)
- Save 将状态和公共历史绑定到同一剧本 ID、内容版本和接受版本。回执在单个存档内按 `(actor_id, request_id)` 唯一，两个玩家可以使用同一 UUID。接受版本唯一、严格递增，且不超过当前版本。每档最多 512 条回执，每角色最多 20 轮对话，每账户最多 5 个会话摘要。
- 公共历史模型在读档时验证保留窗口、序号、版本顺序及事件与里程碑的版本对应关系。剧本引用、公开文字来源和世界规则由持有固定剧本版本的领域入口校验。[recap.py](../../backend/src/twoworlds/domain/recap.py)
- JSON 拒绝任意层级的重复键、NaN、正负 Infinity、指数溢出和无效 Unicode。两端都按 UTF-8 字节计量，上限为 1,000,000 字节。写入先重验模型，再确定性编码。读取从普通 JSON 数据重建整个模型。[serialization.py](../../backend/src/twoworlds/storage/serialization.py)
- 仓储端口补清唯一建档、邀请占位、按存档与玩家查找回执以及整档 CAS 的契约。[repository.py](../../backend/src/twoworlds/ports/repository.py)
- 专项测试用真实灯塔命令生成存档，验证中文、emoji、带偏移量的时间、公共历史及两个角色的回执能同时往返。[test_persistence.py](../../backend/tests/domain/test_persistence.py)

## 实际验证

Python 3.12.4。PR 草案原有 7 项专项均通过。首次扩充用例复现了 17 个失败，包括接受坏历史和未重验的子记录、非有限数字、无效 Unicode 和 UTC 溢出。

| 检查 | 结果 |
| --- | --- |
| 持久化专项 | 45 通过，原 7 项加新增 38 项 |
| 全部领域 | 297 通过 |
| 全部内容 | 191 通过 |
| 全量后端 | 488 通过，38 失败，0 errors，0 skipped，1 条既有弃用警告 |
| Ruff 与格式 | 通过，44 个 Python 文件 |
| 离线锁与安装依赖 | 通过，22 个包 |

逐项比较 JUnit，38 个失败的用例和报错均与 T03.2 一致，涉及尚未实现的 API/SQLite。另用直接调用确认 NaN、正负 Infinity 写入被拒绝，合法的补充平面 Unicode 转义能够读取。

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain/test_persistence.py -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t041-persistence --junitxml=work/t041-persistence.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t041-domain --junitxml=work/t041-domain.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t041-content --junitxml=work/t041-content.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t041-all --junitxml=work/t041-all.xml
.\backend\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/hatch_build.py
.\backend\.venv\Scripts\python.exe -m ruff format --check backend/src backend/tests backend/hatch_build.py
uv lock --project backend --check --offline --cache-dir F:/two-worlds-agent-game/work/uv-cache
uv pip check --python backend/.venv/Scripts/python.exe
```

## 学习检查点

先看 SaveRecord 的版本绑定与回执约束，再对照 JSON 编解码及真实命令往返测试。T04.2 建议使用两个独立 SQLite 连接验证同版本只有一次 CAS 成功，随后验证聚合与回执同时落盘、失败回滚及文件重开恢复。真实 SQLite、Mongo、身份 API 和 WebSocket 验收仍待后续。当前停在 T04.1，等待审查。
