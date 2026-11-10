"""只用真实正式内容运行纯规则，不提供HTTP/存储/AI模拟器。"""

from collections import deque
from copy import deepcopy
from functools import lru_cache
from itertools import product
import json
from pathlib import Path
import subprocess
import sys

from pydantic import ValidationError
import pytest


def api():
    from twoworlds.domain import engine

    return engine


@lru_cache
def script():
    from twoworlds.content import loader

    return loader.ScriptLoader(Path(loader.__file__).parent / "scripts").load(
        "lighthouse", "1.0.0"
    )


def fresh():
    return api().create_initial_state(script())


def command(kind, args=None):
    return {"kind": kind, "args": {} if args is None else args}


def accept(state, role, kind, args=None):
    before = state.model_dump(mode="json")
    action = command(kind, args)
    untouched = deepcopy(action)
    result = api().apply_command(state, script(), role, action)
    assert state.model_dump(mode="json") == before
    assert action == untouched
    assert result.state is not state and result.state.version == state.version + 1
    assert result.events and all(
        event.version == result.state.version for event in result.events
    )
    return result


def reject(state, role, kind, args=None, code=None, action=None):
    from twoworlds.domain.errors import DomainError

    before = state.model_dump(mode="json")
    payload = command(kind, args) if action is None else action
    untouched = deepcopy(payload)
    with pytest.raises(DomainError) as error:
        api().apply_command(state, script(), role, payload)
    if code is not None:
        assert error.value.code == code
    assert state.model_dump(mode="json") == before and payload == untouched
    return error.value.code


def at(phase):
    state = fresh()
    if phase == "fresh":
        return state
    steps = [
        ("a", "inspect", {"target": "maintenance_log"}),
        ("b", "inspect", {"target": "sea_chart"}),
        ("a", "set_emitter", {"angle": 0, "pattern": "pulse"}),
        ("b", "set_filter", {"filter": "amber"}),
        ("a", "set_emitter", {"angle": 90, "pattern": "pulse"}),
        ("b", "lock_signal", {}),
        ("b", "route_power", {"target": "tower"}),
        ("a", "inspect", {"target": "clock_gears"}),
        ("a", "repair_clock", {"mode": "steady"}),
        ("b", "confirm_route", {}),
    ]
    stop = {
        "read": 2,
        "aligned": 5,
        "repair": 6,
        "powered": 7,
        "tools": 8,
        "repaired": 9,
        "decision": 10,
    }[phase]
    for role, kind, args in steps[:stop]:
        state = accept(state, role, kind, args).state
    return state


def observation(state, audience, topic):
    return next(
        item.text
        for item in state.observations
        if item.audience == audience and item.topic == topic
    )


def visible_events(events, role):
    # 只在测试中检查事件标签；这不是生产玩家投影接口。
    return json.dumps(
        [
            event.model_dump(mode="json")
            for event in events
            if event.audience in {role, "public"}
        ],
        ensure_ascii=False,
    )


def test_initial_state_comes_from_the_existing_content_definitions():
    state = fresh()
    assert state.script_id == "lighthouse" and state.script_version == "1.0.0"
    assert (
        state.scene_id == "calibration" and state.version == 0 and not state.completed
    )
    assert (
        state.device("emitter", "angle") == 0
        and state.device("emitter", "pattern") == "steady"
    )
    assert state.device("filter", "filter") == "clear"
    assert state.device("power_router", "target") == "observatory"
    assert not state.discovered_clues and not state.votes and state.ending_id is None
    assert all(state.fact(item.id) == item.initial_value for item in script().facts)


@pytest.mark.parametrize("ending", ["guide_now", "wait_tide"])
def test_complete_acceptance_trace_requires_two_matching_votes(ending):
    state = at("decision")
    assert state.version == 10 and state.scene_id == "decision"
    first = accept(state, "a", "vote_ending", {"choice": ending})
    assert not first.state.completed and first.state.ending_id is None
    assert not any(event.kind == "game_completed" for event in first.events)
    final = accept(first.state, "b", "vote_ending", {"choice": ending})
    assert final.state.version == 12 and final.state.completed
    assert final.state.scene_id == "completed" and final.state.ending_id == ending
    assert (
        final.state.fact("completed") is True
        and final.state.fact("ending_id") == ending
    )
    assert sum(event.kind == "game_completed" for event in final.events) == 1
    reject(
        final.state,
        "b",
        "vote_ending",
        {"choice": "wait_tide" if ending == "guide_now" else "guide_now"},
        "SAVE_COMPLETED",
    )


