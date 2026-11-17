"""Same-save command/read projections through real SQLite and Mongo adapters."""

from tests.api import test_save_isolation as isolation
from tests.contracts.support import command, error

games = isolation.games
save_repository_factory = isolation.save_repository_factory
sqlite_repository_factory = isolation.sqlite_repository_factory


def visual(snapshot):
    return {
        item["id"]: item["value"] for item in snapshot["presentation"]["visual_state"]
    }


def test_lighthouse_same_save_cross_role_visual_feedback(games):
    factory, _, _ = games
    game, repo = factory()
    a, b, pair = game.pair()
    state = game.save(a, pair)
    state = game.accept(a, state, "inspect", {"target": "maintenance_log"})
    state = game.accept(b, state, "inspect", {"target": "sea_chart"})
    state = game.accept(a, state, "set_emitter", {"angle": 0, "pattern": "pulse"})
    assert "beam_destination" not in visual(game.read(b, state))
    state = game.accept(b, state, "set_filter", {"filter": "amber"})
    assert visual(state)["beam_destination"] == "reef"
    state = game.accept(a, state, "set_emitter", {"angle": 90, "pattern": "pulse"})
    received = game.read(b, state)
    assert received["id"] == state["id"] and received["version"] == state["version"]
    assert visual(received)["beam_destination"] == "inner_bay"
    assert "emitter" not in received["personal"]["devices"]
    assert not {"emitter_angle", "emitter_pattern"} & visual(received).keys()
    state = game.accept(b, state, "lock_signal")
    assert state["scene_id"] == "repair" and visual(state)["signal_locked"] is True
    assert visual(game.read(a, state))["clock_powered"] is False
    state = game.accept(b, state, "route_power", {"target": "tower"})
    powered = game.read(a, state)
    assert visual(powered)["clock_powered"] is True
    assert "power_target" not in visual(powered)
    assert "power_router" not in powered["personal"]["devices"]
    state = game.accept(a, state, "inspect", {"target": "clock_gears"})
    before = repo.get_save(state["id"])
    error(
        game.post(a, state, command(state, "repair_clock", {"mode": "fast"})),
        422,
        "REPAIR_MODE_UNSAFE",
    )
    assert repo.get_save(state["id"]) == before
    assert game.read(a, state) == state
    state = game.accept(a, state, "repair_clock", {"mode": "steady"})
    assert visual(game.read(b, state))["route_ready"] is True
    state = game.accept(b, state, "route_power", {"target": "shore"})
    assert visual(game.read(a, state))["clock_repaired"] is True
    assert visual(game.read(a, state))["clock_powered"] is False
    state = game.accept(b, state, "route_power", {"target": "tower"})
    state = game.accept(b, state, "confirm_route")
    assert state["scene_id"] == "decision"
    state = game.accept(a, state, "vote_ending", {"choice": "guide_now"})
    state = game.accept(b, state, "vote_ending", {"choice": "guide_now"})
    assert state["completed"] and state["public"]["ending"] == "guide_now"
    assert not state["available_actions"]


def test_starline_same_save_cross_role_visual_feedback(games):
    factory, _, _ = games
    game, repo = factory()
    a, b, pair = game.pair()
    state = game.save(a, pair, "starline")
    state = game.accept(a, state, "inspect", {"target": "station_log"})
    state = game.accept(b, state, "inspect", {"target": "power_board"})
    state = game.accept(
        b, state, "allocate_power", {"engine": False, "sonar": True, "lamp": False}
    )
    assert visual(state)["echo_available"] is False
    state = game.accept(a, state, "set_echo_gate", {"position": "east"})
    echo = game.read(b, state)
    assert visual(echo)["echo_available"] is True
    assert "echo_gate" not in echo["personal"]["devices"]
    assert "gate_position" not in visual(echo)
    assert "scanned_segment" not in visual(game.read(a, state))
    before = repo.get_save(state["id"])
    error(
        game.post(
            b,
            state,
            command(
                state, "allocate_power", {"engine": True, "sonar": True, "lamp": True}
            ),
        ),
        422,
        "POWER_BUDGET_EXCEEDED",
    )
    assert repo.get_save(state["id"]) == before
    assert game.read(b, state) == echo
    state = game.accept(b, state, "scan_track")
    assert visual(game.read(a, state))["scanned_segment"] == "bridge_2"
    state = game.accept(a, state, "install_rail", {"segment": "bridge_2"})
    assert state["scene_id"] == "boarding"
    assert visual(game.read(b, state))["rail_connected"] is True
    assert visual(game.read(a, state))["signal_confirmed"] is False
    state = game.accept(
        b, state, "allocate_power", {"engine": True, "sonar": False, "lamp": True}
    )
    power = visual(state)
    assert (
        power["engine_on"] is True
        and power["lamp_on"] is True
        and power["sonar_on"] is False
    )
    state = game.accept(b, state, "confirm_signal")
    assert visual(game.read(a, state))["confirmed_signal"] == "blue_double_flash"
    assert "engine_on" not in visual(game.read(a, state))
    state = game.accept(a, state, "set_platform", {"track": "track_2"})
    assert "platform_track" not in visual(game.read(b, state))
    state = game.accept(b, state, "dispatch_train")
    assert state["scene_id"] == "decision" and visual(state)["train_arrived"] is True
    state = game.accept(a, state, "vote_ending", {"choice": "return_station"})
    state = game.accept(b, state, "vote_ending", {"choice": "return_station"})
    assert state["completed"] and state["public"]["ending"] == "return_station"
