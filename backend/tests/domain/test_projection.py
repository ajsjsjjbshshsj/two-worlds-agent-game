"""正式灯塔世界的纯投影边界；不伪造 API、分享命令或私人对话。"""

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from twoworlds.content.loader import ScriptLoader
from twoworlds.content.schema import ScriptVersion
from twoworlds.domain.engine import apply_command, create_initial_state
from twoworlds.domain.errors import DomainError
from twoworlds.domain.models import GameState


def test_starline_power_budget_is_visible_only_after_inspecting_own_board():
    from tests.domain.test_starline import script as starline_script

    content = starline_script()
    initial = create_initial_state(content)
    before_a, before_b = (project(initial, role, content) for role in ("a", "b"))
    # Check the observation channel, not random IDs or unrelated version numbers.
    before_text = " ".join(o.text for o in before_b.personal.observations)
    assert "请先检查" in before_text
    assert "使用" not in before_text and "/5" not in before_text
    assert "engine=" not in before_text and not before_b.personal.clues
    inspected = act(initial, "b", "inspect", content, target="power_board")
    after_a, after_b = (project(inspected, role, content) for role in ("a", "b"))
    after_text = " ".join(o.text for o in after_b.personal.observations)
    assert "使用0/5" in after_text and "engine=False" in after_text
    assert before_a.personal == after_a.personal
    assert before_a.public == after_a.public
    board = next(c for c in content.clues if c.id == "b_power_board")
    assert board.text in after_b.model_dump_json()
    assert board.text not in after_a.model_dump_json()
    assert "/5" not in after_a.model_dump_json()


@lru_cache
def script():
    import twoworlds.content.loader as loader

    return ScriptLoader(Path(loader.__file__).parent / "scripts").load(
        "lighthouse", "1.0.0"
    )


def project(state, role, content=None):
    from twoworlds.domain.projection import project_save

    return project_save(state, script() if content is None else content, role)


def act(state, role, kind, content=None, **args):
    return apply_command(
        state,
        script() if content is None else content,
        role,
        {"kind": kind, "args": args},
    ).state


def at(phase="fresh", content=None, ending="guide_now"):
    content = script() if content is None else content
    state = create_initial_state(content)
    steps = [
        ("a", "inspect", {"target": "maintenance_log"}),
        ("b", "inspect", {"target": "sea_chart"}),
        ("a", "set_emitter", {"angle": 90, "pattern": "pulse"}),
        ("b", "set_filter", {"filter": "amber"}),
        ("b", "lock_signal", {}),
        ("b", "route_power", {"target": "tower"}),
        ("a", "inspect", {"target": "clock_gears"}),
        ("a", "repair_clock", {"mode": "steady"}),
        ("b", "confirm_route", {}),
        ("a", "vote_ending", {"choice": ending}),
        ("b", "vote_ending", {"choice": ending}),
    ]
    limit = {
        "fresh": 0,
        "log": 1,
        "read": 2,
        "aligned": 4,
        "repair": 5,
        "powered": 6,
        "tools": 7,
        "repaired": 8,
        "decision": 9,
        "one_vote": 10,
        "completed": 11,
    }[phase]
    for role, kind, args in steps[:limit]:
        state = act(state, role, kind, content, **args)
    return state


def dumped(state, role, content=None):
    return project(state, role, content).model_dump(mode="json")


def media_ids(snapshot):
    view = snapshot["presentation"]
    return ({view["background"]["asset_id"]} if view["background"] else set()) | {
        asset["asset_id"] for cue in view["cues"] for asset in cue["assets"]
    }


def action_ids(state, role):
    return {item["id"] for item in dumped(state, role)["available_actions"]}


def changed_content(change):
    raw = script().model_dump(mode="json")
    change(raw)
    return ScriptVersion.model_validate(raw)