@pytest.mark.parametrize("ending", ["guide_now", "wait_tide"])
def test_different_exploration_order_and_extra_trials_do_not_require_a_fixed_step_count(
    ending,
):
    steps = [
        ("b", "inspect", {"target": "sea_chart"}),
        ("b", "set_filter", {"filter": "blue"}),
        ("a", "inspect", {"target": "maintenance_log"}),
        ("a", "set_emitter", {"angle": 270, "pattern": "pulse"}),
        ("b", "set_filter", {"filter": "amber"}),
        ("a", "set_emitter", {"angle": 90, "pattern": "pulse"}),
        ("b", "lock_signal", {}),
        ("b", "route_power", {"target": "shore"}),
        ("b", "route_power", {"target": "tower"}),
        ("a", "inspect", {"target": "clock_gears"}),
        ("a", "repair_clock", {"mode": "steady"}),
        ("b", "route_power", {"target": "observatory"}),
        ("b", "route_power", {"target": "tower"}),
        ("b", "confirm_route", {}),
        ("b", "vote_ending", {"choice": ending}),
        ("a", "vote_ending", {"choice": ending}),
    ]
    state = fresh()
    for role, kind, args in steps:
        state = accept(state, role, kind, args).state
    assert state.completed and state.ending_id == ending and state.version == len(steps)
    assert state.version != 12


@pytest.mark.parametrize(
    "angle,pattern,filter_value",
    list(product([0, 90, 180, 270], ["steady", "pulse"], ["clear", "blue", "amber"])),
)
def test_all_optical_configurations_only_lock_the_valid_combination(
    angle, pattern, filter_value
):
    state = at("read")
    if (angle, pattern) != (0, "steady"):
        state = accept(
            state, "a", "set_emitter", {"angle": angle, "pattern": pattern}
        ).state
    if filter_value != "clear":
        state = accept(state, "b", "set_filter", {"filter": filter_value}).state
    if (angle, pattern, filter_value) == (90, "pulse", "amber"):
        result = accept(state, "b", "lock_signal")
        assert (
            result.state.scene_id == "repair"
            and result.state.fact("signal_locked") is True
        )
    else:
        reject(state, "b", "lock_signal", code="SIGNAL_UNSTABLE")


@pytest.mark.parametrize(
    "angle,direction", [(0, "暗礁"), (90, "内湾航道"), (180, "观测山"), (270, "外海港")]
)
def test_a_emitter_changes_b_current_observation_without_sending_it_to_a(
    angle, direction
):
    state = at("read")
    state = accept(state, "b", "set_filter", {"filter": "amber"}).state
    result = accept(state, "a", "set_emitter", {"angle": angle, "pattern": "pulse"})
    assert direction in observation(result.state, "b", "beam")
    assert direction in visible_events(result.events, "b")
    assert direction not in visible_events(result.events, "a")


@pytest.mark.parametrize("filter_value", ["clear", "blue"])
def test_b_filter_changes_their_own_clarity_and_can_recover(filter_value):
    state = at("aligned")
    blurred = accept(state, "b", "set_filter", {"filter": filter_value})
    assert "模糊" in observation(blurred.state, "b", "beam")
    assert "内湾" not in visible_events(blurred.events, "a")
    reject(blurred.state, "b", "lock_signal", code="SIGNAL_UNSTABLE")
    restored = accept(blurred.state, "b", "set_filter", {"filter": "amber"}).state
    assert "内湾" in observation(restored, "b", "beam")
    assert accept(restored, "b", "lock_signal").state.scene_id == "repair"


