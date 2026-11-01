"""执行既有Schema允许的条件/效果；每个更新返回新的不可变世界值。"""

from twoworlds.content.schema import (
    ActionDefinition,
    Condition,
    Effect,
    EndingVote,
    Role,
    Scalar,
    ScriptVersion,
)

from ..errors import DomainError
from ..models import DomainEvent, GameState, StateValue


def same(left, right) -> bool:
    # bool属于int子类，严格比较类型以避免True当作角度1等隐式匹配。
    return type(left) is type(right) and left == right


def matches(state: GameState, condition: Condition) -> bool:
    if condition.kind == "fact":
        return same(state.fact(condition.fact_id), condition.equals)
    if condition.kind == "device":
        return same(
            state.device(condition.device_id, condition.field), condition.equals
        )
    return (condition.clue_id in state.discovered_clues) is condition.discovered


def conditions_met(state: GameState, conditions: tuple[Condition, ...]) -> bool:
    return all(matches(state, condition) for condition in conditions)


def valid_parameters(definition: ActionDefinition, args: dict) -> bool:
    if set(args) != {parameter.id for parameter in definition.parameters}:
        return False
    for parameter in definition.parameters:
        value = args[parameter.id]
        expected = {"boolean": bool, "integer": int, "string": str}[
            parameter.value_type
        ]
        if type(value) is not expected:
            return False
        if parameter.choices and not any(
            same(value, choice) for choice in parameter.choices
        ):
            return False
        if parameter.max_length is not None and len(value) > parameter.max_length:
            return False
    return True


def resolve_action(script: ScriptVersion, kind: str, args: dict) -> ActionDefinition:
    candidates = [item for item in script.actions if item.kind == kind]
    if not candidates:
        raise DomainError("UNKNOWN_ACTION")
    if len(candidates) > 1:
        # inspect等复用kind的声明以明确参数选择；不能先按角色筛选而误选别人的目标。
        candidates = [item for item in candidates if valid_parameters(item, args)]
        if not candidates:
            raise DomainError("INVALID_ARGUMENTS")
    if len(candidates) != 1:
        raise DomainError("INVALID_SCRIPT")
    return candidates[0]


def require_preconditions(state: GameState, definition: ActionDefinition) -> None:
    for condition in definition.preconditions:
        if matches(state, condition):
            continue
        if definition.kind == "lock_signal":
            code = "SIGNAL_UNSTABLE"
        elif condition.kind == "clue":
            code = (
                "ALREADY_DISCOVERED"
                if not condition.discovered
                else "CLUE_NOT_DISCOVERED"
            )
            if condition.discovered and definition.kind == "repair_clock":
                code = "TOOLS_NOT_READY"
        elif condition.kind == "device":
            code = (
                "CLOCK_UNPOWERED"
                if condition.device_id == "power_router"
                else "PRECONDITION_NOT_MET"
            )
        else:
            code = {
                "signal_locked": "SIGNAL_NOT_LOCKED",
                "repair_tools_ready": "TOOLS_NOT_READY",
                "clock_repaired": "CLOCK_NOT_REPAIRED"
                if condition.equals
                else "NO_STATE_CHANGE",
                "route_confirmed": "ENDING_UNAVAILABLE",
            }.get(condition.fact_id, "PRECONDITION_NOT_MET")
        if code not in definition.error_codes:
            code = definition.error_codes[0]
        raise DomainError(code)


def set_fact(state: GameState, script: ScriptVersion, identifier: str, value: Scalar):
    if same(state.fact(identifier), value):
        return state, ()
    facts = tuple(
        StateValue(id=item.id, value=value) if item.id == identifier else item
        for item in state.facts
    )
    definition = next(item for item in script.facts if item.id == identifier)
    event = DomainEvent(
        kind="fact_changed",
        audience=definition.audience,
        subject_id=identifier,
        value=value,
        text="世界事实已更新。",
    )
    return state.model_copy(update={"facts": facts}), (event,)


