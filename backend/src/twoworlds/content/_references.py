"""已通过字段校验的整份内容引用检查；不推演实际玩法状态。

这是第二层校验：schema.py 保证每条声明自身合法，本文件检查声明之间的指向
关系——ID 是否存在、归属角色是否一致、媒体对该角色是否可见、场景图是否可达。
输入一定是已通过 ScriptVersion 字段校验的对象，所以这里只做"引用层"判断。
"""

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    # 仅供类型标注：运行时 schema 在校验器里延迟导入本模块，这里避免循环导入
    from .schema import ContentModel, ScriptVersion

# 泛型约束：_index 要服务场景/事实/线索等所有定义，它们的共同点是都有 id
Item = TypeVar("Item", bound="ContentModel")


def _index(items: tuple[Item, ...], location: str) -> dict[str, Item]:
    """把"带 id 的定义序列"变成 id→对象 的字典，同时拒绝重复 id。

    location 只用于报错定位（如 "scenes"、"actions.tune.parameters"），
    让内容作者知道是哪个命名空间出了问题。
    """
    result = {}
    for item in items:
        if item.id in result:
            raise ValueError(f"{location}: duplicate id {item.id}")
        result[item.id] = item
    return result


def _require(identifier: str, items: dict, location: str):
    """引用必须存在；存在则返回被引用的对象，方便调用方继续取它的字段。"""
    if identifier not in items:
        raise ValueError(f"{location}: unknown reference {identifier}")
    return items[identifier]