@pytest.mark.parametrize("target", ["shore", "observatory"])
def test_b_power_changes_a_inspection_and_preserves_completed_repair(target):
    state = at("powered")
    dark = accept(state, "b", "route_power", {"target": target})
    assert "无电" in observation(dark.state, "a", "clock_power")
    assert "无电" in visible_events(dark.events, "a")
    reject(dark.state, "a", "inspect", {"target": "clock_gears"}, "CLOCK_UNPOWERED")
    reject(dark.state, "a", "repair_clock", {"mode": "steady"})
    restored = accept(dark.state, "b", "route_power", {"target": "tower"})
    assert "有电" in observation(restored.state, "a", "clock_power")
    inspected = accept(restored.state, "a", "inspect", {"target": "clock_gears"})
    assert inspected.state.fact("repair_tools_ready") is True
    assert script().clues[2].text not in visible_events(inspected.events, "b")
    fixed = accept(inspected.state, "a", "repair_clock", {"mode": "steady"})
    assert fixed.state.fact("clock_repaired") is True
    assert "可确认" in observation(fixed.state, "b", "route_scan")
    unpowered = accept(fixed.state, "b", "route_power", {"target": target}).state
    assert unpowered.fact("clock_repaired") is True
    reject(unpowered, "b", "confirm_route", code="CLOCK_UNPOWERED")
    powered = accept(unpowered, "b", "route_power", {"target": "tower"}).state
    assert accept(powered, "b", "confirm_route").state.scene_id == "decision"


@pytest.mark.parametrize(
    "phase,role,kind,args,code",
    [
        (
            "fresh",
            "a",
            "set_emitter",
            {"angle": 90, "pattern": "pulse"},
            "CLUE_NOT_DISCOVERED",
        ),
        ("fresh", "b", "set_filter", {"filter": "amber"}, "CLUE_NOT_DISCOVERED"),
        ("fresh", "b", "lock_signal", {}, "SIGNAL_UNSTABLE"),
        ("repair", "a", "inspect", {"target": "clock_gears"}, "CLOCK_UNPOWERED"),
        ("powered", "a", "repair_clock", {"mode": "steady"}, "TOOLS_NOT_READY"),
        ("tools", "a", "repair_clock", {"mode": "fast"}, "REPAIR_MODE_UNSAFE"),
        ("tools", "b", "confirm_route", {}, "CLOCK_NOT_REPAIRED"),
        (
            "repair",
            "a",
            "set_emitter",
            {"angle": 180, "pattern": "steady"},
            "ACTION_UNAVAILABLE",
        ),
        ("repair", "b", "set_filter", {"filter": "blue"}, "ACTION_UNAVAILABLE"),
        ("repair", "a", "inspect", {"target": "maintenance_log"}, "ACTION_UNAVAILABLE"),
        ("fresh", "a", "vote_ending", {"choice": "guide_now"}, "ACTION_UNAVAILABLE"),
        ("fresh", "b", "route_power", {"target": "tower"}, "ACTION_UNAVAILABLE"),
    ],
)
def test_failed_operations_preserve_every_state_field_and_version(
    phase, role, kind, args, code
):
    reject(at(phase), role, kind, args, code)


@pytest.mark.parametrize(
    "phase,role,kind,args",
    [
        ("fresh", "b", "inspect", {"target": "maintenance_log"}),
        ("fresh", "a", "inspect", {"target": "sea_chart"}),
        ("read", "b", "set_emitter", {"angle": 90, "pattern": "pulse"}),
        ("read", "a", "set_filter", {"filter": "amber"}),
        ("aligned", "a", "lock_signal", {}),
        ("repair", "a", "route_power", {"target": "tower"}),
        ("powered", "b", "inspect", {"target": "clock_gears"}),
        ("tools", "b", "repair_clock", {"mode": "steady"}),
        ("repaired", "a", "confirm_route", {}),
    ],
)
def test_all_exclusive_actions_reject_the_other_role(phase, role, kind, args):
    reject(at(phase), role, kind, args, "ROLE_FORBIDDEN")


@pytest.mark.parametrize(
    "kind,args",
    [
        ("set_emitter", {"angle": True, "pattern": "pulse"}),
        ("set_emitter", {"angle": 90.0, "pattern": "pulse"}),
        ("set_emitter", {"angle": "90", "pattern": "pulse"}),
        ("set_emitter", {"angle": 45, "pattern": "pulse"}),
        ("set_emitter", {"angle": 90, "pattern": "unknown"}),
        ("set_emitter", {"angle": 90}),
        ("set_emitter", {"angle": 90, "pattern": "pulse", "role": "b"}),
        ("set_emitter", {"angle": [], "pattern": "pulse"}),
        ("set_emitter", {"angle": {}, "pattern": "pulse"}),
        ("set_filter", {"filter": None}),
        ("set_filter", {"filter": "red"}),
        ("inspect", {"target": "unknown"}),
    ],
)
def test_invalid_parameters_are_not_coerced_or_applied(kind, args):
    role = "a" if kind != "set_filter" else "b"
    reject(at("read"), role, kind, args, "INVALID_ARGUMENTS")


