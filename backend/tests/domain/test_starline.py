"""Real versioned Starline rules: no API, repository, AI or simulated engine."""

from collections import deque
from copy import deepcopy
from functools import lru_cache
from itertools import product
from pathlib import Path

import pytest

from twoworlds.content import loader
from twoworlds.domain.engine import apply_command, create_initial_state, validate_state
from twoworlds.domain.errors import DomainError
from twoworlds.domain.projection import project_save


@lru_cache
def script():
    return loader.ScriptLoader(Path(loader.__file__).parent / "scripts").load(
        "starline", "1.0.0"
    )


def accept(state, role, kind, **args):
    before = state.model_copy(deep=True)
    action = {"kind": kind, "args": args}
    original = deepcopy(action)
    result = apply_command(state, script(), role, action)
    assert state == before and action == original
    assert result.state is not state and result.state.version == state.version + 1
    assert result.events and all(
        event.version == result.state.version for event in result.events
    )
    assert validate_state(result.state, script()) == result.state
    return result


def reject(state, role, kind, code, **args):
    before = state.model_copy(deep=True)
    action = {"kind": kind, "args": args}
    original = deepcopy(action)
    with pytest.raises(DomainError) as error:
        apply_command(state, script(), role, action)
    assert error.value.code == code
    assert state == before and action == original


TRACE = (
    ("a", "inspect", {"target": "station_log"}),
    ("b", "inspect", {"target": "power_board"}),
    ("a", "set_echo_gate", {"position": "east"}),
    ("b", "allocate_power", {"engine": False, "sonar": True, "lamp": True}),
    ("b", "scan_track", {}),
    ("a", "install_rail", {"segment": "bridge_2"}),
    ("b", "allocate_power", {"engine": True, "sonar": False, "lamp": True}),
    ("b", "confirm_signal", {}),
    ("a", "set_platform", {"track": "track_2"}),
    ("b", "dispatch_train", {}),
)


def at(phase="fresh"):
    state = create_initial_state(script())
    count = {
        "fresh": 0,
        "read": 2,
        "powered": 4,
        "scanned": 5,
        "boarding": 6,
        "signal": 8,
        "platform": 9,
        "decision": 10,
    }[phase]
    for role, kind, args in TRACE[:count]:
        state = accept(state, role, kind, **args).state
    return state


def finish(ending):
    state = at("decision")
    state = accept(state, "a", "vote_ending", choice=ending).state
    return accept(state, "b", "vote_ending", choice=ending)


def test_initial_state_and_private_devices():
    state = at()
    assert (state.script_id, state.script_version, state.scene_id, state.version) == (
        "starline",
        "1.0.0",
        "survey",
        0,
    )
    assert state.device("echo_gate", "position") == "closed"
    assert state.device("platform", "track") == "unset"
    assert all(
        state.device("power_panel", field) is False
        for field in ("engine", "sonar", "lamp")
    )
    assert all(
        state.fact(key) is False
        for key in (
            "track_scanned",
            "rail_installed",
            "signal_confirmed",
            "train_dispatched",
            "completed",
        )
    )
    assert state.fact("ending_id") == "none" and state.ending_id is None
    assert not state.discovered_clues and not state.shared_clues and not state.votes
    assert not state.completed


@pytest.mark.parametrize("ending", ["rescue_detour", "return_station"])
def test_complete_trace_and_two_real_endings(ending):
    result = finish(ending)
    state = result.state
    assert state.scene_id == "completed" and state.completed
    assert state.ending_id == state.fact("ending_id") == ending
    assert {vote.ending_id for vote in state.votes} == {ending}
    assert all(
        state.fact(key) is True
        for key in (
            "track_scanned",
            "rail_installed",
            "signal_confirmed",
            "train_dispatched",
            "completed",
        )
    )
    assert sum(event.kind == "game_completed" for event in result.events) == 1


@pytest.mark.parametrize("phase", ["read", "boarding"])
@pytest.mark.parametrize("engine,sonar,lamp", product((False, True), repeat=3))
def test_every_power_combination_is_atomic_and_strictly_budgeted(
    phase, engine, sonar, lamp
):
    state = at(phase)
    args = {"engine": engine, "sonar": sonar, "lamp": lamp}
    used = 3 * engine + 3 * sonar + lamp
    if used > 5:
        reject(state, "b", "allocate_power", "POWER_BUDGET_EXCEEDED", **args)
    elif all(state.device("power_panel", key) is value for key, value in args.items()):
        reject(state, "b", "allocate_power", "NO_STATE_CHANGE", **args)
    else:
        result = accept(state, "b", "allocate_power", **args)
        assert all(
            result.state.device("power_panel", key) is value
            for key, value in args.items()
        )
        assert all(
            event.audience == "b"
            for event in result.events
            if event.kind == "device_changed"
        )