def test_initial_snapshot_is_a_separate_explicit_contract():
    state = at()
    a, b = dumped(state, "a"), dumped(state, "b")
    assert a != b
    for role, view in (("a", a), ("b", b)):
        assert set(view) == {
            "script_id",
            "script_version",
            "version",
            "role",
            "scene_id",
            "completed",
            "public",
            "personal",
            "available_actions",
            "presentation",
        }
        assert view["role"] == role and view["version"] == 0
        assert view["script_id"] == "lighthouse" and view["script_version"] == "1.0.0"
        assert view["public"] == {
            "clues": [],
            "ending": None,
            "events": [],
            "recap": {"milestones": [], "ending_id": None, "summary": None},
        }
        assert set(view["personal"]) == {"clues", "dialogue", "devices", "observations"}
        assert view["personal"]["dialogue"] == view["personal"]["clues"] == []
    assert a["personal"]["devices"] == {"emitter": {"angle": 0, "pattern": "steady"}}
    assert b["personal"]["devices"] == {
        "filter": {"filter": "clear"},
        "power_router": {"target": "observatory"},
    }


@pytest.mark.parametrize("phase", ["fresh", "log", "read", "tools", "completed"])
def test_whole_json_never_contains_undiscovered_or_partner_private_clue(phase):
    def mark(raw):
        for clue in raw["clues"]:
            clue["text"] = "PRIVATE_MARKER_" + clue["id"]

    content = changed_content(mark)
    state = at(phase, content)
    for role in ("a", "b"):
        snapshot = project(state, role, content)
        serialized = snapshot.model_dump_json()
        visible = snapshot.model_dump(mode="json")["personal"]["clues"]
        assert visible == sorted(visible, key=lambda item: item["id"])
        for clue in content.clues:
            allowed = clue.role == role and clue.id in state.discovered_clues
            assert (clue.text in serialized) is allowed
            assert (clue.id in {item["id"] for item in visible}) is allowed


def test_shared_clue_exposes_only_one_explicit_id_and_text_to_both():
    state = at("tools").model_copy(update={"shared_clues": ("a_maintenance_log",)})
    clue = next(item for item in script().clues if item.id == "a_maintenance_log")
    a, b = dumped(state, "a"), dumped(state, "b")
    assert (
        a["public"]["clues"]
        == b["public"]["clues"]
        == [{"id": clue.id, "text": clue.text}]
    )
    assert {item["id"] for item in b["personal"]["clues"]} == {"b_sea_chart"}
    assert "a_clock_gears" not in json.dumps(b)


@pytest.mark.parametrize(
    "shared",
    [("unknown",), ("a_clock_gears",), ("a_maintenance_log", "a_maintenance_log")],
)
def test_invalid_shared_clues_are_rejected_without_a_snapshot(shared):
    state = at("read").model_copy(update={"shared_clues": shared})
    with pytest.raises(DomainError) as error:
        project(state, "b")
    assert error.value.code == "INVALID_STATE"


def test_nonshareable_personal_clue_stays_private_and_cannot_be_public():
    def make_private(raw):
        raw["clues"][0]["shareable"] = False

    content = changed_content(make_private)
    state = at("read", content)
    assert dumped(state, "a", content)["personal"]["clues"]
    assert not dumped(state, "b", content)["public"]["clues"]
    with pytest.raises(DomainError) as error:
        project(
            state.model_copy(update={"shared_clues": ("a_maintenance_log",)}),
            "b",
            content,
        )
    assert error.value.code == "INVALID_STATE"


def test_private_devices_fields_and_values_do_not_appear_in_other_json():
    def mark(raw):
        for device in raw["devices"]:
            role = device["role"]
            device["fields"].append(
                {
                    "id": "secret_" + role,
                    "value_type": "string",
                    "choices": ["PRIVATE_DEVICE_" + role],
                    "initial_value": "PRIVATE_DEVICE_" + role,
                }
            )

    content = changed_content(mark)
    state = at("read", content)
    for role, other in (("a", "b"), ("b", "a")):
        serialized = project(state, role, content).model_dump_json()
        assert "PRIVATE_DEVICE_" + role in serialized
        assert "PRIVATE_DEVICE_" + other not in serialized
        assert "secret_" + other not in serialized


@pytest.mark.parametrize(
    "phase",
    ["fresh", "aligned", "repair", "powered", "repaired", "decision", "completed"],
)
def test_static_and_current_observations_are_strictly_role_scoped(phase):
    def mark(raw):
        for scene in raw["scenes"]:
            for item in scene["observations"]:
                item["text"] = "PRIVATE_SCENE_" + item["role"] + "_" + scene["id"]

    content = changed_content(mark)
    state = at(phase, content)
    for role, other in (("a", "b"), ("b", "a")):
        view = dumped(state, role, content)
        actual = view["personal"]["observations"]
        assert actual[0] == {
            "topic": "scene",
            "text": "PRIVATE_SCENE_" + role + "_" + state.scene_id,
        }
        assert {(item["topic"], item["text"]) for item in actual[1:]} == {
            (item.topic, item.text)
            for item in state.observations
            if item.audience == role
        }
        assert "PRIVATE_SCENE_" + other not in json.dumps(view)
        for scene in content.scenes:
            if scene.id != state.scene_id:
                assert "PRIVATE_SCENE_" + role + "_" + scene.id not in json.dumps(view)


