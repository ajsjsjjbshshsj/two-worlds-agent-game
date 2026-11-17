"""Playback policy for existing immutable content; no puzzle rules or state."""


def operation_sounds(script_id: str) -> dict[str, str]:
    """Asset -> device whose confirmed change can play it (never prose matching)."""
    return {
        "lighthouse": {
            "emitter_click": "emitter",
            "receiver_tone": "filter",
            "power_panel": "power_router",
        },
        "starline": {
            "gate_movement": "echo_gate",
            "power_switch": "power_panel",
        },
    }.get(script_id, {})
