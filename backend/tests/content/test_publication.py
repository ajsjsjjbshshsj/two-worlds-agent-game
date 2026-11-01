"""发布真实临时快照；测试资源不进入正式内容，不代表灯塔媒体可用。"""

import binascii
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import struct
import sys
import wave
import zlib
from zipfile import ZipFile, Path as ZipPath

import pytest


def api():
    from twoworlds.content import publication

    return publication


def draft(tmp_path, identifier="alpha", version="1.0.0", secret="PRIVATE_TEST_ALPHA"):
    document = json.loads(
        (Path(__file__).parent / "fixtures/minimal.json").read_text(encoding="utf-8")
    )
    document["metadata"].update(
        id=identifier, content_version=version, title=f"测试剧本{identifier}"
    )
    document["clues"][0]["text"] = secret
    document["media"][2]["transcript"] = secret + "_VOICE"

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", binascii.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x11\x22\x33\xff"))
        + chunk(b"IEND", b"")
    )
    audio = BytesIO()
    with wave.open(audio, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(8000)
        target.writeframes(b"\x00\x00\x01\x00" * 40)
    media_root = tmp_path / "assets"
    for item in document["media"]:
        item["content_version"] = version
        item["path"] = (
            f"{identifier}/{version}/{item['id']}.{'png' if item['kind'] == 'image' else 'wav'}"
        )
        item["source"] = (
            "Temporary self-generated test data; not a formal game resource"
        )
        item["license"] = "Test-only synthetic material; not a production approval"
        path = media_root / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png if item["kind"] == "image" else audio.getvalue())
    script = tmp_path / "scripts" / identifier / f"{version}.json"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    module = api()
    approval = module.ReleaseApproval(
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        reviewed_by="test-only reviewer",
        public_metadata_reviewed=True,
        media=[
            module.MediaApproval(
                asset_id=item["id"],
                path=item["path"],
                sha256=hashlib.sha256(
                    (media_root / item["path"]).read_bytes()
                ).hexdigest(),
                license_evidence="Test-only generated PNG/WAV; no production licensing claim",
            )
            for item in document["media"]
        ],
    )
    return tmp_path / "scripts", media_root, approval


def publish(store, source, identifier="alpha", version="1.0.0"):
    scripts, assets, approval = source
    return store.publish(scripts, assets, identifier, version, approval)


def snapshot(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def directory_link(link, target):
    if sys.platform == "win32":

        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"New-Item -ItemType Junction -Path {quote(link)} -Target {quote(target)} -ErrorAction Stop | Out-Null",
            ],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(target, target_is_directory=True)


def test_published_asset_root_link_is_not_treated_as_trusted_configuration(tmp_path):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    publish(store, draft(tmp_path / "draft"))
    original = tmp_path / "published/alpha/1.0.0/assets"
    outside = tmp_path / "outside-assets"
    # 只移动本例生成的数据，先验证两个绝对路径均在本例临时目录。
    assert original.resolve(strict=True).is_relative_to(tmp_path.resolve(strict=True))
    assert outside.resolve(strict=False).is_relative_to(tmp_path.resolve(strict=True))
    module._commit_bundle(original, outside)
    directory_link(original, outside)
    with pytest.raises(module.PublicationError) as error:
        store.load("alpha", "1.0.0")
    assert error.value.code == "PUBLICATION_PATH_FORBIDDEN"


def test_first_publication_and_exact_version_loading(tmp_path):
    module = api()
    source = draft(tmp_path / "draft")
    store = module.PublicationStore.initialize(tmp_path / "published")
    record = publish(store, source)
    assert record.script_id == "alpha" and record.content_version == "1.0.0"
    script = store.load("alpha", "1.0.0")
    assert script.clues[0].text == "PRIVATE_TEST_ALPHA"
    assert store.catalog() == (script.metadata,)
    assert store.read_media("alpha", "1.0.0", "b_voice").startswith(b"RIFF")


def test_same_version_is_not_overwritten(tmp_path):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    source = draft(tmp_path / "draft")
    publish(store, source)
    before = snapshot(tmp_path / "published")
    with pytest.raises(module.PublicationError) as error:
        publish(store, source)
    assert error.value.code == "PUBLICATION_VERSION_EXISTS"
    assert snapshot(tmp_path / "published") == before