def test_bidirectional_current_feedback_and_actions_are_derived_from_real_commands():
    state = at("read")
    assert "lock_signal" not in action_ids(state, "b")
    state = act(state, "a", "set_emitter", angle=90, pattern="pulse")
    state = act(state, "b", "set_filter", filter="amber")
    assert "lock_signal" in action_ids(state, "b")
    assert "beam_90" in media_ids(dumped(state, "b"))
    assert "内湾航道" in project(state, "b").model_dump_json()
    assert "内湾航道" not in project(state, "a").model_dump_json()
    state = act(state, "b", "lock_signal")
    assert "inspect_gears" not in action_ids(state, "a")
    state = act(state, "b", "route_power", target="tower")
    assert "inspect_gears" in action_ids(state, "a")
    assert "tower_powered" in media_ids(dumped(state, "a"))
    state = act(state, "a", "inspect", target="clock_gears")
    assert "repair_clock" in action_ids(state, "a")
    state = act(state, "a", "repair_clock", mode="steady")
    assert "confirm_route" in action_ids(state, "b")
    state = act(state, "b", "route_power", target="shore")
    assert "confirm_route" not in action_ids(state, "b")
    assert "route_scan" not in media_ids(dumped(state, "b"))
    state = act(state, "b", "route_power", target="tower")
    assert "confirm_route" in action_ids(state, "b")
    assert "route_scan" in media_ids(dumped(state, "b"))


@pytest.mark.parametrize(
    "phase,role,expected",
    [
        ("fresh", "a", {"inspect_log"}),
        ("fresh", "b", {"inspect_chart"}),
        ("log", "a", {"set_emitter", "share_clue"}),
        ("read", "b", {"set_filter", "share_clue"}),
        ("aligned", "b", {"set_filter", "lock_signal", "share_clue"}),
        ("repair", "a", {"share_clue"}),
        ("repair", "b", {"route_power", "share_clue"}),
        ("powered", "a", {"inspect_gears", "share_clue"}),
        ("tools", "a", {"repair_clock", "share_clue"}),
        ("repaired", "a", {"share_clue"}),
        ("repaired", "b", {"route_power", "confirm_route", "share_clue"}),
        ("decision", "a", {"vote_ending", "share_clue"}),
        ("decision", "b", {"vote_ending", "share_clue"}),
        ("completed", "a", set()),
        ("completed", "b", set()),
    ],
)
def test_available_actions_follow_role_scene_and_real_preconditions(
    phase, role, expected
):
    assert action_ids(at(phase), role) == expected


def test_action_fields_and_parameter_choices_are_explicitly_whitelisted():
    view = dumped(at("read"), "a")
    action = next(
        item for item in view["available_actions"] if item["id"] == "set_emitter"
    )
    assert set(action) == {"id", "kind", "parameters"}
    assert action["kind"] == "set_emitter"
    assert action["parameters"] == [
        {
            "id": "angle",
            "value_type": "integer",
            "choices": [0, 90, 180, 270],
            "max_length": None,
        },
        {
            "id": "pattern",
            "value_type": "string",
            "choices": ["steady", "pulse"],
            "max_length": None,
        },
    ]
    for key in [
        "preconditions",
        "effects",
        "error_codes",
        "discovery_conditions",
        "recovery_digest",
        "receipts",
        "facts",
        "world_state",
        "npc",
    ]:
        assert '"' + key + '"' not in json.dumps(view)
    # UI允许动作不是执行凭证；伪造清单不能令B调用A的机关。
    with pytest.raises(DomainError) as error:
        act(at("read"), "b", "set_emitter", angle=90, pattern="pulse")
    assert error.value.code == "ROLE_FORBIDDEN"