@pytest.mark.parametrize(
    "extra",
    [
        "role",
        "actor_role",
        "player_id",
        "account_id",
        "state",
        "completed",
        "ending_id",
        "expected_version",
        "request_id",
    ],
)
def test_command_cannot_claim_an_identity_or_replace_the_world(extra):
    payload = command("inspect", {"target": "maintenance_log"})
    payload[extra] = "forged"
    reject(fresh(), "a", "inspect", code="INVALID_COMMAND", action=payload)


@pytest.mark.parametrize("role", ["admin", "A", None, True, 0, {"role": "a"}])
def test_invalid_actor_roles_are_rejected(role):
    reject(fresh(), role, "inspect", {"target": "maintenance_log"}, "ROLE_FORBIDDEN")


@pytest.mark.parametrize(
    "kind",
    ["share_clue", "request_hint", "talk", "set_fact", "complete_game", "eval_python"],
)
def test_commands_without_valid_arguments_or_definition_have_no_authority(kind):
    code = "INVALID_ARGUMENTS" if kind == "share_clue" else "UNKNOWN_ACTION"
    reject(fresh(), "a", kind, code=code)


def test_disagreement_revote_and_repeat_vote_behave_as_state_changes():
    first = accept(at("decision"), "a", "vote_ending", {"choice": "guide_now"}).state
    different = accept(first, "b", "vote_ending", {"choice": "wait_tide"}).state
    assert not different.completed and different.scene_id == "decision"
    reject(different, "b", "vote_ending", {"choice": "wait_tide"}, "NO_STATE_CHANGE")
    changed = accept(different, "a", "vote_ending", {"choice": "wait_tide"})
    assert changed.state.completed and changed.state.ending_id == "wait_tide"
    assert all(
        event.audience == "public"
        for event in changed.events
        if event.kind in {"vote_changed", "game_completed"}
    )


@pytest.mark.parametrize(
    "phase,role,kind,args,code",
    [
        ("read", "a", "inspect", {"target": "maintenance_log"}, "ALREADY_DISCOVERED"),
        ("read", "b", "inspect", {"target": "sea_chart"}, "ALREADY_DISCOVERED"),
        (
            "read",
            "a",
            "set_emitter",
            {"angle": 0, "pattern": "steady"},
            "NO_STATE_CHANGE",
        ),
        ("read", "b", "set_filter", {"filter": "clear"}, "NO_STATE_CHANGE"),
        ("repair", "b", "route_power", {"target": "observatory"}, "NO_STATE_CHANGE"),
        ("tools", "a", "inspect", {"target": "clock_gears"}, "ALREADY_DISCOVERED"),
        ("repaired", "a", "repair_clock", {"mode": "steady"}, "NO_STATE_CHANGE"),
    ],
)
def test_repeated_no_change_commands_do_not_consume_a_version(
    phase, role, kind, args, code
):
    reject(at(phase), role, kind, args, code)


def test_private_clues_and_tools_never_become_public_events():
    a = accept(fresh(), "a", "inspect", {"target": "maintenance_log"})
    assert script().clues[0].text in visible_events(a.events, "a")
    assert script().clues[0].text not in visible_events(a.events, "b")
    b = accept(a.state, "b", "inspect", {"target": "sea_chart"})
    assert script().clues[1].text in visible_events(b.events, "b")
    assert script().clues[1].text not in visible_events(b.events, "a")
    gears = accept(at("powered"), "a", "inspect", {"target": "clock_gears"})
    assert all(
        event.audience == "a"
        for event in gears.events
        if event.kind in {"clue_discovered", "fact_changed"}
    )


def test_state_and_nested_values_are_immutable_and_unchanged_objects_can_be_reused():
    initial = fresh()
    for item, field, value in [
        (initial, "version", 4),
        (initial.facts[0], "value", True),
        (initial.devices[0].fields[0], "value", 90),
    ]:
        with pytest.raises(ValidationError):
            setattr(item, field, value)
    first = accept(initial, "a", "inspect", {"target": "maintenance_log"})
    second = accept(initial, "b", "inspect", {"target": "sea_chart"})
    assert first.state.discovered_clues == ("a_maintenance_log",)
    assert second.state.discovered_clues == ("b_sea_chart",)
    assert initial.discovered_clues == ()