@pytest.mark.parametrize("target", ["json", "media"])
def test_modified_published_bytes_fail_load_catalog_and_further_publication(
    tmp_path, target
):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    publish(store, draft(tmp_path / "draft"))
    release = tmp_path / "published/alpha/1.0.0"
    path = release / (
        "scripts/alpha/1.0.0.json"
        if target == "json"
        else "assets/alpha/1.0.0/b_voice.wav"
    )
    path.write_bytes(path.read_bytes() + b" ")
    for operation in [
        lambda: store.load("alpha", "1.0.0"),
        store.catalog,
        lambda: publish(
            store, draft(tmp_path / "next", version="1.0.1"), version="1.0.1"
        ),
    ]:
        with pytest.raises(module.PublicationError) as error:
            operation()
        assert error.value.code == "PUBLICATION_INTEGRITY_MISMATCH"


def test_new_version_and_draft_edits_never_change_old_snapshot(tmp_path):
    store = api().PublicationStore.initialize(tmp_path / "published")
    first = draft(tmp_path / "draft", secret="PRIVATE_OLD")
    publish(store, first)
    before = snapshot(tmp_path / "published/alpha/1.0.0")
    next_source = draft(tmp_path / "draft", version="1.0.1", secret="PRIVATE_NEW")
    publish(store, next_source, version="1.0.1")
    (first[0] / "alpha/1.0.0.json").write_text("changed draft", encoding="utf-8")
    (first[1] / "alpha/1.0.0/b_voice.wav").write_bytes(b"changed draft resource")
    assert snapshot(tmp_path / "published/alpha/1.0.0") == before
    assert store.load("alpha", "1.0.0").clues[0].text == "PRIVATE_OLD"
    assert store.load("alpha", "1.0.1").clues[0].text == "PRIVATE_NEW"


@pytest.mark.parametrize(
    "identifier,version", [("missing", "1.0.0"), ("alpha", "9.0.0")]
)
def test_missing_published_version_is_explicit_without_fallback(
    tmp_path, identifier, version
):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    publish(store, draft(tmp_path / "draft"))
    with pytest.raises(module.PublicationError) as error:
        store.load(identifier, version)
    assert error.value.code == "PUBLICATION_NOT_FOUND"


def test_catalog_only_exposes_metadata_of_published_versions_in_stable_numeric_order(
    tmp_path,
):
    from twoworlds.content.schema import ScriptMetadata

    store = api().PublicationStore.initialize(tmp_path / "published")
    draft(tmp_path / "unpublished", identifier="hidden", secret="PRIVATE_UNPUBLISHED")
    for identifier, version in [
        ("beta", "1.0.0"),
        ("alpha", "1.10.0"),
        ("alpha", "1.2.0"),
    ]:
        publish(
            store, draft(tmp_path / "draft", identifier, version), identifier, version
        )
    catalog = store.catalog()
    assert [(item.id, item.content_version) for item in catalog] == [
        ("alpha", "1.2.0"),
        ("alpha", "1.10.0"),
        ("beta", "1.0.0"),
    ]
    assert all(type(item) is ScriptMetadata for item in catalog)
    wire = json.dumps(
        [item.model_dump(mode="json") for item in catalog], ensure_ascii=False
    )
    for forbidden in [
        "PRIVATE_",
        "hidden",
        "clues",
        "facts",
        "devices",
        "actions",
        "preconditions",
        "effects",
        "npc",
        "media",
        "path",
        "presentation",
    ]:
        assert forbidden not in wire


def test_new_private_text_cannot_appear_in_a_catalog(tmp_path):
    store = api().PublicationStore.initialize(tmp_path / "published")
    publish(store, draft(tmp_path / "draft", secret="PRIVATE_FIRST"))
    publish(
        store,
        draft(tmp_path / "draft", version="1.0.1", secret="PRIVATE_SECOND"),
        version="1.0.1",
    )
    assert "PRIVATE" not in json.dumps([item.model_dump() for item in store.catalog()])


