"""纯函数命令边界；不访问文件、网络、数据库、时钟或AI。"""

from pydantic import ValidationError

from twoworlds.content.schema import ScriptVersion

from .errors import DomainError
from .mechanics import common, lighthouse
from .models import CommandResult, DeviceState, DomainEvent, GameState, StateValue


def _require_script(script: ScriptVersion) -> None:
    if not isinstance(script, ScriptVersion):
        raise DomainError("INVALID_SCRIPT")
    if script.metadata.id != "lighthouse":
        raise DomainError("SCRIPT_UNSUPPORTED")


def create_initial_state(script: ScriptVersion) -> GameState:
    _require_script(script)
    state = GameState(
        script_id=script.metadata.id,
        script_version=script.metadata.content_version,
        version=0,
        scene_id=script.initial_state.scene_id,
        facts=tuple(
            StateValue(id=item.id, value=item.initial_value) for item in script.facts
        ),
        devices=tuple(
            DeviceState(
                id=item.id,
                fields=tuple(
                    StateValue(id=field.id, value=field.initial_value)
                    for field in item.fields
                ),
            )
            for item in script.devices
        ),
        discovered_clues=script.initial_state.discovered_clues,
        shared_clues=script.initial_state.shared_clues,
        votes=script.initial_state.votes,
        completed=script.initial_state.completed,
    )
    try:
        state = state.model_copy(
            update={"observations": lighthouse.observations(state, script)}
        )
        _validate_state(state, script)
    except (StopIteration, KeyError, ValidationError):
        raise DomainError("INVALID_SCRIPT") from None
    return state


def _unique(items) -> dict:
    indexed = {item.id: item for item in items}
    if len(indexed) != len(items):
        raise DomainError("INVALID_STATE")
    return indexed


def _validate_state(state: GameState, script: ScriptVersion) -> None:
    facts, definitions = _unique(state.facts), _unique(script.facts)
    if facts.keys() != definitions.keys() or any(
        type(item.value) is not type(definitions[item.id].initial_value)
        for item in state.facts
    ):
        raise DomainError("INVALID_STATE")
    devices, device_definitions = _unique(state.devices), _unique(script.devices)
    if devices.keys() != device_definitions.keys():
        raise DomainError("INVALID_STATE")
    for device in state.devices:
        fields = _unique(device.fields)
        options = _unique(device_definitions[device.id].fields)
        if fields.keys() != options.keys() or any(
            not any(
                common.same(item.value, choice) for choice in options[item.id].choices
            )
            for item in device.fields
        ):
            raise DomainError("INVALID_STATE")
    clues = _unique(script.clues)
    if (
        len(set(state.discovered_clues)) != len(state.discovered_clues)
        or not set(state.discovered_clues) <= clues.keys()
        or len(set(state.shared_clues)) != len(state.shared_clues)
        or not set(state.shared_clues) <= set(state.discovered_clues)
        or any(not clues[key].shareable for key in state.shared_clues)
    ):
        raise DomainError("INVALID_STATE")
    endings = _unique(script.endings)
    votes = {item.role: item.ending_id for item in state.votes}
    agreed = len(votes) == 2 and votes["a"] == votes["b"]
    scene = next(item for item in script.scenes if item.id == state.scene_id)
    if (
        len(votes) != len(state.votes)
        or not set(votes.values()) <= endings.keys()
        or state.fact("completed") is not state.completed
        or state.completed is not agreed
        or scene.terminal is not state.completed
    ):
        raise DomainError("INVALID_STATE")
    if state.completed:
        if (
            state.ending_id != votes["a"]
            or state.fact("ending_id") != state.ending_id
            or endings[state.ending_id].scene_id != state.scene_id
        ):
            raise DomainError("INVALID_STATE")
    elif state.ending_id is not None or not common.same(
        state.fact("ending_id"), definitions["ending_id"].initial_value
    ):
        raise DomainError("INVALID_STATE")
    if not common.conditions_met(state, scene.entry_conditions):
        raise DomainError("INVALID_STATE")
    lighthouse.validate_invariants(state, script)
    if state.observations != lighthouse.observations(state, script):
        raise DomainError("INVALID_STATE")


def apply_command(
    state: GameState, script: ScriptVersion, actor_role: str, action: dict
) -> CommandResult:
    _require_script(script)
    if not isinstance(state, GameState):
        raise DomainError("INVALID_STATE")
    try:
        # 即使调用方用了model_copy/construct绕过字段校验，这里也不接受坏快照。
        state = GameState.model_validate(state.model_dump(mode="python"))
        if (state.script_id, state.script_version) != (
            script.metadata.id,
            script.metadata.content_version,
        ):
            raise DomainError("SCRIPT_MISMATCH")
        _validate_state(state, script)
    except (ValidationError, StopIteration, KeyError, TypeError):
        raise DomainError("INVALID_STATE") from None
    if type(actor_role) is not str or actor_role not in {"a", "b"}:
        raise DomainError("ROLE_FORBIDDEN")
    if (
        type(action) is not dict
        or set(action) != {"kind", "args"}
        or type(action["kind"]) is not str
        or type(action["args"]) is not dict
    ):
        raise DomainError("INVALID_COMMAND")
    if state.completed:
        raise DomainError("SAVE_COMPLETED")
    try:
        return _apply_supported_command(state, script, actor_role, action)
    except (StopIteration, KeyError, ValidationError, TypeError):
        # Schema合法不代表新机关值已经有处理器；仍按领域错误拒绝，原状态未改。
        raise DomainError("INVALID_SCRIPT") from None


def _apply_supported_command(
    state: GameState, script: ScriptVersion, actor_role: str, action: dict
) -> CommandResult:
    definition = common.resolve_action(script, action["kind"], action["args"])
    if actor_role not in definition.roles:
        raise DomainError("ROLE_FORBIDDEN")
    if state.scene_id not in definition.scene_ids:
        raise DomainError("ACTION_UNAVAILABLE")
    if not common.valid_parameters(definition, action["args"]):
        if definition.kind == "repair_clock" and action["args"] == {"mode": "fast"}:
            raise DomainError("REPAIR_MODE_UNSAFE")
        raise DomainError("INVALID_ARGUMENTS")
    common.require_preconditions(state, definition)
    candidate, events = state, []
    for effect in definition.effects:
        candidate, emitted = common.apply_effect(
            candidate, script, actor_role, action["args"], effect
        )
        events.extend(emitted)
    if definition.kind == "vote_ending":
        candidate, emitted = common.settle_votes(candidate, script)
        events.extend(emitted)
    if candidate == state:
        # Observe文案不算游戏状态变化，不让重复设置仅凭生成事件消耗版本。
        raise DomainError("NO_STATE_CHANGE")
    observations = lighthouse.observations(candidate, script)
    for item in observations:
        if item not in state.observations:
            events.append(
                DomainEvent(
                    kind="observation_changed",
                    audience=item.audience,
                    subject_id=item.topic,
                    text=item.text,
                )
            )
    candidate = candidate.model_copy(
        update={"observations": observations, "version": state.version + 1}
    )
    _validate_state(candidate, script)
    return CommandResult(
        candidate,
        tuple(
            event.model_copy(update={"version": candidate.version}) for event in events
        ),
    )
