"""正式灯塔内容的加载与声明契约；不实现或模拟规则引擎。"""

from copy import deepcopy
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from twoworlds.content import loader
from twoworlds.content.loader import ScriptLoadError, ScriptLoader
from twoworlds.content.schema import ScriptVersion


def load_lighthouse():
    # 直接读取安装中源码包的正式目录，不复制minimal小样、不在测试里合成剧本。
    root = Path(loader.__file__).parent / "scripts"
    return ScriptLoader(root).load("lighthouse", "1.0.0")


def by_id(items):
    return {item.id: item for item in items}


def declarations(items):
    return [item.model_dump(mode="json") for item in items]


def fact(identifier, value=True):
    return {"kind": "fact", "fact_id": identifier, "equals": value}


def clue(identifier, discovered=True):
    return {"kind": "clue", "clue_id": identifier, "discovered": discovered}


def device(identifier, field, value):
    return {"kind": "device", "device_id": identifier, "field": field, "equals": value}


def test_formal_version_loads_from_source_content_directory():
    script = load_lighthouse()
    assert (script.metadata.id, script.metadata.content_version) == (
        "lighthouse",
        "1.0.0",
    )
    assert script.metadata.title == "跨时灯塔"
    assert ScriptVersion.model_validate_json(script.model_dump_json()) == script
    root = Path(loader.__file__).parent / "scripts"
    with pytest.raises(ScriptLoadError) as error:
        ScriptLoader(root).load("lighthouse", "9.0.0")
    assert error.value.code == "CONTENT_NOT_FOUND"


def test_four_state_graph_preserves_both_roles_verification_and_terminal():
    script = load_lighthouse()
    scenes = by_id(script.scenes)
    assert tuple(scenes) == ("calibration", "repair", "decision", "completed")
    assert [scene.next_scene_ids for scene in scenes.values()] == [
        ("repair",),
        ("decision",),
        ("completed",),
        (),
    ]
    assert [scene.terminal for scene in scenes.values()] == [False, False, False, True]
    assert declarations(scenes["repair"].entry_conditions) == [fact("signal_locked")]
    assert declarations(scenes["repair"].completion_conditions) == [
        fact("clock_repaired"),
        fact("route_confirmed"),
    ]
    assert declarations(scenes["decision"].entry_conditions) == [
        fact("clock_repaired"),
        fact("route_confirmed"),
    ]
    assert declarations(scenes["completed"].entry_conditions) == [fact("completed")]


def test_fresh_start_matches_the_acceptance_trace():
    script = load_lighthouse()
    assert script.initial_state.model_dump(mode="json") == {
        "scene_id": "calibration",
        "discovered_clues": [],
        "shared_clues": [],
        "votes": [],
        "completed": False,
    }
    fields = {
        (item.id, field.id): field.initial_value
        for item in script.devices
        for field in item.fields
    }
    assert fields == {
        ("emitter", "angle"): 0,
        ("emitter", "pattern"): "steady",
        ("filter", "filter"): "clear",
        ("power_router", "target"): "observatory",
    }
    assert all(
        item.initial_value is False for item in script.facts if item.id != "ending_id"
    )
    assert by_id(script.facts)["ending_id"].initial_value == "none"


@pytest.mark.parametrize(
    "action_id,role,scene",
    [
        ("inspect_log", "a", "calibration"),
        ("inspect_chart", "b", "calibration"),
        ("set_emitter", "a", "calibration"),
        ("set_filter", "b", "calibration"),
        ("lock_signal", "b", "calibration"),
        ("route_power", "b", "repair"),
        ("inspect_gears", "a", "repair"),
        ("repair_clock", "a", "repair"),
        ("confirm_route", "b", "repair"),
    ],
)
def test_exclusive_actions_remain_in_their_role_and_phase(action_id, role, scene):
    script = load_lighthouse()
    action = by_id(script.actions)[action_id]
    assert action.roles == (role,)
    assert action.scene_ids == (scene,)
    assert "completed" not in action.scene_ids


