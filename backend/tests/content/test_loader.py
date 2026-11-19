"""真实临时目录验证版本加载边界；不接数据库或网络。"""

import importlib
import json
import os
from pathlib import Path
import subprocess

import pytest


def loader_api():
    # 实现前可收集，调用时明确因缺少loader模块而失败。
    return importlib.import_module("twoworlds.content.loader")


@pytest.fixture
def document():
    source = Path(__file__).parent / "fixtures/minimal.json"
    return json.loads(source.read_text(encoding="utf-8"))


def write_version(root, document):
    metadata = document["metadata"]
    target = root / metadata["id"] / f"{metadata['content_version']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return target


@pytest.fixture
def library(tmp_path, document):
    root = tmp_path / "scripts"
    write_version(root, document)
    return root


def expect_error(code, root, script_id="schema_example", version="1.0.0"):
    api = loader_api()
    with pytest.raises(api.ScriptLoadError) as error:
        api.ScriptLoader(root).load(script_id, version)
    assert error.value.code == code
    return error.value


def test_loads_exact_version_and_returns_validated_frozen_model(library):
    script = loader_api().ScriptLoader(library).load("schema_example", "1.0.0")
    assert script.metadata.id == "schema_example"
    assert script.metadata.content_version == "1.0.0"
    assert script.initial_state.scene_id == "opening"
    assert isinstance(script.scenes, tuple)


def test_two_versions_do_not_replace_each_other(library, document):
    document["metadata"]["content_version"] = "2.0.0"
    document["metadata"]["title"] = "第二版测试内容"
    for asset in document["media"]:
        asset["content_version"] = "2.0.0"
    write_version(library, document)
    loader = loader_api().ScriptLoader(library)
    second = loader.load("schema_example", "2.0.0")
    first = loader.load("schema_example", "1.0.0")
    assert first.metadata.content_version == "1.0.0"
    assert second.metadata.content_version == "2.0.0"
    assert first.metadata.title != second.metadata.title


def test_missing_version_does_not_fall_back_to_an_existing_version(library):
    expect_error("CONTENT_NOT_FOUND", library, version="9.0.0")


def test_missing_script_is_not_found(library):
    expect_error("CONTENT_NOT_FOUND", library, script_id="missing")


@pytest.mark.parametrize(
    "script_id,version",
    [
        ("../outside", "1.0.0"),
        ("/absolute", "1.0.0"),
        ("C:\\outside", "1.0.0"),
        ("a/b", "1.0.0"),
        ("%2e%2e", "1.0.0"),
        ("Schema_example", "1.0.0"),
        ("schema_example", "../1.0.0"),
        ("schema_example", "latest"),
        ("schema_example", "01.0.0"),
        ("schema_example", "1.0"),
        ("schema_example", True),
        (123, "1.0.0"),
    ],
)
def test_invalid_reference_is_rejected_before_file_lookup(library, script_id, version):
    expect_error("CONTENT_INVALID_REFERENCE", library, script_id, version)


@pytest.mark.parametrize("as_file", [False, True], ids=["missing", "file"])
def test_root_must_be_an_existing_directory(tmp_path, as_file):
    root = tmp_path / "not_a_directory"
    if as_file:
        root.write_text("not a directory", encoding="utf-8")
    api = loader_api()
    with pytest.raises(api.ScriptLoadError) as error:
        api.ScriptLoader(root)
    assert error.value.code == "CONTENT_INVALID_ROOT"


@pytest.mark.parametrize(
    "field,value", [("id", "different"), ("content_version", "2.0.0")]
)
def test_metadata_must_match_requested_identity(library, document, field, value):
    target = library / "schema_example/1.0.0.json"
    document["metadata"][field] = value
    if field == "content_version":
        for asset in document["media"]:
            asset["content_version"] = value
    target.write_text(json.dumps(document), encoding="utf-8")
    expect_error("CONTENT_IDENTITY_MISMATCH", library)


def test_schema_and_reference_errors_fail_loading(library, document):
    document["actions"][0]["effects"][0]["clue_id"] = "missing"
    write_version(library, document)
    expect_error("CONTENT_INVALID_SCHEMA", library)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"metadata":',
        b"\xff",
        b"\xef\xbb\xbf{}",
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
    ],
    ids=["syntax", "encoding", "bom", "nan", "infinity", "negative-infinity"],
)
def test_invalid_json_never_reaches_schema(library, payload):
    (library / "schema_example/1.0.0.json").write_bytes(payload)
    expect_error("CONTENT_INVALID_JSON", library)


@pytest.mark.parametrize("nested", [False, True], ids=["top-level", "nested"])
def test_duplicate_json_keys_are_rejected_instead_of_last_value_winning(
    library, document, nested
):
    text = json.dumps(document)
    if nested:
        text = text.replace(
            '"initial_value": false', '"initial_value": true, "initial_value": false', 1
        )
    else:
        text = text.replace('"metadata":', '"metadata": null, "metadata":', 1)
    (library / "schema_example/1.0.0.json").write_text(text, encoding="utf-8")
    expect_error("CONTENT_INVALID_JSON", library)