@pytest.mark.parametrize(
    "phase,role,kind,args,code",
    [
        ("fresh", "a", "set_echo_gate", {"position": "east"}, "CLUE_NOT_DISCOVERED"),
        (
            "fresh",
            "b",
            "allocate_power",
            {"engine": False, "sonar": True, "lamp": False},
            "CLUE_NOT_DISCOVERED",
        ),
        ("read", "b", "scan_track", {}, "SCAN_UNAVAILABLE"),
        ("fresh", "a", "install_rail", {"segment": "bridge_2"}, "TRACK_NOT_SCANNED"),
        ("read", "a", "install_rail", {"segment": "bridge_2"}, "TRACK_NOT_SCANNED"),
        ("boarding", "a", "set_platform", {"track": "track_2"}, "SIGNAL_NOT_CONFIRMED"),
        ("boarding", "b", "dispatch_train", {}, "DISPATCH_NOT_READY"),
        ("fresh", "b", "confirm_signal", {}, "ACTION_UNAVAILABLE"),
        (
            "fresh",
            "a",
            "vote_ending",
            {"choice": "rescue_detour"},
            "ACTION_UNAVAILABLE",
        ),
    ],
)
def test_failed_prerequisites_leave_complete_state_and_version_unchanged(
    phase, role, kind, args, code
):
    reject(at(phase), role, kind, code, **args)


@pytest.mark.parametrize(
    "role,kind,args",
    [
        ("b", "inspect", {"target": "station_log"}),
        ("a", "inspect", {"target": "power_board"}),
        ("b", "set_echo_gate", {"position": "east"}),
        ("a", "allocate_power", {"engine": False, "sonar": True, "lamp": False}),
        ("a", "scan_track", {}),
        ("b", "install_rail", {"segment": "bridge_2"}),
        ("a", "confirm_signal", {}),
        ("b", "set_platform", {"track": "track_2"}),
        ("a", "dispatch_train", {}),
    ],
)
def test_opposite_role_cannot_operate_partner_devices(role, kind, args):
    reject(at("read"), role, kind, "ROLE_FORBIDDEN", **args)


@pytest.mark.parametrize(
    "role,kind,args",
    [
        ("b", "allocate_power", {"engine": 1, "sonar": False, "lamp": False}),
        ("b", "allocate_power", {"engine": "true", "sonar": False, "lamp": False}),
        ("b", "allocate_power", {"engine": False, "sonar": False}),
        (
            "b",
            "allocate_power",
            {"engine": False, "sonar": False, "lamp": True, "budget": 100},
        ),
        ("a", "set_echo_gate", {"position": "north"}),
        ("a", "install_rail", {"segment": "bridge_1"}),
        ("a", "set_platform", {"track": "track_4"}),
        ("a", "vote_ending", {"choice": "guide_now"}),
    ],
)
def test_invalid_parameters_do_not_write_partial_state(role, kind, args):
    phase = (
        "decision"
        if kind == "vote_ending"
        else "signal"
        if kind == "set_platform"
        else "read"
    )
    reject(at(phase), role, kind, "INVALID_ARGUMENTS", **args)


@pytest.mark.parametrize("position", ["closed", "west"])
def test_sonar_needs_a_real_east_echo_path(position):
    state = at("powered")
    state = accept(state, "a", "set_echo_gate", position=position).state
    reject(state, "b", "scan_track", "SCAN_UNAVAILABLE")
    state = accept(state, "a", "set_echo_gate", position="east").state
    scanned = accept(state, "b", "scan_track").state
    assert scanned.fact("scanned_segment") == "bridge_2"


def test_engine_noise_and_sonar_power_are_real_scan_prerequisites():
    state = at("powered")
    state = accept(
        state, "b", "allocate_power", engine=True, sonar=False, lamp=True
    ).state
    reject(state, "b", "scan_track", "SCAN_UNAVAILABLE")
    state = accept(
        state, "b", "allocate_power", engine=False, sonar=True, lamp=False
    ).state
    assert accept(state, "b", "scan_track").state.fact("track_scanned") is True


@pytest.mark.parametrize("track", ["unset", "track_1", "track_3"])
def test_wrong_track_rejected_then_can_recover(track):
    state = at("signal")
    if track != "unset":
        state = accept(state, "a", "set_platform", track=track).state
    reject(state, "b", "dispatch_train", "WRONG_TRACK")
    state = accept(state, "a", "set_platform", track="track_2").state
    assert accept(state, "b", "dispatch_train").state.scene_id == "decision"