def test_private_discoveries_are_not_required_to_be_shared():
    script = load_lighthouse()
    clues = by_id(script.clues)
    assert {key: item.role for key, item in clues.items()} == {
        "a_maintenance_log": "a",
        "b_sea_chart": "b",
        "a_clock_gears": "a",
    }
    assert all(item.shareable for item in clues.values())
    actions = by_id(script.actions)
    for action_id, clue_id in [
        ("inspect_log", "a_maintenance_log"),
        ("inspect_chart", "b_sea_chart"),
        ("inspect_gears", "a_clock_gears"),
    ]:
        assert {"op": "discover_clue", "clue_id": clue_id} in declarations(
            actions[action_id].effects
        )
    assert declarations(actions["set_emitter"].preconditions) == [
        clue("a_maintenance_log")
    ]
    assert declarations(actions["set_filter"].preconditions) == [clue("b_sea_chart")]
    assert "内湾" not in clues["a_maintenance_log"].text
    assert "稳定模式" not in clues["b_sea_chart"].text


def test_lock_requires_both_discoveries_and_the_complete_optical_configuration():
    script = load_lighthouse()
    action = by_id(script.actions)["lock_signal"]
    assert declarations(action.preconditions) == [
        clue("a_maintenance_log"),
        clue("b_sea_chart"),
        device("emitter", "angle", 90),
        device("emitter", "pattern", "pulse"),
        device("filter", "filter", "amber"),
    ]
    assert declarations(action.effects)[:2] == [
        {"op": "set_fact", "fact_id": "signal_locked", "value": True},
        {"op": "enter_scene", "scene_id": "repair"},
    ]
    assert "SIGNAL_UNSTABLE" in action.error_codes


def test_reversible_controls_do_not_pretend_the_puzzle_is_already_solved():
    script = load_lighthouse()
    actions = by_id(script.actions)
    expected = {
        "set_emitter": {"angle": (0, 90, 180, 270), "pattern": ("steady", "pulse")},
        "set_filter": {"filter": ("clear", "blue", "amber")},
        "route_power": {"target": ("tower", "shore", "observatory")},
    }
    for action_id, choices in expected.items():
        action = actions[action_id]
        assert {
            parameter.id: parameter.choices for parameter in action.parameters
        } == choices
        assert {effect.op for effect in action.effects} <= {"set_device", "observe"}
        assert "NO_STATE_CHANGE" in action.error_codes
    # 未修好和已经修好时均可切供电；不能让一次合法试验抹掉维修里程碑。
    assert declarations(actions["route_power"].preconditions) == [fact("signal_locked")]


def test_reverse_power_unlocks_a_tools_then_repair_unlocks_b_confirmation():
    script = load_lighthouse()
    actions = by_id(script.actions)
    powered = device("power_router", "target", "tower")
    gears = actions["inspect_gears"]
    assert powered in declarations(gears.preconditions)
    assert declarations(by_id(script.clues)["a_clock_gears"].discovery_conditions) == [
        fact("signal_locked"),
        powered,
    ]
    assert {
        "op": "set_fact",
        "fact_id": "repair_tools_ready",
        "value": True,
    } in declarations(gears.effects)
    repair = actions["repair_clock"]
    assert declarations(repair.preconditions) == [
        clue("a_clock_gears"),
        fact("repair_tools_ready"),
        powered,
        fact("clock_repaired", False),
    ]
    assert repair.parameters[0].choices == ("steady",)
    assert "REPAIR_MODE_UNSAFE" in repair.error_codes
    confirm = actions["confirm_route"]
    assert declarations(confirm.preconditions) == [fact("clock_repaired"), powered]
    assert {"op": "enter_scene", "scene_id": "decision"} in declarations(
        confirm.effects
    )
    assert by_id(script.facts)["repair_tools_ready"].audience == "a"


@pytest.mark.parametrize("ending", ["guide_now", "wait_tide"])
def test_each_ending_is_a_joint_choice_without_unconditional_completion(ending):
    script = load_lighthouse()
    vote = by_id(script.actions)["vote_ending"]
    assert vote.roles == ("a", "b") and vote.scene_ids == ("decision",)
    assert vote.parameters[0].id == "choice"
    assert set(vote.parameters[0].choices) == {"guide_now", "wait_tide"}
    assert declarations(vote.effects) == [{"op": "record_vote", "parameter": "choice"}]
    assert declarations(vote.preconditions) == [fact("route_confirmed")]
    assert by_id(script.endings)[ending].scene_id == "completed"
    assert len({item.summary_template for item in script.endings}) == 2
    # 这里只保证声明不在单票时完成；一致票结算/改选/只提交一次须T02行为测试。
    for action in script.actions:
        assert not any(
            effect.op == "set_fact" and effect.fact_id in {"ending_id", "completed"}
            for effect in action.effects
        )