@pytest.mark.parametrize(
    "phase", ["fresh", "read", "aligned", "repair", "powered", "repaired", "completed"]
)
def test_media_references_have_no_partner_ids_future_scenes_or_internal_fields(phase):
    state = at(phase)
    for role in ("a", "b"):
        view = dumped(state, role)
        ids = media_ids(view)
        by_id = {asset.id: asset for asset in script().media}
        assert {asset.audience for key, asset in by_id.items() if key in ids} <= {
            role,
            "public",
        }
        assert all(state.scene_id in by_id[key].scene_ids for key in ids)
        assert view["presentation"]["background"]["asset_id"] == (
            "old_tower" if role == "a" else "future_station"
        )
        serialized = json.dumps(view)
        for asset in script().media:
            assert (
                asset.path not in serialized
                and asset.source not in serialized
                and asset.license not in serialized
            )
        refs = (
            [view["presentation"]["background"]]
            if view["presentation"]["background"]
            else []
        ) + [asset for cue in view["presentation"]["cues"] for asset in cue["assets"]]
        for ref in refs:
            assert set(ref) == {"asset_id", "kind", "alt_text", "transcript"}
        for cue in view["presentation"]["cues"]:
            assert set(cue) == {"id", "alt_text", "assets"}


def test_media_asset_and_cue_conditions_are_checked_independently():
    def gate(raw):
        for asset in raw["media"]:
            if asset["id"] == "opening_voice":
                asset["conditions"] = [
                    {"kind": "clue", "clue_id": "a_maintenance_log", "discovered": True}
                ]
        for view in raw["presentation"]:
            if view["scene_id"] == "calibration" and view["role"] == "a":
                view["cues"][0]["conditions"] = [
                    {"kind": "clue", "clue_id": "a_maintenance_log", "discovered": True}
                ]

    content = changed_content(gate)
    initial = dumped(at(content=content), "a", content)
    assert not initial["presentation"]["cues"]
    assert "opening_voice" not in media_ids(initial)
    ready = dumped(at("log", content), "a", content)
    assert {"opening_voice", "sea_wind", "emitter_click"} <= media_ids(ready)


def test_conditional_background_is_null_and_its_id_and_alt_text_are_absent():
    def gate(raw):
        raw["media"][0]["conditions"] = [
            {"kind": "clue", "clue_id": "a_maintenance_log", "discovered": True}
        ]
        raw["media"][0]["alt_text"] = "PRIVATE_BACKGROUND_NOT_YET"

    content = changed_content(gate)
    view = dumped(at(content=content), "a", content)
    assert view["presentation"]["background"] is None
    assert "old_tower" not in json.dumps(view)
    assert "PRIVATE_BACKGROUND_NOT_YET" not in json.dumps(view)
    assert (
        dumped(at("log", content), "a", content)["presentation"]["background"][
            "asset_id"
        ]
        == "old_tower"
    )


def test_private_media_transcript_and_cue_text_never_enter_partner_snapshot():
    def mark(raw):
        for asset in raw["media"]:
            if asset["id"] == "emitter_click":
                asset["alt_text"] = "PRIVATE_MEDIA_ALT_A"
                asset["transcript"] = "PRIVATE_MEDIA_TRANSCRIPT_A"
        for view in raw["presentation"]:
            if view["scene_id"] == "calibration" and view["role"] == "a":
                view["cues"][-1]["alt_text"] = "PRIVATE_CUE_A"

    content = changed_content(mark)
    state = at("read", content)
    a, b = (
        project(state, "a", content).model_dump_json(),
        project(state, "b", content).model_dump_json(),
    )
    for marker in (
        "PRIVATE_MEDIA_ALT_A",
        "PRIVATE_MEDIA_TRANSCRIPT_A",
        "PRIVATE_CUE_A",
    ):
        assert marker in a and marker not in b


@pytest.mark.parametrize(
    "ending,other", [("guide_now", "wait_tide"), ("wait_tide", "guide_now")]
)
def test_completed_snapshot_exposes_only_chosen_ending_media(ending, other):
    state = at("completed", ending=ending)
    for role in ("a", "b"):
        view = dumped(state, role)
        assert view["completed"] and view["public"]["ending"] == ending
        assert not view["available_actions"]
        assert ending + "_" + role in media_ids(view)
        assert ending + "_voice" in media_ids(view)
        assert not any(key.startswith(other) for key in media_ids(view))
    assert dumped(at("one_vote", ending=ending), "a")["public"]["ending"] is None