def enter_scene(state: GameState, script: ScriptVersion, target: str):
    source = next(item for item in script.scenes if item.id == state.scene_id)
    destination = next(item for item in script.scenes if item.id == target)
    if (
        target not in source.next_scene_ids
        or not conditions_met(state, source.completion_conditions)
        or not conditions_met(state, destination.entry_conditions)
    ):
        raise DomainError("PRECONDITION_NOT_MET")
    events = [
        DomainEvent(
            kind="scene_changed",
            audience="public",
            subject_id=target,
            text="共同旅程进入下一阶段。",
        )
    ]
    events.extend(
        DomainEvent(
            kind="scene_observation",
            audience=item.role,
            subject_id=target,
            text=item.text,
        )
        for item in destination.observations
    )
    return state.model_copy(update={"scene_id": target}), tuple(events)


def apply_effect(
    state: GameState, script: ScriptVersion, role: Role, args: dict, effect: Effect
):
    if effect.op == "discover_clue":
        clue = next(item for item in script.clues if item.id == effect.clue_id)
        if clue.role != role:
            raise DomainError("ROLE_FORBIDDEN")
        if not conditions_met(state, clue.discovery_conditions):
            raise DomainError("PRECONDITION_NOT_MET")
        if clue.id in state.discovered_clues:
            return state, ()
        discovered = tuple(sorted((*state.discovered_clues, clue.id)))
        event = DomainEvent(
            kind="clue_discovered",
            audience=clue.role,
            subject_id=clue.id,
            text=clue.text,
        )
        return state.model_copy(update={"discovered_clues": discovered}), (event,)
    if effect.op == "set_device":
        owner = next(
            item.role for item in script.devices if item.id == effect.device_id
        )
        if owner != role:
            raise DomainError("ROLE_FORBIDDEN")
        value = args[effect.parameter]
        if same(state.device(effect.device_id, effect.field), value):
            return state, ()
        devices = []
        for device in state.devices:
            if device.id == effect.device_id:
                fields = tuple(
                    StateValue(id=item.id, value=value)
                    if item.id == effect.field
                    else item
                    for item in device.fields
                )
                device = device.model_copy(update={"fields": fields})
            devices.append(device)
        event = DomainEvent(
            kind="device_changed",
            audience=owner,
            subject_id=effect.device_id,
            field=effect.field,
            value=value,
            text="装置配置已更新。",
        )
        return state.model_copy(update={"devices": tuple(devices)}), (event,)
    if effect.op == "set_fact":
        return set_fact(state, script, effect.fact_id, effect.value)
    if effect.op == "enter_scene":
        return enter_scene(state, script, effect.scene_id)
    if effect.op == "record_vote":
        choice = args[effect.parameter]
        old = next((item.ending_id for item in state.votes if item.role == role), None)
        if old == choice:
            return state, ()
        votes = tuple(
            sorted(
                (
                    *[item for item in state.votes if item.role != role],
                    EndingVote(role=role, ending_id=choice),
                ),
                key=lambda item: item.role,
            )
        )
        event = DomainEvent(
            kind="vote_changed",
            audience="public",
            subject_id=role,
            value=choice,
            text="共同选择已更新；一致前仍可修改本人选择。",
        )
        return state.model_copy(update={"votes": votes}), (event,)
    if effect.op == "observe":
        return state, (
            DomainEvent(kind="observation", audience=effect.audience, text=effect.text),
        )
    raise DomainError("INVALID_SCRIPT")


def settle_votes(state: GameState, script: ScriptVersion):
    if len(state.votes) != 2 or state.votes[0].ending_id != state.votes[1].ending_id:
        return state, ()
    choice = state.votes[0].ending_id
    ending = next(item for item in script.endings if item.id == choice)
    candidate, events = set_fact(state, script, "completed", True)
    candidate, more = set_fact(candidate, script, "ending_id", choice)
    candidate = candidate.model_copy(update={"completed": True, "ending_id": choice})
    candidate, moved = enter_scene(candidate, script, ending.scene_id)
    completed = DomainEvent(
        kind="game_completed",
        audience="public",
        subject_id=choice,
        text=ending.summary_template,
    )
    return candidate, (*events, *more, *moved, completed)