def test_public_text_does_not_embed_private_clues_or_the_answer_table():
    script = load_lighthouse()
    public = json.dumps(
        {
            "metadata": script.metadata.model_dump(mode="json"),
            "npc": script.npc.model_dump(mode="json"),
            "endings": declarations(script.endings),
            "public_events": [
                effect.model_dump(mode="json")
                for action in script.actions
                for effect in action.effects
                if effect.op == "observe" and effect.audience == "public"
            ],
            "media": declarations(
                tuple(asset for asset in script.media if asset.audience == "public")
            ),
        },
        ensure_ascii=False,
    )
    for item in script.clues:
        assert item.text not in public
    for secret in ("90", "amber", "内湾", "琥珀", "稳定模式", "fast", "a_clock_gears"):
        assert secret not in public
    assert set(script.metadata.model_dump()) == {
        "id",
        "content_version",
        "title",
        "summary",
        "roles",
        "difficulty",
        "estimated_minutes",
    }
    for role in ("a", "b"):
        own_text = " ".join(
            view.text
            for scene in script.scenes
            for view in scene.observations
            if view.role == role
        )
        assert all(item.text not in own_text for item in script.clues)


def test_three_hint_levels_exist_per_scene_without_hidden_answers():
    script = load_lighthouse()
    assert {(hint.scene_id, hint.level) for hint in script.npc.hints} == {
        (scene.id, level) for scene in script.scenes for level in (1, 2, 3)
    }
    assert len(script.npc.hints) == 12


@pytest.mark.parametrize(
    "angle,direction", [(0, "暗礁"), (90, "内湾"), (180, "观测山"), (270, "外海港")]
)
def test_angle_feedback_is_b_only_and_requires_chart_pulse_and_amber(angle, direction):
    script = load_lighthouse()
    asset = by_id(script.media)[f"beam_{angle}"]
    expected = [
        clue("b_sea_chart"),
        device("emitter", "angle", angle),
        device("emitter", "pattern", "pulse"),
        device("filter", "filter", "amber"),
    ]
    assert asset.audience == "b" and asset.scene_ids == ("calibration",)
    assert declarations(asset.conditions) == expected
    assert direction in asset.alt_text
    references = [
        (view, cue)
        for view in script.presentation
        for cue in view.cues
        if asset.id in cue.asset_ids
    ]
    assert len(references) == 1
    view, cue = references[0]
    assert view.role == "b" and view.scene_id == "calibration"
    assert declarations(cue.conditions) == expected


def test_blurry_configurations_have_feedback_without_claiming_a_stable_signal():
    script = load_lighthouse()
    view = next(
        view
        for view in script.presentation
        if view.role == "b" and view.scene_id == "calibration"
    )
    blurred = [cue for cue in view.cues if "beam_blurred" in cue.asset_ids]
    assert {cue.id for cue in blurred} == {
        "b_blur_steady",
        "b_blur_clear",
        "b_blur_blue",
    }
    expected = [
        [clue("b_sea_chart"), device("emitter", "pattern", "steady")],
        [
            clue("b_sea_chart"),
            device("emitter", "pattern", "pulse"),
            device("filter", "filter", "clear"),
        ],
        [
            clue("b_sea_chart"),
            device("emitter", "pattern", "pulse"),
            device("filter", "filter", "blue"),
        ],
    ]
    assert [declarations(cue.conditions) for cue in blurred] == expected