def test_projection_and_serialized_copies_cannot_mutate_state_or_each_other():
    state = at("tools")
    before = deepcopy(state.model_dump(mode="json"))
    a, b = project(state, "a"), project(state, "b")
    encoded_a, encoded_b = a.model_dump(mode="json"), b.model_dump(mode="json")
    encoded_a["personal"]["devices"]["emitter"]["angle"] = 270
    encoded_a["personal"]["clues"][0]["text"] = "CHANGED"
    encoded_a["personal"]["observations"].clear()
    encoded_a["presentation"]["cues"].clear()
    assert state.model_dump(mode="json") == before
    assert b.model_dump(mode="json") == encoded_b
    assert dumped(state, "a") == a.model_dump(mode="json")
    with pytest.raises(ValidationError):
        a.personal.clues[0].text = "CHANGED"
    with pytest.raises(ValidationError):
        a.personal.devices[0].fields[0].value = 270
    with pytest.raises(ValidationError):
        a.role = "b"
    assert a is not project(state, "a") and a.personal is not b.personal
    assert a.public is not b.public


@pytest.mark.parametrize("role", [None, "A", "public", "", True, 1, {}, ["a"]])
def test_invalid_role_is_rejected(role):
    with pytest.raises(DomainError) as error:
        project(at(), role)
    assert error.value.code == "ROLE_FORBIDDEN"


@pytest.mark.parametrize(
    "update,code",
    [
        ({"script_id": "starline"}, "SCRIPT_MISMATCH"),
        ({"script_version": "9.0.0"}, "SCRIPT_MISMATCH"),
        ({"scene_id": "missing"}, "INVALID_STATE"),
        ({"version": True}, "INVALID_STATE"),
        ({"version": -1}, "INVALID_STATE"),
        ({"facts": ()}, "INVALID_STATE"),
        ({"devices": ()}, "INVALID_STATE"),
        ({"discovered_clues": ("missing",)}, "INVALID_STATE"),
        (
            {"discovered_clues": ("a_maintenance_log", "a_maintenance_log")},
            "INVALID_STATE",
        ),
        ({"observations": ()}, "INVALID_STATE"),
        ({"completed": True}, "INVALID_STATE"),
        ({"ending_id": "guide_now"}, "INVALID_STATE"),
        ({"votes": ({"role": "a", "ending_id": "guide_now"},)}, "INVALID_STATE"),
    ],
)
def test_invalid_runtime_state_is_rejected_without_mutation(update, code):
    state = at().model_copy(update=update)
    before = deepcopy(state.model_dump(mode="json", warnings=False))
    with pytest.raises(DomainError) as error:
        project(state, "a")
    assert error.value.code == code
    assert state.model_dump(mode="json", warnings=False) == before


@pytest.mark.parametrize("state", [None, {}, GameState.model_construct()])
def test_wrong_type_or_incomplete_state_cannot_bypass_projection(state):
    with pytest.raises(DomainError) as error:
        project(state, "a")
    assert error.value.code == "INVALID_STATE"


@pytest.mark.parametrize("content", [None, {}, ScriptVersion.model_construct()])
def test_wrong_type_or_incomplete_script_cannot_bypass_projection(content):
    from twoworlds.domain.projection import project_save

    with pytest.raises(DomainError) as error:
        project_save(at(), content, "a")
    assert error.value.code == "INVALID_SCRIPT"


def test_copied_script_with_invalid_media_role_reference_is_rejected():
    content = script()
    media = tuple(
        item.model_copy(update={"audience": "b"}) if item.id == "old_tower" else item
        for item in content.media
    )
    malformed = content.model_copy(update={"media": media})
    with pytest.raises(DomainError) as error:
        project(at(), "a", malformed)
    assert error.value.code == "INVALID_SCRIPT"


def test_unknown_nested_data_and_fake_dialogue_are_not_accepted():
    from twoworlds.domain.projection import PlayerSnapshot

    raw = dumped(at(), "a")
    raw["personal"]["dialogue"] = [
        {"question": "fake", "answer": "fake", "mode": "demo"}
    ]
    with pytest.raises(ValidationError):
        PlayerSnapshot.model_validate(raw)
    raw["personal"]["dialogue"] = []
    raw["public"]["debug"] = {"state": at().model_dump(mode="json")}
    with pytest.raises(ValidationError):
        PlayerSnapshot.model_validate(raw)