def test_oversized_file_is_rejected(library):
    api = loader_api()
    (library / "schema_example/1.0.0.json").write_bytes(
        b" " * (api.MAX_SCRIPT_BYTES + 1)
    )
    expect_error("CONTENT_TOO_LARGE", library)


def test_json_parser_recursion_failure_is_reported_without_a_raw_traceback(library):
    (library / "schema_example/1.0.0.json").write_bytes(
        b"[" * 3000 + b"0" + b"]" * 3000
    )
    expect_error("CONTENT_INVALID_JSON", library)


@pytest.mark.parametrize("depth", [65, 200, 800, 1400, 3000, 10000])
def test_deep_nesting_is_json_error_regardless_of_platform_recursion_limit(
    library, depth
):
    # 解析器递归上限随平台/解释器不同：深层嵌套必须统一落在解析阶段拒绝，
    # 不能因为某平台恰好解析成功就漂移到Schema分类（PR #34云端失败根因）。
    (library / "schema_example/1.0.0.json").write_bytes(
        ("[" * depth + "0" + "]" * depth).encode("utf-8")
    )
    expect_error("CONTENT_INVALID_JSON", library)


def test_deep_object_nesting_is_json_error(library):
    depth = 3000
    (library / "schema_example/1.0.0.json").write_text(
        '{"a":' * depth + "0" + "}" * depth, encoding="utf-8"
    )
    expect_error("CONTENT_INVALID_JSON", library)


def test_nesting_at_parse_limit_still_reaches_schema_stage(library):
    # 深度恰在解析边界内：顶层数组语法有效，不满足内容模型属于Schema阶段失败，
    # 证明分类按实际失败阶段而不是按深度一刀切。
    api = loader_api()
    (library / "schema_example/1.0.0.json").write_bytes(
        ("[" * api.MAX_JSON_DEPTH + "0" + "]" * api.MAX_JSON_DEPTH).encode("utf-8")
    )
    expect_error("CONTENT_INVALID_SCHEMA", library)


def test_nesting_just_over_parse_limit_is_json_error(library):
    api = loader_api()
    depth = api.MAX_JSON_DEPTH + 1
    (library / "schema_example/1.0.0.json").write_bytes(
        ("[" * depth + "0" + "]" * depth).encode("utf-8")
    )
    expect_error("CONTENT_INVALID_JSON", library)


def test_schema_stage_recursion_error_is_contained(library, monkeypatch):
    api = loader_api()

    def explode(*args, **kwargs):
        raise RecursionError("PRIVATE_RECURSION_DETAIL")

    monkeypatch.setattr(api.ScriptVersion, "model_validate", explode)
    error = expect_error("CONTENT_INVALID_SCHEMA", library)
    assert "PRIVATE_RECURSION_DETAIL" not in str(error)
    assert error.__suppress_context__ is True


def test_brackets_inside_strings_do_not_count_as_nesting(library, document):
    document["metadata"]["title"] = "[" * 900 + "{" * 900
    write_version(library, document)
    script = loader_api().ScriptLoader(library).load("schema_example", "1.0.0")
    assert script.metadata.title == "[" * 900 + "{" * 900


def test_directory_is_not_a_script_file(tmp_path):
    root = tmp_path / "scripts"
    (root / "schema_example/1.0.0.json").mkdir(parents=True)
    expect_error("CONTENT_READ_FAILED", root)


def test_unreadable_file_has_a_read_error_without_exposing_os_details(
    library, monkeypatch
):
    api = loader_api()
    loader = api.ScriptLoader(library)
    target = library / "schema_example/1.0.0.json"
    original_open = Path.open

    def denied(path, *args, **kwargs):
        if path == target:
            raise PermissionError("PRIVATE_OS_DETAIL")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(api.ScriptLoadError) as error:
        loader.load("schema_example", "1.0.0")
    assert error.value.code == "CONTENT_READ_FAILED"
    assert "PRIVATE_OS_DETAIL" not in str(error.value)
    assert error.value.__suppress_context__ is True


def test_error_does_not_echo_private_content_or_absolute_path(library):
    target = library / "schema_example/1.0.0.json"
    target.write_text('{"secret":"PRIVATE_STORY_TEXT"}', encoding="utf-8")
    error = expect_error("CONTENT_INVALID_SCHEMA", library)
    assert "PRIVATE_STORY_TEXT" not in str(error)
    assert str(target) not in str(error)
    assert error.__suppress_context__ is True


def test_relative_root_is_resolved_once(library, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    loader = loader_api().ScriptLoader("scripts")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert loader.load("schema_example", "1.0.0").metadata.id == "schema_example"


def test_directory_link_cannot_escape_content_root(library, tmp_path, document):
    outside = tmp_path / "outside"
    document["metadata"]["id"] = "escaped"
    target = write_version(outside, document).parent
    link = library / "escaped"
    if os.name == "nt":
        # Windows目录联接不要求开发者开启符号链接权限；使用真实文件系统链接。
        def ps_quote(path):
            return "'" + str(path).replace("'", "''") + "'"

        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"New-Item -ItemType Junction -Path {ps_quote(link)} -Target {ps_quote(target)} -ErrorAction Stop | Out-Null",
            ],
            capture_output=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(target, target_is_directory=True)
    expect_error("CONTENT_PATH_FORBIDDEN", library, script_id="escaped")
