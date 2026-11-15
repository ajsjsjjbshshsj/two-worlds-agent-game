"""Formal Starline content, distinct mechanics and honest unreleased media."""

from copy import deepcopy
from pathlib import Path

from pydantic import ValidationError
import pytest

from twoworlds.content import loader
from twoworlds.content.publication import PublicationStore
from twoworlds.content.schema import ScriptVersion


def story():
    return loader.ScriptLoader(Path(loader.__file__).parent / "scripts").load(
        "starline", "1.0.0"
    )


def test_formal_json_loads_with_frozen_schema_and_precise_version():
    content = story()
    assert content.metadata.title == "末班星轨"
    assert (content.metadata.id, content.metadata.content_version) == (
        "starline",
        "1.0.0",
    )
    assert ScriptVersion.model_validate_json(content.model_dump_json()) == content
    with pytest.raises(loader.ScriptLoadError) as error:
        loader.ScriptLoader(Path(loader.__file__).parent / "scripts").load(
            "starline", "9.0.0"
        )
    assert error.value.code == "CONTENT_NOT_FOUND"


def test_four_scenes_and_different_roles_and_mechanics():
    content = story()
    assert [s.id for s in content.scenes] == [
        "survey",
        "boarding",
        "decision",
        "completed",
    ]
    assert [s.next_scene_ids for s in content.scenes] == [
        ("boarding",),
        ("decision",),
        ("completed",),
        (),
    ]
    assert [s.terminal for s in content.scenes] == [False, False, False, True]
    assert {d.id: d.role for d in content.devices} == {
        "echo_gate": "a",
        "platform": "a",
        "power_panel": "b",
    }
    assert not {
        "set_emitter",
        "lock_signal",
        "repair_clock",
        "confirm_route",
    }.intersection(a.kind for a in content.actions)
    assert {c.role for c in content.clues} == {"a", "b"}


def test_initial_values_and_choices_are_real_formal_declarations():
    content = story()
    assert content.initial_state.scene_id == "survey"
    assert (
        not content.initial_state.discovered_clues and not content.initial_state.votes
    )
    facts = {f.id: f.initial_value for f in content.facts}
    assert all(
        facts[k] is False
        for k in (
            "track_scanned",
            "rail_installed",
            "signal_confirmed",
            "train_dispatched",
            "completed",
        )
    )
    assert facts["ending_id"] == "none"
    devices = {d.id: {f.id: f.initial_value for f in d.fields} for d in content.devices}
    assert devices["echo_gate"] == {"position": "closed"}
    assert devices["power_panel"] == {"engine": False, "sonar": False, "lamp": False}
    assert devices["platform"] == {"track": "unset"}
    allocate = next(a for a in content.actions if a.kind == "allocate_power")
    assert {p.id for p in allocate.parameters} == {"engine", "sonar", "lamp"}
    assert all(
        p.value_type == "boolean" and set(p.choices) == {False, True}
        for p in allocate.parameters
    )


@pytest.mark.parametrize("ending", ["rescue_detour", "return_station"])
def test_both_declared_endings_have_real_rule_paths(ending):
    from tests.domain.test_starline import finish

    assert ending in {e.id for e in story().endings}
    result = finish(ending)
    assert result.state.completed and result.state.ending_id == ending


@pytest.mark.parametrize("part", ["scene", "clue", "device", "ending", "asset"])
def test_invalid_references_are_rejected_by_existing_schema(part):
    raw = deepcopy(story().model_dump(mode="json"))
    if part == "scene":
        raw["scenes"][0]["next_scene_ids"] = ["missing"]
    elif part == "clue":
        raw["actions"][0]["effects"][0]["clue_id"] = "missing"
    elif part == "device":
        next(
            e for a in raw["actions"] for e in a["effects"] if e["op"] == "set_device"
        )["device_id"] = "missing"
    elif part == "ending":
        next(a for a in raw["actions"] if a["kind"] == "vote_ending")["parameters"][0][
            "choices"
        ] = ["missing"]
    else:
        raw["presentation"][0]["background_asset_id"] = "missing"
    with pytest.raises(ValidationError):
        ScriptVersion.model_validate(raw)


def test_every_scene_has_two_views_and_all_media_remain_unproduced_and_unpublished():
    content = story()
    assert {(v.scene_id, v.role) for v in content.presentation} == {
        (s.id, r) for s in content.scenes for r in ("a", "b")
    }
    media = {m.id: m for m in content.media}
    for view in content.presentation:
        assert media[view.background_asset_id].audience == view.role
    for asset in content.media:
        assert asset.content_version == "1.0.0"
        assert (
            "待制作" in asset.source
            and "待核验" in asset.license
            and "禁止生产发布" in asset.license
        )
        assert asset.path.startswith("starline/1.0.0/")
        assert not (Path(loader.__file__).parent / "assets" / asset.path).exists()
        if asset.kind == "narration":
            assert asset.transcript
    store = PublicationStore(Path(loader.__file__).parent / "published")
    assert all(s.id != "starline" for s in store.catalog())
