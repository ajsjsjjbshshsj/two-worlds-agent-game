# T01.1 · 内容结构与静态校验

日期：2026-10-27。本轮只定义ScriptVersion、字段与引用校验，不读取剧本目录、不发布版本、不执行游戏规则或生成媒体。用户已明确要求执行这个子环节。

## 设计与实施边界

采用Pydantic模型，入口为`ScriptVersion.model_validate(data)`或`model_validate_json(text)`，错误为`ValidationError`。相比手写字典检查，它能统一字段类型、多余字段拒绝和JSON Schema导出；相比单独维护JSON Schema再写Python转换，它减少两份契约偏差。Pydantic从已有锁定的2.14.1提升为直接运行依赖，不另选新版本。

内容分为metadata、initial_state、scenes、facts、clues、devices、actions、endings、npc、media和presentation。每类ID在自身命名空间唯一，A/B角色固定；动作参数有类型与允许值，前置条件/效果使用判别字段和有限原语，禁止字符串表达式与任意Python。复杂原语在T02/T09按实际机制扩展并测试，本轮不建立通用脚本语言或执行器。

动作与设备的引用，以及场景转换、事实、线索、结局、角色场景和媒体引用在整份文档级校验。设备初值写在设备字段定义，事实初值写在事实定义；initial_state指定起始场景，并要求发现、分享、投票为空且未完成。容器使用tuple便于保持定义稳定；这不替代T01.2的版本发布/文件不可覆盖保护。

媒体必须声明版本、角色范围、场景/事实条件、相对资源路径、替代文字、来源与许可；短叙事音频还要字幕全文。角色场景不能引用另一角色专属素材。这里的public表示房间两角色可见，不等于可直接放进互联网公开目录；实际读取权限仍在T03/T08实现。只检查声明，实际文件、许可有效性和素材质量未验证。

结构可达性只依据next_scene_ids检查场景图，不能证明动作条件可满足、双方必须参与或所有游戏状态可解；这些由T02/T09纯规则轨迹与后续试玩验证。公开元信息由独立ScriptMetadata模型提供，不包含规则、私线索或媒体清单；作者仍须审核简介文字是否带秘密。

## 本轮步骤与文件

- [x] 先写`backend/tests/content/test_schema.py`及最小测试专用JSON，验证合法字段、严格类型、重复/错误引用、有限原语与媒体边界；运行确认缺少Schema实现。
- [x] 实现`backend/src/twoworlds/content/schema.py`的结构与局部校验、`_references.py`的整份内容引用校验；不做loader。
- [x] 在独立项目环境中运行本轮测试、锁检查与Ruff；全量保留原38个未实现契约；不修改它们以变绿。
- [x] 记录实际结果、阅读顺序和复现命令；更新交接后停止。

测试专用最小内容只演示协议，不是《跨时灯塔》正式故事；其媒体路径与许可是明确的测试标记，不构成实际素材交付。

T01后续：T01.2实现按id+version安全加载、灯塔正式四场景内容与不可变发布约束。本轮不自动执行。

## 执行证据与学习说明

| 检查 | 实际结果 |
| --- | --- |
| 首轮Schema测试（实现前） | 60 failed；首例明确ModuleNotFoundError，缺content.schema |
| 首次实现后 | 60 passed |
| 补充严格类型与场景边界测试 | 73 passed、1 failed；提示等级True被当作1接受 |
| 改为严格整数后的本轮测试 | 74 passed，无警告；JUnit为work/t01-1-schema-results.xml |
| 全量backend/tests | 74 passed、38 failed、0 errors、0 skipped；旧38项均缺api.app/storage.sqlite，保留既有Starlette/AnyIO弃用警告 |
| Ruff检查/本轮格式检查 | 通过；未格式化或改写原有三份中文注释文件 |
| uv lock --check / uv pip check | 锁一致；项目环境22包依赖元数据兼容 |
| 全新无开发依赖的运行环境 | work/schema-runtime/.venv离线安装6包；无FastAPI/pytest，隔离模式可校验测试JSON并导出JSON Schema，6包依赖检查通过 |

Pydantic加入依赖时普通沙箱阻止uv更新临时程序PE资源；相同离线命令在扩展权限下完成，实际版本仍为已有2.14.1。没有联网、模型调用或外部内容上传。

原有三份注释文件的SHA256分别保持：support.py=`d43857d3a483b7830297164969979787b80da3972fc42c7bb715ed59da6e7690`、test_commands.py=`0dc8ffe3b254dd73b37cdb75deef0b5d4bf35d5b16e15783832536dcaf195073`、test_platform.py=`97a207e01790a3496fa6eed5c8aae79c0a98907bd9d2f265d2c91e8990813585`。交接文件的原有中文注释记录也保留。

收尾检查：17份Markdown、105个本地链接、JSON示例/代码块通过；JUnit核实112项中74通过、38个缺实现失败、0错误/跳过。没有改动原有三份注释文件内容或它们的暂存状态。

旧dist未重建，不代表本轮归档。工作目录中的JUnit、运行验证环境和JSON Schema导出均被Git忽略；本轮不提交或推送，避免混入另一轮尚未提交的注释。

## 怎么阅读和自己验证

1. 先看[最小测试内容](../../backend/tests/content/fixtures/minimal.json)，认识metadata、角色、场景与媒体。它不提供真实文件，不是产品剧本。
2. 看[schema.py](../../backend/src/twoworlds/content/schema.py)：先读ScriptVersion和ScriptMetadata，再读MediaAsset与Condition/Effect，最后读局部校验器。
3. 看[_references.py](../../backend/src/twoworlds/content/_references.py)的validate_references：先按ID建立表，再检查跨对象引用、场景图和角色媒体范围。
4. 看[test_schema.py](../../backend/tests/content/test_schema.py)：合法输入、改坏一个字段、断言拒绝；这些测试真实执行Schema，不是mock。

例子：媒体b_voice声明只给B；如果A的演出引用b_voice，错误会带presentation.opening.a的位置和audience原因。这里拒绝的是错误内容声明；真正的HTTP媒体读取鉴权仍待T08。

在项目根目录执行：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -q
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/content -k role_cannot_reference_partner_media -v
```

第一条应显示74 passed，第二条验证“错误引用被拒绝”这一条行为。没有游戏服务启动地址。Schema也可以在已安装本项目的Python中直接使用：

```python
from pathlib import Path
from twoworlds.content.schema import ScriptVersion

text = Path("backend/tests/content/fixtures/minimal.json").read_text(encoding="utf-8")
script = ScriptVersion.model_validate_json(text)
print(script.metadata.title)
```

ScriptVersion包含服务端秘密，不能整体发送给客户端或NPC；目录只使用script.metadata。数字/布尔/文字不相互猜测转换，多余字段拒绝；校验通过后的模型冻结，后续游戏存档应新建独立可演进状态，不能修改内容定义本身。
