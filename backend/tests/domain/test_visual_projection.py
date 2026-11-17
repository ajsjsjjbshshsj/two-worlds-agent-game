import pytest
from pydantic import ValidationError

from tests.domain.test_projection import script, at, act, project
from tests.domain.test_starline import script as star_script
from twoworlds.domain.engine import create_initial_state


def visual(state, role, content=None):
    return {
        v.id: v.value for v in project(state, role, content).presentation.visual_state
    }


def test_lighthouse_observable_effects_without_partner_configuration():
    state = at("read")
    hidden = visual(state, "b")
    assert "beam_destination" not in hidden
    state = act(state, "a", "set_emitter", angle=0, pattern="pulse")
    state = act(state, "b", "set_filter", filter="amber")
    assert visual(state, "b")["beam_destination"] == "reef"
    state = act(state, "a", "set_emitter", angle=90, pattern="pulse")
    assert visual(state, "b")["beam_destination"] == "inner_bay"
    assert visual(state, "b")["beam_quality"] == "clear"
    assert not {"emitter_angle", "emitter_pattern"} & visual(state, "b").keys()
    assert "beam_destination" not in visual(state, "a")
    state = act(state, "b", "lock_signal")
    assert visual(state, "b")["signal_locked"] is True
    assert visual(state, "a")["clock_powered"] is False
    state = act(state, "b", "route_power", target="tower")
    assert visual(state, "a")["clock_powered"] is True
    assert "power_target" not in visual(state, "a")
    state = act(state, "a", "inspect", target="clock_gears")
    state = act(state, "a", "repair_clock", mode="steady")
    assert visual(state, "a")["clock_repaired"] is True
    assert visual(state, "b")["route_ready"] is True


def test_starline_bidirectional_visual_permissions():
    content = star_script()
    state = create_initial_state(content)
    state = act(state, "a", "inspect", content, target="station_log")
    state = act(state, "b", "inspect", content, target="power_board")
    state = act(state, "a", "set_echo_gate", content, position="east")
    state = act(
        state, "b", "allocate_power", content, engine=False, sonar=True, lamp=False
    )
    b = visual(state, "b", content)
    assert b["echo_available"] is True and b["sonar_on"] is True
    assert b["engine_on"] is False and b["lamp_on"] is False
    assert "gate_position" not in b and "scanned_segment" not in b
    state = act(state, "b", "scan_track", content)
    assert visual(state, "a", content)["scanned_segment"] == "bridge_2"
    state = act(state, "a", "install_rail", content, segment="bridge_2")
    assert visual(state, "b", content)["rail_connected"] is True
    assert "engine_on" not in visual(state, "a", content)


def test_visuals_do_not_mutate_world_and_keep_frozen_contract():
    state = at("read")
    before = state.model_dump_json()
    assert project(state, "a").presentation.visual_state
    assert state.model_dump_json() == before
    snapshot = project(state, "a")
    assert isinstance(snapshot.presentation.visual_state, tuple)
    with pytest.raises(ValidationError):
        snapshot.presentation.visual_state[0].value = "tampered"


@pytest.mark.parametrize(
    "angle,destination",
    [(0, "reef"), (90, "inner_bay"), (180, "observatory"), (270, "outer_harbor")],
)
def test_beam_effect_requires_chart_pattern_and_filter(angle, destination):
    state = act(at("read"), "a", "set_emitter", angle=angle, pattern="pulse")
    assert "beam_destination" not in visual(state, "b")
    state = act(state, "b", "set_filter", filter="amber")
    assert visual(state, "b")["beam_destination"] == destination
    state = act(state, "b", "set_filter", filter="clear")
    assert visual(state, "b")["beam_quality"] == "blurred"
    assert "beam_destination" not in visual(state, "b")
    state = act(state, "b", "set_filter", filter="amber")
    state = act(state, "a", "set_emitter", angle=angle, pattern="steady")
    assert "beam_destination" not in visual(state, "b")
    # Configuring the sender cannot reveal a direction before B discovers its chart.
    unread = act(at("log"), "a", "set_emitter", angle=angle, pattern="pulse")
    assert visual(unread, "b")["beam_quality"] == "unidentified"


def test_repair_is_persistent_while_clock_power_and_route_feedback_change():
    state = at("repaired")
    state = act(state, "b", "route_power", target="shore")
    assert visual(state, "a")["clock_repaired"] is True
    assert visual(state, "a")["clock_powered"] is False
    assert visual(state, "b")["route_ready"] is False
    state = act(state, "b", "route_power", target="tower")
    assert visual(state, "b")["route_ready"] is True


@pytest.mark.parametrize(
    "phase", ["fresh", "read", "repair", "repaired", "decision", "completed"]
)
def test_lighthouse_visual_whitelists_never_expose_partner_fields(phase):
    state = at(phase)
    a, b = visual(state, "a"), visual(state, "b")
    assert (
        not {"filter_tint", "power_target", "beam_destination", "route_ready"}
        & a.keys()
    )
    assert (
        not {"emitter_angle", "emitter_pattern", "clock_powered", "repair_tools_ready"}
        & b.keys()
    )
    for effect in project(state, "b").presentation.visual_state:
        assert set(effect.model_dump()) == {"id", "value"}
    assert state.script_id == script().metadata.id


@pytest.mark.parametrize(
    "engine,sonar,lamp",
    [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (True, False, True),
        (False, True, True),
    ],
)
def test_starline_individual_power_effects(engine, sonar, lamp):
    content = star_script()
    from tests.domain.test_starline import at as star_at

    state = star_at("read")
    if engine or sonar or lamp:
        state = act(
            state, "b", "allocate_power", content, engine=engine, sonar=sonar, lamp=lamp
        )
    b = visual(state, "b", content)
    assert (b["engine_on"], b["sonar_on"], b["lamp_on"]) == (engine, sonar, lamp)
    assert not {"engine_on", "sonar_on", "lamp_on"} & visual(state, "a", content).keys()