def validate_references(script: "ScriptVersion") -> None:
    """检查整份内容的跨表引用。顺序固定：先建全部索引，再逐段查引用。"""
    # 先把七个顶级命名空间全部建好索引：任何引用检查开始前索引必须齐全，
    # 否则"引用了还没建索引的集合"会被误判成未知引用
    scenes = _index(script.scenes, "scenes")
    facts = _index(script.facts, "facts")
    clues = _index(script.clues, "clues")
    devices = _index(script.devices, "devices")
    actions = _index(script.actions, "actions")
    endings = _index(script.endings, "endings")
    media = _index(script.media, "media")
    # 设备字段是二级命名空间：devices.<id>.fields.<field_id>
    fields = {
        key: _index(device.fields, f"devices.{key}.fields")
        for key, device in devices.items()
    }

    def device_field(device_id, field_id, location):
        # 先确认设备存在，才能安全访问 fields[device_id]；顺序反了会抛 KeyError
        _require(device_id, devices, location)
        return _require(field_id, fields[device_id], location)

    def conditions(items, location):
        """三种谓词共用：每个引用都要存在，比较值还要与目标声明同类型。"""
        for condition in items:
            if condition.kind == "fact":
                fact = _require(condition.fact_id, facts, location)
                # 类型也必须一致：False 与 0 值相等，但不是同一个事实取值
                if type(condition.equals) is not type(fact.initial_value):
                    raise ValueError(f"{location}: fact value type mismatch")
            elif condition.kind == "clue":
                _require(condition.clue_id, clues, location)
            else:
                field = device_field(condition.device_id, condition.field, location)
                # 比较值必须落在字段的选项白名单里，且类型一致
                if not any(
                    type(condition.equals) is type(value) and condition.equals == value
                    for value in field.choices
                ):
                    raise ValueError(f"{location}: device value outside choices")

    initial = _require(script.initial_state.scene_id, scenes, "initial_state.scene_id")
    # 开局场景若是终点，新档一开始就"已结束"
    if initial.terminal:
        raise ValueError("initial_state.scene_id cannot be terminal")
    for scene in scenes.values():
        # 出边只能指向已声明的场景
        for target in scene.next_scene_ids:
            _require(target, scenes, f"scenes.{scene.id}.next_scene_ids")
        conditions(scene.entry_conditions, f"scenes.{scene.id}.entry_conditions")
        conditions(
            scene.completion_conditions, f"scenes.{scene.id}.completion_conditions"
        )

    # 只检查声明的场景图；实际条件可满足性必须由规则轨迹测试证明。
    # 用栈从初始场景做深度优先遍历；图上不可达的场景会被拒绝。
    reachable, pending = set(), [initial.id]
    while pending:
        current = pending.pop()
        if current not in reachable:
            reachable.add(current)
            pending.extend(scenes[current].next_scene_ids)
    if reachable != scenes.keys():
        raise ValueError(
            f"scenes: unreachable scene ids {sorted(scenes.keys() - reachable)}"
        )
    for ending in endings.values():
        # 结局必须落在终点场景，否则"结局"之后还能继续走
        scene = _require(ending.scene_id, scenes, f"endings.{ending.id}.scene_id")
        if not scene.terminal:
            raise ValueError(f"endings.{ending.id}.scene_id must be terminal")
    for clue in clues.values():
        # 线索的发现条件同样要检查引用
        conditions(clue.discovery_conditions, f"clues.{clue.id}.discovery_conditions")

    for action in actions.values():
        location = f"actions.{action.id}"
        # 动作参数是第三层命名空间：actions.<id>.parameters.<id>
        parameters = _index(action.parameters, f"{location}.parameters")
        for scene_id in action.scene_ids:
            _require(scene_id, scenes, f"{location}.scene_ids")
        conditions(action.preconditions, f"{location}.preconditions")
        location += ".effects"
        # 六种效果逐类检查：引用、归属角色、取值白名单各有约束
        for effect in action.effects:
            if effect.op == "discover_clue":
                clue = _require(effect.clue_id, clues, location)
                # 只有线索归属者本人能发现它：两个角色都能做的动作，
                # 不能产生某个人的私密线索
                if set(action.roles) != {clue.role}:
                    raise ValueError(f"{location}: clue owner role mismatch")
            elif effect.op == "set_device":
                field = device_field(effect.device_id, effect.field, location)
                # 装置的 owner 必须就是动作的唯一角色：A 的设备只能 A 操作
                if set(action.roles) != {devices[effect.device_id].role}:
                    raise ValueError(f"{location}: device owner role mismatch")
                parameter = _require(effect.parameter, parameters, location)
                # 参数取值必须是设备字段选项的子集，否则动作能写出声明外的值
                if (
                    parameter.value_type != field.value_type
                    or not parameter.choices
                    or not set(parameter.choices) <= set(field.choices)
                ):
                    raise ValueError(
                        f"{location}: parameter choices must fit device choices"
                    )
            elif effect.op == "set_fact":
                fact = _require(effect.fact_id, facts, location)
                if type(effect.value) is not type(fact.initial_value):
                    raise ValueError(f"{location}: fact value type mismatch")
            elif effect.op == "enter_scene":
                _require(effect.scene_id, scenes, location)
                # 跳转必须已写进每个声明场景的 next_scene_ids：
                # 效果不能凭空创造图里没有的边
                if any(
                    effect.scene_id not in scenes[source].next_scene_ids
                    for source in action.scene_ids
                ):
                    raise ValueError(
                        f"{location}: scene transition not declared in next_scene_ids"
                    )
            elif effect.op == "record_vote":
                parameter = _require(
                    effect.parameter, parameters, f"{location}.record_vote"
                )
                # 投票参数必须是字符串枚举，且候选项来自结局 ID
                if (
                    parameter.value_type != "string"
                    or not parameter.choices
                    or not set(parameter.choices) <= endings.keys()
                ):
                    raise ValueError(
                        f"{location}.record_vote: choices must reference endings"
                    )

    # NPC 提示绑定的场景必须存在
    for hint in script.npc.hints:
        _require(hint.scene_id, scenes, "npc.hints.scene_id")
    for asset in media.values():
        # 媒体版本必须与剧本版本一致：换资源不换版本会让缓存和存档对不上
        if asset.content_version != script.metadata.content_version:
            raise ValueError(f"media.{asset.id}.content_version differs from script")
        for scene_id in asset.scene_ids:
            _require(scene_id, scenes, f"media.{asset.id}.scene_ids")
        conditions(asset.conditions, f"media.{asset.id}.conditions")

    def visible_asset(asset_id, presentation, location):
        """资源必须存在、对该角色可见、且在当前场景可用。"""
        asset = _require(asset_id, media, location)
        # audience 只有 public 或本人时才算可见：B 的专属旁白不能被 A 的场景引用
        if asset.audience not in {"public", presentation.role}:
            raise ValueError(f"{location}: asset audience excludes role")
        if presentation.scene_id not in asset.scene_ids:
            raise ValueError(f"{location}: asset unavailable in scene")
        return asset

    # views 记录 (场景, 角色) 组合，cues 记录演出提示 id；
    # cue 的 id 在所有场景、所有角色之间全局唯一
    views, cues = set(), set()
    for view in script.presentation:
        location = f"presentation.{view.scene_id}.{view.role}"
        _require(view.scene_id, scenes, location)
        # 同一场景同一角色只能有一份演示配置
        if (view.scene_id, view.role) in views:
            raise ValueError(f"{location}: duplicate presentation")
        views.add((view.scene_id, view.role))
        # 背景必须是图片，不能把音频当背景
        if visible_asset(view.background_asset_id, view, location).kind != "image":
            raise ValueError(f"{location}: background asset must be image")
        for cue in view.cues:
            if cue.id in cues:
                raise ValueError(f"{location}: duplicate cue id {cue.id}")
            cues.add(cue.id)
            conditions(cue.conditions, f"{location}.cues.{cue.id}")
            # cue 的每个资源同样要过可见性与场景校验
            for asset_id in cue.asset_ids:
                visible_asset(asset_id, view, f"{location}.cues.{cue.id}")
    # 覆盖率：每个场景必须 a、b 各一份，缺一个角色就会出现"另一半没画面"
    if views != {(scene, role) for scene in scenes for role in ("a", "b")}:
        raise ValueError("presentation must cover both roles in every scene")
