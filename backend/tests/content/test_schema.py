"""内容声明的真实校验测试；不启动API、不执行规则、不读媒体文件。"""

from copy import deepcopy
import json
from pathlib import Path

from pydantic import ValidationError
import pytest


@pytest.fixture
def document():
    path = Path(__file__).parent / "fixtures/minimal.json"
    return json.loads(path.read_text(encoding="utf-8"))


def parse(document):
    # 放在调用处导入：实现前测试可收集，并明确因缺Schema而失败。
    from twoworlds.content.schema import ScriptVersion

    return ScriptVersion.model_validate(document)


def test_valid_document_and_json_roundtrip(document):
    original = deepcopy(document)
    script = parse(document)
    assert document == original
    assert script.metadata.id == "schema_example"
    assert script.initial_state.scene_id == "opening"
    assert type(script).model_validate_json(script.model_dump_json()) == script


def test_public_metadata_excludes_private_content_and_rules(document):
    metadata = parse(document).metadata.model_dump_json()
    for secret in (
        "PRIVATE_A_ONLY_",
        "PRIVATE_B_ONLY_",
        "effects",
        "presentation",
        "media",
    ):
        assert secret not in metadata


def test_missing_required_section_has_a_field_location(document):
    del document["metadata"]
    with pytest.raises(ValidationError) as error:
        parse(document)
    assert ("metadata",) in [entry["loc"] for entry in error.value.errors()]


@pytest.mark.parametrize(
    "path,value,message",
    [
        (("metadata", "roles", 0, "id"), "admin", "literal_error"),
        (("metadata", "content_version"), "../latest", "string_pattern_mismatch"),
        (("metadata", "estimated_minutes"), True, "int_type"),
        (("metadata", "summary"), " ", "string_too_short"),
        (("initial_state", "completed"), True, "initial_state"),
        (("initial_state", "discovered_clues"), ["a_log"], "initial_state"),
        (("initial_state", "shared_clues"), ["a_log"], "initial_state"),
        (
            ("initial_state", "votes"),
            [{"role": "a", "ending_id": "now"}],
            "initial_state",
        ),
        (("devices", 0, "fields", 0, "initial_value"), True, "initial_value"),
        (("devices", 0, "fields", 0, "choices"), [0, 0], "duplicate"),
        (("actions", 1, "parameters", 0, "choices"), [0, "90"], "choices"),
        (("actions", 0, "effects", 0, "op"), "eval_python", "union_tag_invalid"),
        (
            ("actions", 2, "preconditions", 0, "kind"),
            "python_expression",
            "union_tag_invalid",
        ),
        (("actions", 0, "roles"), ["a", "a"], "duplicate"),
        (("media", 2, "transcript"), None, "transcript"),
        (("media", 0, "license"), "", "string_too_short"),
        (("media", 0, "content_version"), "2.0.0", "content_version"),
    ],
)
def test_rejects_invalid_fields(document, path, value, message):
    parent = document
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ValidationError, match=message):
        parse(document)


@pytest.mark.parametrize(
    "section", ["scenes", "facts", "clues", "devices", "actions", "endings", "media"]
)
def test_duplicate_ids_are_rejected_in_each_namespace(document, section):
    document[section].append(deepcopy(document[section][0]))
    with pytest.raises(ValidationError, match=rf"{section}.*duplicate"):
        parse(document)


@pytest.mark.parametrize(
    "path,value,message",
    [
        (("initial_state", "scene_id"), "missing", "initial_state.scene_id"),
        (("scenes", 0, "next_scene_ids"), ["missing"], "scenes.opening.next_scene_ids"),
        (("actions", 0, "scene_ids"), ["missing"], "actions.read_log.scene_ids"),
        (
            ("actions", 0, "effects", 0, "clue_id"),
            "missing",
            "actions.read_log.effects",
        ),
        (("actions", 1, "effects", 0, "device_id"), "missing", "actions.tune.effects"),
        (("actions", 1, "effects", 0, "field"), "missing", "actions.tune.effects"),
        (("actions", 1, "effects", 0, "parameter"), "missing", "actions.tune.effects"),
        (("actions", 2, "preconditions", 0, "clue_id"), "missing", "preconditions"),
        (("actions", 2, "preconditions", 2, "fact_id"), "missing", "preconditions"),
        (("actions", 2, "effects", 0, "fact_id"), "missing", "effects"),
        (("actions", 2, "effects", 1, "scene_id"), "missing", "effects"),
        (("actions", 3, "parameters", 0, "choices"), ["missing"], "record_vote"),
        (("endings", 0, "scene_id"), "missing", "endings.now.scene_id"),
        (("npc", "hints", 0, "scene_id"), "missing", "npc.hints"),
        (("media", 0, "scene_ids"), ["missing"], "media.opening_bg.scene_ids"),
        (("presentation", 0, "background_asset_id"), "missing", "presentation"),
        (("presentation", 1, "cues", 0, "asset_ids"), ["missing"], "presentation"),
    ],
)
def test_rejects_dangling_references(document, path, value, message):
    parent = document
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ValidationError, match=message):
        parse(document)


