"""已通过字段校验的整份内容引用检查；不推演实际玩法状态。"""

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from .schema import ContentModel, ScriptVersion

Item = TypeVar("Item", bound="ContentModel")


def _index(items: tuple[Item, ...], location: str) -> dict[str, Item]:
    result = {}
    for item in items:
        if item.id in result:
            raise ValueError(f"{location}: duplicate id {item.id}")
        result[item.id] = item
    return result


def _require(identifier: str, items: dict, location: str):
    if identifier not in items:
        raise ValueError(f"{location}: unknown reference {identifier}")
    return items[identifier]


def validate_references(script: "ScriptVersion") -> None:
    scenes = _index(script.scenes, "scenes")
    facts = _index(script.facts, "facts")
    clues = _index(script.clues, "clues")
    devices = _index(script.devices, "devices")
    actions = _index(script.actions, "actions")
    endings = _index(script.endings, "endings")
    media = _index(script.media, "media")
    fields = {
        key: _index(device.fields, f"devices.{key}.fields")
        for key, device in devices.items()
    }

    def device_field(device_id, field_id, location):
        _require(device_id, devices, location)
        return _require(field_id, fields[device_id], location)

    def conditions(items, location):
        for condition in items:
            if condition.kind == "fact":
                fact = _require(condition.fact_id, facts, location)
                if type(condition.equals) is not type(fact.initial_value):
                    raise ValueError(f"{location}: fact value type mismatch")
            elif condition.kind == "clue":
                _require(condition.clue_id, clues, location)
            else:
                field = device_field(condition.device_id, condition.field, location)
                if not any(
                    type(condition.equals) is type(value) and condition.equals == value
                    for value in field.choices
                ):
                    raise ValueError(f"{location}: device value outside choices")

    initial = _require(script.initial_state.scene_id, scenes, "initial_state.scene_id")
    if initial.terminal:
        raise ValueError("initial_state.scene_id cannot be terminal")
    for scene in scenes.values():
        for target in scene.next_scene_ids:
            _require(target, scenes, f"scenes.{scene.id}.next_scene_ids")
        conditions(scene.entry_conditions, f"scenes.{scene.id}.entry_conditions")
        conditions(
            scene.completion_conditions, f"scenes.{scene.id}.completion_conditions"
        )

    # 只检查声明的场景图；实际条件可满足性必须由规则轨迹测试证明。
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
        scene = _require(ending.scene_id, scenes, f"endings.{ending.id}.scene_id")
        if not scene.terminal:
            raise ValueError(f"endings.{ending.id}.scene_id must be terminal")
    for clue in clues.values():
        conditions(clue.discovery_conditions, f"clues.{clue.id}.discovery_conditions")

    for action in actions.values():
        location = f"actions.{action.id}"
        parameters = _index(action.parameters, f"{location}.parameters")
        for scene_id in action.scene_ids:
            _require(scene_id, scenes, f"{location}.scene_ids")
        conditions(action.preconditions, f"{location}.preconditions")
        location += ".effects"
        for effect in action.effects:
            if effect.op == "discover_clue":
                clue = _require(effect.clue_id, clues, location)
                if set(action.roles) != {clue.role}:
                    raise ValueError(f"{location}: clue owner role mismatch")
            elif effect.op == "set_device":
                field = device_field(effect.device_id, effect.field, location)
                if set(action.roles) != {devices[effect.device_id].role}:
                    raise ValueError(f"{location}: device owner role mismatch")
                parameter = _require(effect.parameter, parameters, location)
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
                if (
                    parameter.value_type != "string"
                    or not parameter.choices
                    or not set(parameter.choices) <= endings.keys()
                ):
                    raise ValueError(
                        f"{location}.record_vote: choices must reference endings"
                    )

    for hint in script.npc.hints:
        _require(hint.scene_id, scenes, "npc.hints.scene_id")
    for asset in media.values():
        if asset.content_version != script.metadata.content_version:
            raise ValueError(f"media.{asset.id}.content_version differs from script")
        for scene_id in asset.scene_ids:
            _require(scene_id, scenes, f"media.{asset.id}.scene_ids")
        conditions(asset.conditions, f"media.{asset.id}.conditions")

    def visible_asset(asset_id, presentation, location):
        asset = _require(asset_id, media, location)
        if asset.audience not in {"public", presentation.role}:
            raise ValueError(f"{location}: asset audience excludes role")
        if presentation.scene_id not in asset.scene_ids:
            raise ValueError(f"{location}: asset unavailable in scene")
        return asset

    views, cues = set(), set()
    for view in script.presentation:
        location = f"presentation.{view.scene_id}.{view.role}"
        _require(view.scene_id, scenes, location)
        if (view.scene_id, view.role) in views:
            raise ValueError(f"{location}: duplicate presentation")
        views.add((view.scene_id, view.role))
        if visible_asset(view.background_asset_id, view, location).kind != "image":
            raise ValueError(f"{location}: background asset must be image")
        for cue in view.cues:
            if cue.id in cues:
                raise ValueError(f"{location}: duplicate cue id {cue.id}")
            cues.add(cue.id)
            conditions(cue.conditions, f"{location}.cues.{cue.id}")
            for asset_id in cue.asset_ids:
                visible_asset(asset_id, view, f"{location}.cues.{cue.id}")
    if views != {(scene, role) for scene in scenes for role in ("a", "b")}:
        raise ValueError("presentation must cover both roles in every scene")