def test_another_content_version_cannot_be_applied_to_the_existing_state():
    from twoworlds.content.schema import ScriptVersion
    from twoworlds.domain.errors import DomainError

    data = script().model_dump(mode="json")
    data["metadata"]["content_version"] = "1.0.1"
    for item in data["media"]:
        item["content_version"] = "1.0.1"
        item["path"] = item["path"].replace("/1.0.0/", "/1.0.1/")
    newer = ScriptVersion.model_validate(data)
    original = fresh()
    before = original.model_dump(mode="json")
    with pytest.raises(DomainError) as error:
        api().apply_command(
            original, newer, "a", command("inspect", {"target": "maintenance_log"})
        )
    assert (
        error.value.code == "SCRIPT_MISMATCH"
        and original.model_dump(mode="json") == before
    )


def test_construct_without_required_state_fields_is_still_rejected_as_a_domain_error():
    from twoworlds.domain.models import GameState

    incomplete = GameState.model_construct()
    reject(incomplete, "a", "inspect", {"target": "maintenance_log"}, "INVALID_STATE")


@pytest.mark.parametrize(
    "update",
    [
        {"version": True},
        {"scene_id": "missing"},
        {"completed": True},
        {"facts": ()},
        {"votes": ()},
    ],
)
def test_inconsistent_runtime_snapshots_are_rejected(update):
    # 空投票本身在开局合法；此例从已完成状态拿掉投票，验证完成依据不会被省略。
    state = at("decision")
    state = accept(state, "a", "vote_ending", {"choice": "guide_now"}).state
    state = accept(state, "b", "vote_ending", {"choice": "guide_now"}).state
    if update == {"completed": True}:
        state = fresh()
    corrupt = state.model_copy(update=update)
    reject(corrupt, "a", "inspect", {"target": "maintenance_log"}, "INVALID_STATE")


def possible_commands():
    for action in script().actions:
        for values in product(*(parameter.choices for parameter in action.parameters)):
            yield command(
                action.kind,
                {
                    parameter.id: value
                    for parameter, value in zip(action.parameters, values)
                },
            )


def key(state):
    return json.dumps(
        state.model_dump(mode="json", exclude={"version"}),
        ensure_ascii=False,
        sort_keys=True,
    )


@pytest.mark.parametrize("role", ["a", "b"])
def test_every_world_reachable_with_only_one_role_remains_incomplete(role):
    from twoworlds.domain.errors import DomainError

    pending = deque([fresh()])
    seen = set()
    while pending:
        state = pending.popleft()
        if key(state) in seen:
            continue
        seen.add(key(state))
        assert not state.completed
        for action in possible_commands():
            before = state.model_dump(mode="json")
            try:
                result = api().apply_command(state, script(), role, action)
                pending.append(result.state)
            except DomainError:
                pass
            assert state.model_dump(mode="json") == before
    assert len(seen) > 1


def test_every_reachable_unfinished_world_can_reach_both_endings():
    from twoworlds.domain.errors import DomainError

    initial = fresh()
    states = {key(initial): initial}
    pending = deque([initial])
    backwards = {}
    while pending:
        state = pending.popleft()
        source = key(state)
        for role in ("a", "b"):
            for action in possible_commands():
                before = state.model_dump(mode="json")
                try:
                    result = api().apply_command(state, script(), role, action)
                except DomainError:
                    assert state.model_dump(mode="json") == before
                    continue
                assert state.model_dump(mode="json") == before
                assert result.state.version == state.version + 1
                target = key(result.state)
                backwards.setdefault(target, set()).add(source)
                if target not in states:
                    states[target] = result.state
                    pending.append(result.state)
                assert len(states) < 1000
    unfinished = {
        identifier for identifier, state in states.items() if not state.completed
    }
    assert {state.ending_id for state in states.values() if state.completed} == {
        "guide_now",
        "wait_tide",
    }
    for ending in ("guide_now", "wait_tide"):
        reachable = {
            identifier
            for identifier, state in states.items()
            if state.ending_id == ending
        }
        todo = list(reachable)
        while todo:
            for source in backwards.get(todo.pop(), set()) - reachable:
                reachable.add(source)
                todo.append(source)
        assert unfinished <= reachable