def test_output_order_is_stable_and_valid_snapshot_round_trips():
    from twoworlds.domain.projection import PlayerSnapshot

    for role in ("a", "b"):
        state = at("read")
        snapshot = project(state, role)
        assert snapshot.model_dump_json() == project(state, role).model_dump_json()
        assert (
            PlayerSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot
        )
        raw = snapshot.model_dump(mode="json")
        assert list(raw["personal"]["devices"]) == sorted(raw["personal"]["devices"])
        assert [item["id"] for item in raw["available_actions"]] == sorted(
            item["id"] for item in raw["available_actions"]
        )


@pytest.mark.parametrize(
    "devices",
    [
        {"emitter": None},
        {"emitter": []},
        {"emitter": {"angle": 1.5}},
        {"emitter": {"angle": {"hidden": True}}},
        {"emitter": {1: "private"}},
        {1: {"angle": 0}, "emitter": {"angle": 0}},
    ],
)
def test_device_display_model_rejects_invalid_nested_json_as_validation_errors(devices):
    from twoworlds.domain.projection import PlayerSnapshot

    raw = dumped(at(), "a")
    raw["personal"]["devices"] = devices
    with pytest.raises(ValidationError):
        PlayerSnapshot.model_validate(raw)


def test_shared_validation_entry_rejects_tampering_for_commands_and_projection():
    from twoworlds.domain.engine import validate_state

    state = at("read")
    before = state.model_dump_json()
    validated = validate_state(state, script())
    assert validated == state and validated is not state
    assert state.model_dump_json() == before
    invalid = state.model_copy(update={"observations": ()})
    for operation in (
        lambda: validate_state(invalid, script()),
        lambda: project(invalid, "a"),
        lambda: act(invalid, "a", "set_emitter", angle=90, pattern="pulse"),
    ):
        with pytest.raises(DomainError) as error:
            operation()
        assert error.value.code == "INVALID_STATE"


def test_shared_clues_are_sorted_without_moving_partner_clues_into_personal():
    state = at("tools").model_copy(
        update={
            "shared_clues": ("b_sea_chart", "a_maintenance_log"),
        }
    )
    for role in ("a", "b"):
        view = dumped(state, role)
        assert [item["id"] for item in view["public"]["clues"]] == [
            "a_maintenance_log",
            "b_sea_chart",
        ]
        assert all(
            item["id"].startswith(role + "_") for item in view["personal"]["clues"]
        )


def test_extra_private_facts_never_enter_any_snapshot():
    def mark(raw):
        raw["facts"].append(
            {
                "id": "internal_note",
                "audience": "a",
                "initial_value": "PRIVATE_FACT_MARKER",
            }
        )

    content = changed_content(mark)
    state = at("read", content)
    for role in ("a", "b"):
        serialized = project(state, role, content).model_dump_json()
        assert (
            "PRIVATE_FACT_MARKER" not in serialized
            and "internal_note" not in serialized
        )


def test_projection_does_not_read_files_or_contact_network(monkeypatch):
    import builtins
    import socket

    state, content = at("repaired"), script()
    from twoworlds.domain.projection import project_save

    def forbidden(*args, **kwargs):
        raise AssertionError("projection attempted I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert project_save(state, content, "a").scene_id == "repair"
    assert project_save(state, content, "b").scene_id == "repair"


def test_projection_can_import_without_web_storage_or_ai_adapters(tmp_path):
    import subprocess
    import sys

    code = """
import importlib.abc,sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked=('fastapi','httpx','pymongo','motor','langgraph','langchain','twoworlds.api','twoworlds.storage','twoworlds.ai')
        if any(fullname==name or fullname.startswith(name+'.') for name in blocked):
            raise AssertionError('projection imported adapter')
sys.meta_path.insert(0,Guard())
from twoworlds.content.schema import ScriptVersion
from twoworlds.domain.engine import create_initial_state
from twoworlds.domain.projection import project_save
script=ScriptVersion.model_validate_json(sys.stdin.read())
state=create_initial_state(script)
for role in ('a','b'):
    view=project_save(state,script,role)
    assert view.role==role and not view.personal.dialogue
print('pure-projection-ok')
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
    assert result.stdout.strip() == "pure-projection-ok"