@pytest.mark.parametrize(
    "problem,code",
    [
        ("missing", "PUBLICATION_MEDIA_MISSING"),
        ("empty", "PUBLICATION_MEDIA_EMPTY"),
        ("no_approval", "PUBLICATION_APPROVAL_REQUIRED"),
        ("unreviewed", "PUBLICATION_APPROVAL_INVALID"),
        ("stale_json", "PUBLICATION_APPROVAL_INVALID"),
        ("stale_media", "PUBLICATION_APPROVAL_INVALID"),
        ("unreviewed_metadata", "PUBLICATION_APPROVAL_INVALID"),
    ],
)
def test_publication_refuses_incomplete_or_unreviewed_resources_without_a_record(
    tmp_path, problem, code
):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    scripts, assets, approval = draft(tmp_path / "draft")
    target = assets / approval.media[0].path
    if problem == "missing":
        target.unlink()
    elif problem == "empty":
        target.write_bytes(b"")
    elif problem == "no_approval":
        approval = None
    elif problem == "unreviewed":
        approval = approval.model_copy(update={"media": approval.media[:-1]})
    elif problem == "unreviewed_metadata":
        approval = approval.model_copy(update={"public_metadata_reviewed": False})
    elif problem == "stale_json":
        path = scripts / "alpha/1.0.0.json"
        path.write_bytes(path.read_bytes() + b" ")
    else:
        target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(module.PublicationError) as error:
        store.publish(scripts, assets, "alpha", "1.0.0", approval)
    assert error.value.code == code
    assert store.catalog() == ()
    assert not list((tmp_path / "published").rglob("release.json"))
    assert not list((tmp_path / "published").glob(".stage-*"))


@pytest.mark.parametrize(
    "path",
    [
        "../escape.png",
        "/absolute.png",
        "C:/escape.png",
        "alpha\\1.0.0\\x.png",
        "https://example.com/a.png",
    ],
)
def test_bad_media_paths_remain_rejected_by_the_existing_loader(tmp_path, path):
    from twoworlds.content.loader import ScriptLoadError

    store = api().PublicationStore.initialize(tmp_path / "published")
    scripts, assets, approval = draft(tmp_path / "draft")
    source = scripts / "alpha/1.0.0.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    document["media"][0]["path"] = path
    source.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ScriptLoadError) as error:
        store.publish(scripts, assets, "alpha", "1.0.0", approval)
    assert error.value.code == "CONTENT_INVALID_SCHEMA"


def test_resource_path_must_use_its_own_script_and_version_namespace(tmp_path):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    scripts, assets, approval = draft(tmp_path / "draft")
    path = scripts / "alpha/1.0.0.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["media"][0]["path"] = "alpha/2.0.0/secret.png"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(module.PublicationError) as error:
        store.publish(scripts, assets, "alpha", "1.0.0", approval)
    assert error.value.code == "PUBLICATION_RESOURCE_VERSION"


def test_linked_resource_directory_cannot_escape_the_asset_root(tmp_path):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    scripts, real_assets, approval = draft(tmp_path / "draft")
    linked_assets = tmp_path / "linked-assets"
    linked_assets.mkdir()
    link = linked_assets / "alpha"
    target = real_assets / "alpha"
    if sys.platform == "win32":

        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"New-Item -ItemType Junction -Path {quote(link)} -Target {quote(target)} -ErrorAction Stop | Out-Null",
            ],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(target, target_is_directory=True)
    with pytest.raises(module.PublicationError) as error:
        store.publish(scripts, linked_assets, "alpha", "1.0.0", approval)
    assert error.value.code == "PUBLICATION_PATH_FORBIDDEN"


def test_commit_failure_leaves_no_partial_record_and_can_retry(tmp_path, monkeypatch):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    source = draft(tmp_path / "draft")
    commit = module.os.rename

    def fail(*args):
        raise OSError("test-only failed rename")

    monkeypatch.setattr(module.os, "rename", fail)
    with pytest.raises(module.PublicationError) as error:
        publish(store, source)
    assert error.value.code == "PUBLICATION_WRITE_FAILED"
    assert store.catalog() == ()
    assert not list((tmp_path / "published").glob(".stage-*"))
    monkeypatch.setattr(module.os, "rename", commit)
    publish(store, source)
    assert len(store.catalog()) == 1