def test_power_loss_preserves_confirmed_signal_and_can_recover():
    state = at("signal")
    state = accept(
        state, "b", "allocate_power", engine=False, sonar=False, lamp=False
    ).state
    assert state.fact("signal_confirmed") is True
    state = accept(state, "a", "set_platform", track="track_2").state
    reject(state, "b", "dispatch_train", "DISPATCH_NOT_READY")
    state = accept(
        state, "b", "allocate_power", engine=True, sonar=False, lamp=True
    ).state
    assert accept(state, "b", "dispatch_train").state.fact("train_dispatched") is True


def test_confirming_signal_needs_lamp_and_does_not_auto_enable_it():
    state = at("boarding")
    state = accept(
        state, "b", "allocate_power", engine=True, sonar=False, lamp=False
    ).state
    reject(state, "b", "confirm_signal", "SIGNAL_UNAVAILABLE")


def test_scan_is_retained_if_gate_changes_and_gate_locks_only_after_installation():
    state = at("scanned")
    state = accept(state, "a", "set_echo_gate", position="west").state
    assert state.fact("track_scanned") is True
    state = accept(state, "a", "install_rail", segment="bridge_2").state
    assert (
        state.scene_id == "boarding" and state.device("echo_gate", "position") == "west"
    )
    reject(state, "a", "set_echo_gate", "ACTION_UNAVAILABLE", position="east")


@pytest.mark.parametrize(
    "reverse_reads,reverse_setup", product((False, True), repeat=2)
)
def test_legal_exploration_orders_can_still_dispatch(reverse_reads, reverse_setup):
    state = at()
    reads = list(TRACE[:2])
    setup = list(TRACE[2:4])
    for role, kind, args in (
        (reads[::-1] if reverse_reads else reads)
        + (setup[::-1] if reverse_setup else setup)
        + list(TRACE[4:])
    ):
        state = accept(state, role, kind, **args).state
    assert state.scene_id == "decision" and not state.completed


def test_disagreement_revote_and_duplicate_vote():
    state = at("decision")
    state = accept(state, "a", "vote_ending", choice="rescue_detour").state
    state = accept(state, "b", "vote_ending", choice="return_station").state
    assert not state.completed and state.ending_id is None
    reject(state, "a", "vote_ending", "NO_STATE_CHANGE", choice="rescue_detour")
    state = accept(state, "a", "vote_ending", choice="return_station").state
    assert state.completed and state.ending_id == "return_station"


@pytest.mark.parametrize("role", ["a", "b"])
def test_one_role_cannot_complete_any_reachable_world(role):
    pending = deque([at()])
    seen = set()
    actions = [
        (action.kind, {p.id: v for p, v in zip(action.parameters, values)})
        for action in script().actions
        for values in product(*(p.choices for p in action.parameters))
    ]
    actions += [("share_clue", {"clue_id": clue.id}) for clue in script().clues]
    while pending:
        state = pending.popleft()
        key = state.model_dump_json(exclude={"version"})
        if key in seen:
            continue
        seen.add(key)
        assert not state.completed
        for kind, args in actions:
            before = state.model_copy(deep=True)
            try:
                pending.append(
                    apply_command(
                        state, script(), role, {"kind": kind, "args": args}
                    ).state
                )
            except DomainError:
                pass
            assert state == before
    assert len(seen) > 1


@pytest.mark.parametrize(
    "role,kind,args",
    [
        ("a", "vote_ending", {"choice": "return_station"}),
        ("b", "dispatch_train", {}),
        ("b", "allocate_power", {"engine": False, "sonar": True, "lamp": False}),
    ],
)
def test_completed_game_cannot_change_ending_or_world(role, kind, args):
    reject(finish("rescue_detour").state, role, kind, "SAVE_COMPLETED", **args)


