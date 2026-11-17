"""Role-filtered visual effects; never send a partner's device configuration.

The gates mirror the mechanics' observable feedback. These are presentation
values, not new world facts or client-side puzzle rules.
"""

from twoworlds.content.schema import ContentModel, Identifier, Role, Scalar

from .models import GameState


class VisualEffect(ContentModel):
    id: Identifier
    value: Scalar


def project_visuals(
    state: GameState, script_id: str, role: Role
) -> tuple[VisualEffect, ...]:
    values: dict[str, Scalar] = {}
    stage = state.scene_id
    if script_id == "lighthouse":
        if stage == "calibration":
            if role == "a":
                values.update(
                    emitter_angle=state.device("emitter", "angle"),
                    emitter_pattern=state.device("emitter", "pattern"),
                )
            else:
                tint = state.device("filter", "filter")
                values["filter_tint"] = tint
                identified = "b_sea_chart" in state.discovered_clues
                clear = (
                    identified
                    and tint == "amber"
                    and state.device("emitter", "pattern") == "pulse"
                )
                values["beam_quality"] = (
                    "clear" if clear else "blurred" if identified else "unidentified"
                )
                if clear:
                    values["beam_destination"] = {
                        0: "reef",
                        90: "inner_bay",
                        180: "observatory",
                        270: "outer_harbor",
                    }[state.device("emitter", "angle")]
        else:
            # Lock/repair are shared milestones. Power destination remains B-only.
            values["signal_locked"] = state.fact("signal_locked")
            values["clock_repaired"] = state.fact("clock_repaired")
            if stage == "repair":
                powered = state.device("power_router", "target") == "tower"
                if role == "a":
                    values["clock_powered"] = powered
                else:
                    values["power_target"] = state.device("power_router", "target")
                    values["route_ready"] = powered and state.fact("clock_repaired")
    elif script_id == "starline":
        values["rail_connected"] = state.fact("rail_installed")
        values["train_arrived"] = state.fact("train_dispatched")
        values["signal_confirmed"] = state.fact("signal_confirmed")
        if stage in {"survey", "boarding"}:
            if role == "a":
                values["gate_position"] = state.device("echo_gate", "position")
                values["platform_track"] = state.device("platform", "track")
            else:
                for key in ("engine", "sonar", "lamp"):
                    values[f"{key}_on"] = state.device("power_panel", key)
                if stage == "survey":
                    values["echo_available"] = (
                        state.device("echo_gate", "position") == "east"
                        and state.device("power_panel", "sonar")
                        and not state.device("power_panel", "engine")
                    )
            if state.fact("track_scanned"):
                values["scanned_segment"] = state.fact("scanned_segment")
            if state.fact("signal_confirmed"):
                values["confirmed_signal"] = state.fact("confirmed_signal")
    return tuple(
        VisualEffect(id=key, value=value) for key, value in sorted(values.items())
    )
