# T03.2 · 线索分享、公共事件与完成回顾

2026-11-10。以已合并的 PR #8 和远端 `codex/bootstrap` 的 `e612882d421000e7cef872fd8913d44855ef3b61` 为基线。交付分支为 `codex/t03-2-sharing-recap`，目标为 `codex/bootstrap`。

## 分享命令

调用 `apply_command(state, script, actor_role, {"kind": "share_clue", "args": {"clue_id": "a_maintenance_log"}})`。该动作由引擎定义。剧本动作不能占用 `share_clue` 的 ID 或 kind。

规则验证严格的 clue_id、角色归属、发现状态、shareable、重复分享及游戏完成状态。未知、伙伴或未发现线索统一返回 `CLUE_NOT_DISCOVERED`。本人已发现但禁止分享时返回 `CLUE_NOT_SHAREABLE`。重复分享返回 `NO_STATE_CHANGE`。失败时保留原状态与版本。

成功时复制冻结状态并将共享 ID 排序，版本加一。命令只返回一条 `clue_shared` 公共事件，subject_id 指定线索，text 等于当前剧本的 `ClueDefinition.text`。A/B 的 `public.clues` 都显示该 `{id,text}`，本人发现集合和伙伴的 `personal.clues` 不受影响。动作参数 choices 只包含本人当下可分享的线索。

## 公共历史与回顾

| 值 | 字段和职责 |
| --- | --- |
| PublicEvent | version、ordinal、kind、text。按允许的公开类型生成独立展示记录 |
| PublicMilestone | version、ordinal、kind、subject_id。结构化保留分享、场景切换、信号锁定、时钟修复、航道确认及共同结局 |
| PublicHistory | script_id、script_version、through_version、event_count、events、milestones。可作为未来 Save 的冻结值 |
| PublicRecap | milestones、ending_id、summary。里程碑展示文字来自指定线索、场景标题、确定的进度文案或结局总结 |

每次命令被接受后，用其新版本和事件批调用 `append_public_history`。accepted_version 必须等于 through_version 加一，所有事件必须属于该版本。私有事件无论有多少都不会占公共序号或窗口容量。公共事件按规则输出顺序获得全局递增的 ordinal，最近 30 条进入窗口。

公共类型白名单包含 clue_shared、scene_changed、fact_changed、vote_changed、observation 和 game_completed。公共事实需校验 FactDefinition.audience 和值类型，公共观察需匹配剧本声明的公共观察效果。分享事件必须引用允许分享的线索并携带指定文本。展示记录只使用公开声明和固定文案。历史读取校验绑定、窗口长度和序号、里程碑引用与文本来源。

里程碑独立于窗口追加，最多 64 条，满时拒绝整个追加。回顾读取结构化里程碑与已审核的公开文本，结局必须匹配历史中已完成的结局。未完成时可显示公共时间线，结局和总结为 null。角色装置、私人观察、私聊和完整世界都不作为回顾生成输入。

`project_save(state, script, role, public_history=None)` 保持原三参数调用。缺省时 events 与 recap.milestones 为空，summary 为 null，已完成状态仍在 public.ending 返回确定的结局。提供历史时核对版本、共享集合、场景、公开进度和结局，再输出 A/B 相同的公共内容。

真实引擎轨迹从发现线索、分享、锁定、供电维修到确认航道。A 在 B 投票前真实改选 38 次，B 最后与 A 一致。两条轨迹都完成于版本 49，共记录 51 条公共事件。截断后最早保留事件来自版本 24，公共回顾仍保留完整的 8 条里程碑。

- `guide_now` 使用“立即引航”的 summary_template。两端灯光划过海雾，船循着信标靠岸。
- `wait_tide` 使用“等待下一次潮汐”的 summary_template。信标继续守候，直到海面渐平。

## T04 存档边界

未来 Save 以 `PublicHistory(script_id=..., script_version=...)` 初始化历史，与初始状态同为版本 0。应用层从同一存档取旧状态和旧历史，调用命令后将新版本与已接受事件交给 `append_public_history`。状态、版本、历史和已接受回执进入同一次 CAS。CAS 或历史追加失败时丢弃整组候选。只有 CAS 成功后才可广播，否则客户端可能收到读档无法恢复的事件。

当前是纯领域值和函数。可信调用方负责提供同一存档的接受结果。跨存档归属、CAS、回执幂等和读取恢复属于 T04。QA-P02、QA-P03 只记录纯领域证据。QA-P01 完整通道、QA-P04、HTTP/WS/AI、正式媒体及 M1 整体验收仍待后续。

## 学习与验证

1. 从命令分流和 `_share_clue` 看分享权限及版本变化。[engine.py](../../backend/src/twoworlds/domain/engine.py)
2. 从 `append_public_history` 看窗口、白名单与里程碑，再看 `build_public_recap`。[recap.py](../../backend/src/twoworlds/domain/recap.py)
3. 对照 public 历史和个人 choices 的组装。[projection.py](../../backend/src/twoworlds/domain/projection.py)
4. 阅读真实投票溢出测试和隐私标记测试。[test_recap.py](../../backend/tests/domain/test_recap.py)

新增 recap.py、test_recap.py 与本报告。更新 engine.py、errors.py、projection.py、原有灯塔与投影测试中受新增契约影响的断言，以及 README、后端说明、技术架构、开发任务、测试验收和交接。正式剧本、内容 Schema、加载器及锁文件沿用基线。

| 检查 | 结果 |
| --- | --- |
| 新增分享与回顾测试 | 29 通过 |
| 全部领域测试 | 252 通过 |
| 全部内容测试 | 191 通过 |
| 全量后端 | 443 通过、38 失败、0 errors、0 skipped、1 条既有弃用警告 |
| Ruff 检查和格式 | 通过，40 个 Python 文件 |
| 离线锁与安装检查 | 通过，22 个包 |

从 Python 3.12.4 独立工作树运行以下命令。JUnit 对比确认 38 项失败的用例和消息与 PR #8 一致，涉及尚未实现的 `twoworlds.api.app` 与 `twoworlds.storage.sqlite`。

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain/test_recap.py -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t032-recap --junitxml=work/t032-recap.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/domain -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t032-domain --junitxml=work/t032-domain.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t032-content --junitxml=work/t032-content.xml
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t032-all --junitxml=work/t032-all.xml
.\backend\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/hatch_build.py
.\backend\.venv\Scripts\python.exe -m ruff format --check backend/src backend/tests backend/hatch_build.py
uv lock --project backend --check --offline --cache-dir F:/two-worlds-agent-game/work/uv-cache
uv pip check --python backend/.venv/Scripts/python.exe
```

完成后停在 T03.2，等待审查。下一阶段 T04 负责 Save 值、SQLite 演示仓储、原子 CAS 和幂等回执的仓储契约。