def test_media_declarations_cover_both_views_and_causal_feedback_with_subtitles():
    script = load_lighthouse()
    assert {(view.scene_id, view.role) for view in script.presentation} == {
        (scene.id, role) for scene in script.scenes for role in ("a", "b")
    }
    media = by_id(script.media)
    assert {asset.kind for asset in script.media} == {
        "image",
        "ambience",
        "sfx",
        "narration",
    }
    assert len([asset for asset in script.media if asset.kind == "sfx"]) >= 3
    for asset in script.media:
        assert asset.alt_text and asset.content_version == "1.0.0"
        assert "尚未制作" in asset.source and "未取得" in asset.license
        assert asset.path.startswith("lighthouse/1.0.0/")
        if asset.kind == "narration":
            assert asset.transcript
    for asset_id, role, conditions in [
        ("tower_powered", "a", [device("power_router", "target", "tower")]),
        ("clock_running", "a", [fact("clock_repaired")]),
        (
            "route_scan",
            "b",
            [fact("clock_repaired"), device("power_router", "target", "tower")],
        ),
    ]:
        asset = media[asset_id]
        assert asset.audience == role and asset.scene_ids == ("repair",)
        assert declarations(asset.conditions) == conditions
    # 每条cue复制所用资源的必要条件，不能把受条件保护的素材塞进无条件预载。
    for view in script.presentation:
        for cue in view.cues:
            for asset_id in cue.asset_ids:
                assert all(
                    condition in cue.conditions
                    for condition in media[asset_id].conditions
                )
                assert media[asset_id].audience in {"public", view.role}


@pytest.mark.parametrize("ending", ["guide_now", "wait_tide"])
def test_ending_performance_is_gated_by_completed_and_the_selected_ending(ending):
    script = load_lighthouse()
    media = by_id(script.media)
    expected = [fact("completed"), fact("ending_id", ending)]
    for suffix in ("a", "b", "voice"):
        asset = media[f"{ending}_{suffix}"]
        assert asset.scene_ids == ("completed",)
        assert declarations(asset.conditions) == expected
    for role in ("a", "b"):
        view = next(
            view
            for view in script.presentation
            if view.scene_id == "completed" and view.role == role
        )
        cue = next(cue for cue in view.cues if cue.id == f"{role}_{ending}")
        assert declarations(cue.conditions) == expected
        assert {f"{ending}_{role}", f"{ending}_voice"} <= set(cue.asset_ids)


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("partner_background", "audience"),
        ("missing_clue", "unknown reference"),
        ("wrong_version", "content_version"),
        ("broken_graph", "unreachable"),
    ],
)
def test_corrupted_formal_content_is_rejected_by_the_existing_schema(mutation, match):
    document = deepcopy(load_lighthouse().model_dump(mode="json"))
    if mutation == "partner_background":
        document["presentation"][0]["background_asset_id"] = "future_station"
    elif mutation == "missing_clue":
        document["actions"][0]["effects"][0]["clue_id"] = "missing"
    elif mutation == "wrong_version":
        document["media"][0]["content_version"] = "2.0.0"
    else:
        document["scenes"][2]["next_scene_ids"] = []
    with pytest.raises(ValidationError, match=match):
        ScriptVersion.model_validate(document)


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("missing_role_view", "CONTENT_INVALID_SCHEMA"),
        ("wrong_device_owner", "CONTENT_INVALID_SCHEMA"),
        ("missing_asset", "CONTENT_INVALID_SCHEMA"),
        ("wrong_identity", "CONTENT_IDENTITY_MISMATCH"),
    ],
)
def test_loader_rejects_damaged_copies_without_changing_the_formal_file(
    tmp_path, mutation, code
):
    # 仅破坏临时副本，正式内容保持不变；实际走文件读取和错误分类。
    script = load_lighthouse()
    document = script.model_dump(mode="json")
    if mutation == "missing_role_view":
        document["presentation"].pop()
    elif mutation == "wrong_device_owner":
        document["devices"][0]["role"] = "b"
    elif mutation == "missing_asset":
        document["presentation"][0]["background_asset_id"] = "missing"
    else:
        document["metadata"]["id"] = "different_story"
    directory = tmp_path / "lighthouse"
    directory.mkdir()
    (directory / "1.0.0.json").write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ScriptLoadError) as error:
        ScriptLoader(tmp_path).load("lighthouse", "1.0.0")
    assert error.value.code == code
    assert load_lighthouse() == script
