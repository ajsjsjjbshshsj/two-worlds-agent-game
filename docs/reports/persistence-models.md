# T04.1 · 持久化聚合模型与严格序列化

2026-11-10。基于已合并 T03.2 的 codex/bootstrap，本环节只定义持久化数据边界，不实现 SQLite 事务、身份 API 或房间 API。

## 本轮交付

- domain/persistence.py：不可变 AccountRecord、SessionRecord、PairRecord、SaveRecord、DialogueTurn、CommandReceipt。
- ports/repository.py：适配器无关的仓储 Protocol 与稳定错误类型。
- storage/serialization.py：严格、确定性 JSON 编解码；拒绝重复键、NaN/Infinity、超大文档和额外字段。
- tests/domain/test_persistence.py：覆盖聚合版本绑定、回执顺序/唯一性、对话与会话上限、UTC 时间、自加入拒绝及严格反序列化。

## 重要约束

Save 是一个聚合：GameState、PublicHistory 与 SaveRecord 的 script_id、script_version、version 必须一致。后续 CAS 必须一次替换整个聚合，不允许分别保存状态、历史和回执。

回执以 (actor_id, request_id) 为唯一键；不同玩家可使用相同 UUID。accepted_version 必须严格递增且不超过 Save.version。最多保存 512 条回执；达到上限后由仓储明确拒绝新命令，不能静默删除仍可能被客户端重试的回执。

对话最多每角色 20 轮。Account 最多 5 个会话摘要。时间必须带时区并统一规范为 UTC。这里只存摘要，不存恢复密钥或会话 token 明文。

PairRecord 只定义配对数据形状；成员唯一、邀请摘要唯一、占位条件与过期判断必须由后续数据库事务约束，Pydantic 模型不能代替并发安全。

## 验证状态

当前执行环境无法解析 GitHub 主机，且没有项目工作树；因此没有声称已运行 pytest 或 Ruff。测试代码已加入 PR 分支，待可用 Python 3.12 项目环境执行：

```powershell
.\\backend\\.venv\\Scripts\\python.exe -m pytest backend/tests/domain/test_persistence.py -q --basetemp=work/pytest-t041
.\\backend\\.venv\\Scripts\\python.exe -m ruff check backend/src/twoworlds/domain/persistence.py backend/src/twoworlds/ports/repository.py backend/src/twoworlds/storage/serialization.py backend/tests/domain/test_persistence.py
.\\backend\\.venv\\Scripts\\python.exe -m ruff format --check backend/src/twoworlds/domain/persistence.py backend/src/twoworlds/ports/repository.py backend/src/twoworlds/storage/serialization.py backend/tests/domain/test_persistence.py
```

未执行：SQLite 事务、文件重开、唯一索引、CAS 竞争、邀请竞争、账户原子更新、完整后端契约测试及真实 Mongo 验证。这些属于 T04.2/T05，不以本轮模型测试代替。

## 阅读顺序

1. domain/persistence.py：先看 SaveRecord 如何把状态、历史与版本绑定。
2. ports/repository.py：再看 SQLite/Mongo 需要共同实现哪些操作。
3. storage/serialization.py：最后看数据如何安全进出 JSON。
4. tests/domain/test_persistence.py：对照边界条件与拒绝行为。

本轮停止于 T04.1 学习检查点，等待用户审查 PR 后继续。