@pytest.mark.parametrize(
    "path",
    [
        "../secret.png",
        "/absolute.png",
        "C:/secret.png",
        "a\\secret.png",
        "a/%2e%2e/secret.png",
        "https://example.com/image.png",
        "a//image.png",
    ],
)
def test_media_paths_are_relative_and_canonical(document, path):
    document["media"][0]["path"] = path
    with pytest.raises(ValidationError, match="path"):
        parse(document)


def test_role_cannot_reference_partner_media(document):
    document["presentation"][0]["cues"] = [
        {
            "id": "leaked",
            "asset_ids": ["b_voice"],
            "conditions": [],
            "alt_text": "错误引用",
        }
    ]
    with pytest.raises(ValidationError, match="audience"):
        parse(document)


def test_media_must_be_available_in_the_presented_scene(document):
    document["presentation"][0]["background_asset_id"] = "ending_bg"
    with pytest.raises(ValidationError, match="scene"):
        parse(document)


def test_scene_graph_cannot_leave_the_ending_unreachable(document):
    document["scenes"][0]["next_scene_ids"] = []
    with pytest.raises(ValidationError, match="unreachable"):
        parse(document)


def test_each_scene_needs_both_role_presentations(document):
    document["presentation"].pop()
    with pytest.raises(ValidationError, match="presentation"):
        parse(document)


def test_action_cannot_operate_another_roles_device(document):
    document["actions"][1]["roles"] = ["b"]
    with pytest.raises(ValidationError, match="role"):
        parse(document)


def test_device_parameter_cannot_offer_values_outside_the_device(document):
    document["actions"][1]["parameters"][0]["choices"] = [0, 90, 180]
    with pytest.raises(ValidationError, match="choices"):
        parse(document)


@pytest.mark.parametrize("section", [None, "metadata", "initial_state"])
def test_extra_fields_cannot_smuggle_executable_code(document, section):
    target = document if section is None else document[section]
    target["python_code"] = "raise RuntimeError('must never execute')"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        parse(document)


def test_hint_level_rejects_boolean_even_though_python_treats_true_as_one(document):
    document["npc"]["hints"][0]["level"] = True
    with pytest.raises(ValidationError, match="int_type"):
        parse(document)


def test_validated_definition_is_not_mutable(document):
    script = parse(document)
    with pytest.raises(ValidationError, match="frozen_instance"):
        script.metadata.title = "不能覆盖已有定义"
    assert isinstance(script.scenes, tuple)


@pytest.mark.parametrize(
    "path,value,message",
    [
        (("metadata", "roles", 1, "id"), "a", "metadata.roles"),
        (("scenes", 0, "observations", 1, "role"), "a", "observations"),
        (("scenes", 1, "next_scene_ids"), ["opening"], "terminal"),
        (("initial_state", "scene_id"), "completed", "terminal"),
        (("endings", 0, "scene_id"), "opening", "terminal"),
        (("actions", 2, "preconditions", 1, "field"), "missing", "preconditions"),
        (("actions", 2, "preconditions", 1, "equals"), 180, "choices"),
        (("actions", 2, "effects", 0, "value"), 1, "type mismatch"),
        (("actions", 2, "preconditions", 2, "equals"), 0, "type mismatch"),
        (("actions", 0, "roles"), ["b"], "owner role"),
        (
            ("media", 0, "conditions"),
            [{"kind": "fact", "fact_id": "missing", "equals": True}],
            "conditions",
        ),
        (("media", 0, "path"), "fixtures/wrong.mp3", "extension"),
    ],
)
def test_cross_reference_types_and_terminal_scene_boundaries(
    document, path, value, message
):
    parent = document
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ValidationError, match=message):
        parse(document)