def test_partial_staging_write_failure_is_cleaned_without_a_registration(
    tmp_path, monkeypatch
):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    source = draft(tmp_path / "draft")
    original = module.write_new
    attempts = []

    def interrupted(path, raw):
        attempts.append(path)
        if len(attempts) == 2:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw[:3])
            raise OSError("test-only interrupted media write")
        original(path, raw)

    monkeypatch.setattr(module, "write_new", interrupted)
    with pytest.raises(module.PublicationError) as error:
        publish(store, source)
    assert error.value.code == "PUBLICATION_WRITE_FAILED"
    assert store.catalog() == ()
    assert not list((tmp_path / "published").glob(".stage-*"))
    assert not list((tmp_path / "published").rglob("release.json"))


def test_two_publishers_cannot_overwrite_the_same_version(tmp_path):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    source = draft(tmp_path / "draft")

    def attempt():
        try:
            publish(store, source)
            return "published"
        except module.PublicationError as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert results.count("published") == 1
    assert set(results) <= {
        "published",
        "PUBLICATION_BUSY",
        "PUBLICATION_VERSION_EXISTS",
    }
    assert len(store.catalog()) == 1


@pytest.mark.parametrize(
    "identifier,version",
    [("../alpha", "1.0.0"), ("alpha", "latest"), ("alpha", "../1.0.0")],
)
def test_release_references_cannot_traverse_or_guess_versions(
    tmp_path, identifier, version
):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    with pytest.raises(module.PublicationError) as error:
        store.load(identifier, version)
    assert error.value.code == "PUBLICATION_INVALID_REFERENCE"


def test_packaged_lighthouse_is_an_unpublished_draft_with_28_missing_unreviewed_assets():
    from twoworlds.content.packaged import packaged_content

    with packaged_content() as content:
        assert content.load_draft("lighthouse", "1.0.0").metadata.title == "跨时灯塔"
        assert content.catalog() == ()
        report = content.audit_draft("lighthouse", "1.0.0")
        assert len(report) == 28
        assert all(
            item.declared
            and not item.file_present
            and not item.license_reviewed
            and item.included_in_package is False
            for item in report
        )
        with pytest.raises(api().PublicationError) as error:
            content.load_published("lighthouse", "1.0.0")
        assert error.value.code == "PUBLICATION_NOT_FOUND"


def test_formal_lighthouse_cannot_be_published_without_its_actual_media(tmp_path):
    from twoworlds.content import loader

    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    scripts = Path(loader.__file__).parent / "scripts"
    with pytest.raises(module.PublicationError) as error:
        store.publish(scripts, tmp_path / "no-assets", "lighthouse", "1.0.0", None)
    assert error.value.code == "PUBLICATION_MEDIA_MISSING"
    assert store.catalog() == ()


def test_zip_resource_directory_is_used_only_within_its_context(tmp_path, monkeypatch):
    from twoworlds.content import packaged
    from twoworlds.content import loader

    archive = tmp_path / "resources.zip"
    with ZipFile(archive, "w") as target:
        root = Path(loader.__file__).parent
        target.write(
            root / "scripts/lighthouse/1.0.0.json",
            "content/scripts/lighthouse/1.0.0.json",
        )
        target.write(
            root / "published/registry.json", "content/published/registry.json"
        )
    with ZipFile(archive) as source:
        monkeypatch.setattr(
            packaged.resources, "files", lambda anchor: ZipPath(source, "content/")
        )
        with packaged.packaged_content() as content:
            assert content.load_draft("lighthouse", "1.0.0").metadata.id == "lighthouse"
            assert content.catalog() == ()


