"""Rules and projection consume the rebuilt script even for unchecked inputs."""

from pathlib import Path

from pydantic import ValidationError
import pytest

from twoworlds.content import loader
from twoworlds.content.schema import ScriptVersion
from twoworlds.domain.engine import (
    _require_script,
    apply_command,
    create_initial_state,
    validate_state,
)
from twoworlds.domain.projection import project_save


@pytest.fixture(params=["model_construct", "model_copy"])
def unchecked_script(request):
    script = loader.ScriptLoader(Path(loader.__file__).parent / "scripts").load(
        "lighthouse", "1.0.0"
    )
    raw = script.model_dump(mode="json")
    scene = next(item for item in raw["scenes"] if item["id"] == "calibration")
    scene["entry_conditions"] = [
        {"kind": "fact", "fact_id": "completed", "equals": False}
    ]
    scene["observations"][0]["text"] = "  需要规范化的观察文字  "
    action = next(item for item in raw["actions"] if item["id"] == "inspect_log")
    canonical = ScriptVersion.model_validate(raw)
    if request.param == "model_construct":
        return ScriptVersion.model_construct(**raw), canonical, scene

    unchecked = canonical.model_copy(
        update={
            "initial_state": canonical.initial_state.model_copy(
                update={"discovered_clues": raw["initial_state"]["discovered_clues"]}
            ),
            "scenes": [
                item.model_copy(
                    update={
                        "entry_conditions": scene["entry_conditions"],
                        "observations": scene["observations"],
                    }
                )
                if item.id == scene["id"]
                else item
                for item in canonical.scenes
            ],
            "actions": [
                item.model_copy(update={"effects": action["effects"]})
                if item.id == action["id"]
                else item
                for item in canonical.actions
            ],
        }
    )
    return unchecked, canonical, scene


def test_require_script_rebuilds_frozen_nested_models(unchecked_script):
    unchecked, canonical, raw_scene = unchecked_script
    rebuilt = _require_script(unchecked)
    scene = next(item for item in rebuilt.scenes if item.id == "calibration")

    assert rebuilt is not unchecked
    assert isinstance(rebuilt.scenes, tuple)
    assert isinstance(scene.entry_conditions, tuple)
    assert isinstance(scene.observations, tuple)
    assert scene.observations[0].text == "需要规范化的观察文字"
    raw_scene["entry_conditions"].clear()
    raw_scene["observations"][0]["text"] = "mutated"
    assert rebuilt == canonical
    with pytest.raises(ValidationError, match="frozen_instance"):
        scene.observations[0].text = "mutated"


def test_create_initial_state_consumes_rebuilt_script(unchecked_script):
    unchecked, canonical, _ = unchecked_script
    assert create_initial_state(unchecked) == create_initial_state(canonical)


def test_validate_state_consumes_rebuilt_script(unchecked_script):
    unchecked, canonical, _ = unchecked_script
    state = create_initial_state(canonical)
    assert validate_state(state, unchecked) == state


def test_apply_command_consumes_rebuilt_effects(unchecked_script):
    unchecked, canonical, _ = unchecked_script
    state = create_initial_state(canonical)
    command = {"kind": "inspect", "args": {"target": "maintenance_log"}}
    assert apply_command(state, unchecked, "a", command) == apply_command(
        state, canonical, "a", command
    )


def test_project_save_consumes_rebuilt_observations(unchecked_script):
    unchecked, canonical, raw_scene = unchecked_script
    state = create_initial_state(canonical)
    snapshot = project_save(state, unchecked, "a")
    raw_scene["observations"].clear()
    assert snapshot == project_save(state, canonical, "a")
