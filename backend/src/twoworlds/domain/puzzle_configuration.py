"""Apply shared generation changes after an otherwise valid rules command."""

from .mechanics.common import same
from .models import GameState
from .puzzles import LighthousePuzzles, Puzzles, StarlinePuzzles


def _changed(before: GameState, after: GameState, device: str, *fields: str) -> bool:
    return any(
        not same(before.device(device, field), after.device(device, field))
        for field in fields
    )


def update_puzzle_configuration(before: GameState, after: GameState) -> Puzzles | None:
    puzzles = after.puzzles
    if isinstance(puzzles, LighthousePuzzles):
        optics = _changed(before, after, "emitter", "angle", "pattern") or _changed(
            before, after, "filter", "filter"
        )
        tide = _changed(before, after, "power_router", "target") or (
            before.fact("clock_repaired") != after.fact("clock_repaired")
        )
        return LighthousePuzzles(
            l03=puzzles.l03.change_optics() if optics else puzzles.l03,
            l05=puzzles.l05.change_tide_config() if tide else puzzles.l05,
        )
    if isinstance(puzzles, StarlinePuzzles):
        power = _changed(before, after, "power_panel", "engine", "sonar", "lamp")
        survey = before.scene_id == "survey" and (
            power or _changed(before, after, "echo_gate", "position")
        )
        approach = puzzles.s05
        if before.scene_id == "boarding":
            if _changed(before, after, "platform", "track"):
                approach = approach.change_alignment(power_changed=power)
            elif power:
                approach = approach.change_drive_power()
        return StarlinePuzzles(
            s03=puzzles.s03.change_survey_config() if survey else puzzles.s03,
            s05=approach,
        )
    return None