@pytest.mark.parametrize(
    "change",
    [
        "invalid_json",
        "missing_media",
        "extra_record_key",
        "wrong_record_id",
        "duplicate_key",
    ],
)
def test_corrupted_registration_or_missing_media_is_rejected(tmp_path, change):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    publish(store, draft(tmp_path / "draft"))
    path = tmp_path / "published/alpha/1.0.0/release.json"
    if change == "invalid_json":
        path.write_text("{", encoding="utf-8")
    elif change == "missing_media":
        (path.parent / "assets/alpha/1.0.0/b_voice.wav").unlink()
    elif change == "duplicate_key":
        path.write_bytes(b'{"format":"twoworlds-release-v1",' + path.read_bytes()[1:])
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        if change == "extra_record_key":
            data["unexpected"] = "PRIVATE_NOT_ALLOWED"
        else:
            data["script_id"] = "wrong"
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(module.PublicationError):
        store.load("alpha", "1.0.0")
    with pytest.raises(module.PublicationError):
        store.catalog()


def test_existing_store_detects_root_registry_changes(tmp_path):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    (tmp_path / "published/registry.json").write_text(
        '{"format":"other"}', encoding="utf-8"
    )
    with pytest.raises(module.PublicationError) as error:
        store.catalog()
    assert error.value.code == "PUBLICATION_INVALID_REGISTRY"


@pytest.mark.parametrize("limit", ["single", "total"])
def test_resource_size_caps_prevent_registration(tmp_path, monkeypatch, limit):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    source = draft(tmp_path / "draft")
    monkeypatch.setattr(
        module, "MAX_MEDIA_BYTES" if limit == "single" else "MAX_RELEASE_BYTES", 1
    )
    with pytest.raises(module.PublicationError) as error:
        publish(store, source)
    assert error.value.code == "PUBLICATION_RESOURCE_TOO_LARGE"
    assert store.catalog() == ()


def test_resource_audit_reports_file_and_review_as_separate_facts(tmp_path):
    from twoworlds.content.loader import ScriptLoader

    module = api()
    scripts, assets, approval = draft(tmp_path / "draft")
    script = ScriptLoader(scripts).load("alpha", "1.0.0")
    unchecked = module.audit_media(script, assets)
    assert all(
        item.declared
        and item.file_present
        and not item.license_reviewed
        and item.included_in_package is None
        for item in unchecked
    )
    checked = module.audit_media(script, assets, approval)
    assert all(item.license_reviewed for item in checked)


def test_git_staging_preserves_the_exact_bytes_of_published_snapshots(tmp_path):
    repository = tmp_path / "git-roundtrip"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(repository)], check=True, capture_output=True
    )
    attributes = Path(__file__).parents[3] / ".gitattributes"
    (repository / ".gitattributes").write_bytes(attributes.read_bytes())
    relative = (
        "backend/src/twoworlds/content/published/alpha/1.0.0/scripts/alpha/1.0.0.json"
    )
    path = repository / relative
    path.parent.mkdir(parents=True)
    raw = b'{\r\n  "test_only": true\r\n}\r\n'
    path.write_bytes(raw)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "core.autocrlf=true",
            "add",
            "--",
            ".gitattributes",
            relative,
        ],
        check=True,
        capture_output=True,
    )
    indexed = subprocess.check_output(
        ["git", "-C", str(repository), "show", ":" + relative]
    )
    assert indexed == raw


@pytest.mark.parametrize("permanent", [False, True])
def test_windows_rename_retry_is_bounded_and_never_creates_a_partial_record(
    tmp_path, monkeypatch, permanent
):
    module = api()
    store = module.PublicationStore.initialize(tmp_path / "published")
    source = draft(tmp_path / "draft")
    original = module.os.rename
    attempts = []

    def rename(staging, destination):
        assert not destination.exists()
        attempts.append(1)
        if permanent or len(attempts) < 3:
            error = PermissionError("test-only transient Windows denial")
            error.winerror = 5
            raise error
        original(staging, destination)

    monkeypatch.setattr(module.os, "rename", rename)
    monkeypatch.setattr(module.time, "sleep", lambda delay: None)
    if permanent:
        with pytest.raises(module.PublicationError) as error:
            publish(store, source)
        assert error.value.code == "PUBLICATION_WRITE_FAILED"
        assert len(attempts) == 5 and store.catalog() == ()
    else:
        publish(store, source)
        assert len(attempts) == 3 and len(store.catalog()) == 1