def test_bidirectional_feedback_and_private_clues_in_events_and_projection():
    state = at("read")
    state = accept(
        state, "b", "allocate_power", engine=False, sonar=True, lamp=True
    ).state
    before_b = project_save(state, script(), "b").personal.observations
    opened = accept(state, "a", "set_echo_gate", position="east")
    state = opened.state
    assert project_save(state, script(), "b").personal.observations != before_b
    before_a = project_save(state, script(), "a").personal.observations
    scanned = accept(state, "b", "scan_track")
    assert project_save(scanned.state, script(), "a").personal.observations != before_a
    assert any(e.audience == "public" and "bridge_2" in e.text for e in scanned.events)
    state = at("boarding")
    state = accept(
        state, "b", "allocate_power", engine=True, sonar=False, lamp=True
    ).state
    before_a = project_save(state, script(), "a").personal.observations
    state = accept(state, "b", "confirm_signal").state
    assert project_save(state, script(), "a").personal.observations != before_a
    before_b = project_save(state, script(), "b").personal.observations
    state = accept(state, "a", "set_platform", track="track_2").state
    assert project_save(state, script(), "b").personal.observations != before_b
    for role, other in (("a", "b"), ("b", "a")):
        encoded = project_save(state, script(), role).model_dump_json()
        for clue in script().clues:
            if clue.role == other:
                assert clue.text not in encoded
        assert all(obs.audience in {"a", "b"} for obs in state.observations)
    initial = at()
    for role, target in (("a", "station_log"), ("b", "power_board")):
        discovered = accept(initial, role, "inspect", target=target)
        assert all(
            e.audience == role for e in discovered.events if e.kind == "clue_discovered"
        )


@pytest.mark.parametrize(
    "phase,changes",
    [
        ("fresh", {"completed": True, "scene_id": "completed"}),
        ("read", {"scene_id": "boarding"}),
        ("boarding", {"scene_id": "decision"}),
        ("read", {"scene_id": "decision", "ending_id": "rescue_detour"}),
    ],
)
def test_inconsistent_state_cannot_skip_phases(phase, changes):
    state = at(phase).model_copy(update=changes)
    before = state.model_copy(deep=True)
    with pytest.raises(DomainError) as error:
        validate_state(state, script())
    assert error.value.code == "INVALID_STATE" and state == before


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "set_fact", "args": {"completed": True}},
        {"kind": "enter_scene", "args": {"scene_id": "completed"}},
        {"kind": "scan_track", "args": {}, "completed": True},
    ],
)
def test_clients_cannot_submit_world_patches(action):
    state = at("read")
    before = state.model_copy(deep=True)
    with pytest.raises(DomainError) as error:
        apply_command(state, script(), "b", action)
    assert error.value.code in {"UNKNOWN_ACTION", "INVALID_COMMAND"}
    assert state == before


@pytest.mark.parametrize(
    "phase,fact_id,value",
    [
        ("fresh", "track_scanned", True),
        ("fresh", "scanned_segment", "bridge_2"),
        ("fresh", "rail_installed", True),
        ("boarding", "signal_confirmed", True),
        ("boarding", "train_dispatched", True),
        ("fresh", "confirmed_signal", "blue_double_flash"),
    ],
)
def test_forged_facts_cannot_bypass_causal_invariants(phase, fact_id, value):
    state = at(phase)
    facts = tuple(
        f.model_copy(update={"value": value}) if f.id == fact_id else f
        for f in state.facts
    )
    state = state.model_copy(update={"facts": facts})
    before = state.model_copy(deep=True)
    with pytest.raises(DomainError) as error:
        validate_state(state, script())
    assert error.value.code == "INVALID_STATE" and state == before


def test_loaded_state_cannot_contain_an_overbudget_power_group():
    state = at("read")
    devices = tuple(
        d.model_copy(
            update={
                "fields": tuple(
                    f.model_copy(update={"value": True})
                    if f.id in {"engine", "sonar"}
                    else f
                    for f in d.fields
                )
            }
        )
        if d.id == "power_panel"
        else d
        for d in state.devices
    )
    state = state.model_copy(update={"devices": devices})
    before = state.model_copy(deep=True)
    with pytest.raises(DomainError) as error:
        validate_state(state, script())
    assert error.value.code == "INVALID_STATE" and state == before


@pytest.mark.parametrize(
    "phase,role,kind,args,code",
    [
        ("read", "a", "inspect", {"target": "station_log"}, "ALREADY_DISCOVERED"),
        ("powered", "a", "set_echo_gate", {"position": "east"}, "NO_STATE_CHANGE"),
        ("scanned", "b", "scan_track", {}, "NO_STATE_CHANGE"),
        ("signal", "b", "confirm_signal", {}, "NO_STATE_CHANGE"),
        ("platform", "a", "set_platform", {"track": "track_2"}, "NO_STATE_CHANGE"),
    ],
)
def test_repeated_operations_do_not_consume_a_version(phase, role, kind, args, code):
    reject(at(phase), role, kind, code, **args)


def test_only_explicitly_registered_script_identifiers_execute_rules():
    from twoworlds.content.schema import ScriptVersion

    raw = script().model_dump(mode="json")
    raw["metadata"]["id"] = "os"
    unregistered = ScriptVersion.model_validate(raw)
    with pytest.raises(DomainError) as error:
        create_initial_state(unregistered)
    assert error.value.code == "SCRIPT_UNSUPPORTED"