def test_failure_after_a_tentative_fact_update_does_not_escape_to_the_input():
    from twoworlds.content.schema import ScriptVersion
    from twoworlds.domain.errors import DomainError

    # 仅修改内存中的测试副本：让锁定后的目标场景前置不满足，触发后段拒绝。
    document = script().model_dump(mode="json")
    document["scenes"][1]["entry_conditions"].append(
        {"kind": "fact", "fact_id": "clock_repaired", "equals": True}
    )
    restrictive = ScriptVersion.model_validate(document)
    state = at("aligned")
    before = state.model_dump(mode="json")
    with pytest.raises(DomainError) as error:
        api().apply_command(state, restrictive, "b", command("lock_signal"))
    assert error.value.code == "PRECONDITION_NOT_MET"
    assert state.model_dump(mode="json") == before
    assert state.fact("signal_locked") is False and state.scene_id == "calibration"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "inspect",
        {},
        {"kind": "inspect", "args": None},
        {"kind": "inspect", "args": []},
        {"kind": True, "args": {}},
    ],
)
def test_malformed_command_envelopes_raise_domain_errors_without_changes(payload):
    from twoworlds.domain.errors import DomainError

    state = fresh()
    before = state.model_dump(mode="json")
    with pytest.raises(DomainError) as error:
        api().apply_command(state, script(), "a", payload)
    assert error.value.code == "INVALID_COMMAND"
    assert state.model_dump(mode="json") == before


def test_applying_a_command_does_not_read_files_or_open_network_connections(
    monkeypatch,
):
    import builtins
    import socket

    state = at("tools")
    definition = script()

    def forbidden(*args, **kwargs):
        raise AssertionError("domain command attempted I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    result = api().apply_command(
        state, definition, "a", command("repair_clock", {"mode": "steady"})
    )
    assert result.state.fact("clock_repaired") is True


def test_schema_valid_but_unsupported_optical_values_raise_a_domain_error():
    from twoworlds.content.schema import ScriptVersion
    from twoworlds.domain.errors import DomainError

    data = script().model_dump(mode="json")
    emitter = data["devices"][0]["fields"]
    emitter[0]["choices"].append(45)
    emitter[0]["initial_value"] = 45
    emitter[1]["initial_value"] = "pulse"
    altered = ScriptVersion.model_validate(data)
    state = api().create_initial_state(altered)
    state = (
        api()
        .apply_command(state, altered, "b", command("inspect", {"target": "sea_chart"}))
        .state
    )
    before = state.model_dump(mode="json")
    with pytest.raises(DomainError) as error:
        api().apply_command(
            state, altered, "b", command("set_filter", {"filter": "amber"})
        )
    assert error.value.code == "INVALID_SCRIPT"
    assert state.model_dump(mode="json") == before


def test_declared_custom_error_codes_do_not_escape_as_python_key_errors():
    from twoworlds.content.schema import ScriptVersion
    from twoworlds.domain.errors import DomainError

    data = script().model_dump(mode="json")
    definition = next(item for item in data["actions"] if item["id"] == "set_emitter")
    definition["preconditions"].append(
        {"kind": "fact", "fact_id": "signal_locked", "equals": True}
    )
    definition["error_codes"] = ["CONTENT_ACTION_BLOCKED"]
    altered = ScriptVersion.model_validate(data)
    state = at("read")
    before = state.model_dump(mode="json")
    with pytest.raises(DomainError) as error:
        api().apply_command(
            state,
            altered,
            "a",
            command("set_emitter", {"angle": 90, "pattern": "pulse"}),
        )
    assert error.value.code == "CONTENT_ACTION_BLOCKED"
    assert state.model_dump(mode="json") == before


def test_domain_can_import_and_execute_when_web_storage_and_ai_imports_are_forbidden(
    tmp_path,
):
    code = """
import importlib.abc,json,sys
class Forbidden(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        names=('fastapi','httpx','pymongo','motor','langgraph','langchain','twoworlds.api','twoworlds.storage','twoworlds.ai')
        if any(fullname==name or fullname.startswith(name+'.') for name in names):
            raise AssertionError('domain imported forbidden adapter')
sys.meta_path.insert(0,Forbidden())
from twoworlds.content.schema import ScriptVersion
from twoworlds.domain.engine import create_initial_state,apply_command
script=ScriptVersion.model_validate_json(sys.stdin.read())
state=create_initial_state(script)
result=apply_command(state,script,'a',{'kind':'inspect','args':{'target':'maintenance_log'}})
assert result.state.version==1 and state.version==0
print('pure-domain-ok')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-c", code],
        input=script().model_dump_json(),
        cwd=tmp_path,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == "pure-domain-ok"
