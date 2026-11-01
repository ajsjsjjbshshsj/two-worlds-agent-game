"""实际构建/检查/安装验证工具；产物只写入指定work目录，不进入发布包。

从项目根运行：python backend/tests/packaging/verify_distribution.py
  --build-python <独立构建环境python> --cache-dir <已有uv缓存> --output work/<新目录>
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile
from zipfile import ZipFile


def run(arguments, cwd, env=None, success=True):
    result = subprocess.run(
        arguments,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if (result.returncode == 0) != success:
        raise AssertionError(result.stdout + result.stderr)
    return result


def inventory(folder):
    wheel = next(folder.glob("*.whl"))
    sdist = next(folder.glob("*.tar.gz"))
    with ZipFile(wheel) as source:
        wheel_names = sorted(source.namelist())
        wheel_data = {name: source.read(name) for name in wheel_names}
    with tarfile.open(sdist) as source:
        sdist_data = {
            member.name: source.extractfile(member).read()
            for member in source.getmembers()
            if member.isfile()
        }
    sdist_names = sorted(sdist_data)
    for names in [wheel_names, sdist_names]:
        for name in names:
            assert not {
                "tests",
                "work",
                "outputs",
                ".idea",
                "__pycache__",
                ".locks",
            } & set(Path(name).parts), name
            assert not any(part.startswith(".stage-") for part in Path(name).parts), (
                name
            )
            assert "private_canary" not in name and not name.endswith(
                (".iml", ".key", ".pem")
            ), name
    draft_path = "twoworlds/content/scripts/lighthouse/1.0.0.json"
    marker_path = "twoworlds/content/published/registry.json"
    assert draft_path in wheel_data and marker_path in wheel_data
    assert any(name.endswith("/src/" + draft_path) for name in sdist_names)
    assert any(name.endswith("/src/" + marker_path) for name in sdist_names)
    assert not any(name.endswith("/hatch_build.py") for name in wheel_names)
    assert any(name.endswith("/hatch_build.py") for name in sdist_names)
    return {
        "wheel": str(wheel),
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "wheel_files": wheel_names,
        "sdist": str(sdist),
        "sdist_sha256": hashlib.sha256(sdist.read_bytes()).hexdigest(),
        "sdist_files": sdist_names,
    }, wheel_data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-python", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    project = Path.cwd()
    backend = project / "backend"
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    build_python = str(Path(args.build_python).resolve(strict=True))
    cache = str(Path(args.cache_dir).resolve(strict=True))

    def build(source, destination, success=True):
        return run(
            [
                "uv",
                "build",
                "--project",
                str(source),
                "--offline",
                "--no-build-isolation",
                "--python",
                build_python,
                "--no-python-downloads",
                "--no-sources",
                "--out-dir",
                str(destination),
            ],
            project,
            success=success,
        )

    build(backend, output / "formal")
    formal, formal_data = inventory(output / "formal")
    # 正式包的内容数据只有草稿JSON与空发布登记，不混入任何合成测试媒体。
    assert {
        name
        for name in formal_data
        if name.startswith("twoworlds/content/") and not name.endswith(".py")
    } == {
        "twoworlds/content/scripts/lighthouse/1.0.0.json",
        "twoworlds/content/published/registry.json",
    }
    assert (
        formal_data["twoworlds/content/scripts/lighthouse/1.0.0.json"]
        == (
            backend / "src/twoworlds/content/scripts/lighthouse/1.0.0.json"
        ).read_bytes()
    )

    # 新项目副本中才生成测试发布；正式源目录与产物不写入测试内容。
    temporary = output / "synthetic-project"
    temporary.mkdir()
    shutil.copytree(
        backend / "src",
        temporary / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for name in [
        "pyproject.toml",
        "README.md",
        "uv.lock",
        ".python-version",
        "hatch_build.py",
    ]:
        shutil.copyfile(backend / name, temporary / name)
    for name in [
        "tests/private_canary.txt",
        "work/private_canary.txt",
        "outputs/private_canary.txt",
        ".idea/private_canary.iml",
        "src/twoworlds/tests/private_canary.py",
        "src/twoworlds/content/private_canary.txt",
    ]:
        target = temporary / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRIVATE_CANARY_MUST_NOT_SHIP", encoding="utf-8")
    helper = runpy.run_path(str(backend / "tests/content/test_publication.py"))
    scripts, assets, approval = helper["draft"](
        output / "synthetic-input", "packaging_example"
    )
    shutil.copytree(
        scripts / "packaging_example",
        temporary / "src/twoworlds/content/scripts/packaging_example",
    )
    from twoworlds.content.publication import PublicationStore

    release_root = temporary / "src/twoworlds/content/published"
    PublicationStore(release_root).publish(
        scripts, assets, "packaging_example", "1.0.0", approval
    )
    # 即使有人把无关文件塞入资源目录，构建也只能收录明确登记的文件。
    (release_root / "packaging_example/1.0.0/assets/private_canary.png").write_bytes(
        b"PRIVATE_CANARY_MUST_NOT_SHIP"
    )
    build(temporary, output / "synthetic")
    synthetic, synthetic_data = inventory(output / "synthetic")
    base = "twoworlds/content/published/packaging_example/1.0.0/"
    assert base + "release.json" in synthetic_data
    for seal in approval.media:
        assert (
            synthetic_data[base + "assets/" + seal.path]
            == (assets / seal.path).read_bytes()
        )
        assert any(
            name.endswith("/src/" + base + "assets/" + seal.path)
            for name in synthetic["sdist_files"]
        )
    assert not any(
        b"PRIVATE_CANARY_MUST_NOT_SHIP" in raw for raw in synthetic_data.values()
    )

    # 单独从sdist解压后重建wheel；目录成员全部先核对路径，不提取符号链接。
    unpacked = output / "from-sdist"
    unpacked.mkdir()
    with tarfile.open(formal["sdist"]) as source:
        for member in source.getmembers():
            target = (unpacked / member.name).resolve()
            assert (
                target.is_relative_to(unpacked)
                and not member.issym()
                and not member.islnk()
            ), member.name
        source.extractall(unpacked, filter="data")
    source_root = next(unpacked.iterdir())
    run(
        [
            "uv",
            "build",
            "--wheel",
            "--project",
            str(source_root),
            "--offline",
            "--no-build-isolation",
            "--python",
            build_python,
            "--no-python-downloads",
            "--no-sources",
            "--out-dir",
            str(output / "rebuilt"),
        ],
        project,
    )
    with ZipFile(next((output / "rebuilt").glob("*.whl"))) as source:
        rebuilt = {name: source.read(name) for name in source.namelist()}
    assert rebuilt == formal_data

    results = {
        "formal": formal,
        "synthetic_test_only": synthetic,
        "rebuilt_wheel_equal": True,
        "installed": [],
    }
    for label, artifact in [("formal", formal), ("synthetic", synthetic)]:
        environment = output / f"runtime-{label}"
        env = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(environment))
        run(
            [
                "uv",
                "sync",
                "--project",
                str(backend),
                "--no-dev",
                "--no-install-project",
                "--locked",
                "--offline",
                "--cache-dir",
                cache,
                "--python",
                build_python,
                "--no-python-downloads",
                "--link-mode",
                "copy",
            ],
            project,
            env=env,
        )
        python = environment / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--offline",
                "--no-deps",
                artifact["wheel"],
            ],
            project,
        )
        empty = output / f"empty-{label}"
        empty.mkdir()
        code = """
import json,sys
from pathlib import Path
from importlib.util import find_spec
import twoworlds
from twoworlds.content.packaged import packaged_content
from twoworlds.content.loader import ScriptLoadError
assert find_spec('pytest') is None and find_spec('fastapi') is None
assert 'site-packages' in str(twoworlds.__file__)
assert not any('backend/src' in value.replace('\\\\','/') for value in sys.path)
with packaged_content() as content:
    assert content.load_draft('lighthouse','1.0.0').metadata.id=='lighthouse'
    missing=content.audit_draft('lighthouse','1.0.0')
    assert len(missing)==28 and all(not item.file_present and not item.license_reviewed and item.included_in_package is False for item in missing)
    try: content.load_draft('lighthouse','9.0.0')
    except ScriptLoadError as error: assert error.code=='CONTENT_NOT_FOUND'
    else: raise AssertionError('missing version silently replaced')
    if LABEL=='synthetic':
        catalog=content.catalog()
        assert [item.id for item in catalog]==['packaging_example']
        assert 'PRIVATE' not in json.dumps([item.model_dump() for item in catalog])
        assert content.load_published('packaging_example','1.0.0').metadata.id=='packaging_example'
        media=content.audit_published('packaging_example','1.0.0')
        assert len(media)==3 and all(item.file_present and item.license_reviewed and item.included_in_package is True for item in media)
        assert content.read_published_media('packaging_example','1.0.0','b_voice').startswith(b'RIFF')
    else: assert content.catalog()==()
print(json.dumps({'case':LABEL,'package':str(twoworlds.__file__),'source_free':True,'runtime_only':True}))
"""
        result = run(
            [
                str(python),
                "-I",
                "-X",
                "utf8",
                "-c",
                "LABEL=" + repr(label) + "\n" + code,
            ],
            empty,
        )
        results["installed"].append(json.loads(result.stdout))
        run(["uv", "pip", "check", "--python", str(python)], project)

    bad_resource = (
        release_root / "packaging_example/1.0.0/assets" / approval.media[0].path
    )
    bad_resource.write_bytes(bad_resource.read_bytes() + b"tampered")
    failure = build(temporary, output / "rejected", success=False)
    assert "PUBLICATION_INTEGRITY_MISMATCH" in failure.stdout + failure.stderr
    assert not list((output / "rejected").glob("*.whl")) and not list(
        (output / "rejected").glob("*.tar.gz")
    )
    results["tampered_build_rejected"] = True
    report = output / "verification.json"
    report.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(report)
    print(
        "formal + temporary test-only wheel/sdist inspected; rebuild equal; 2 runtime installations passed; tampered build rejected"
    )


if __name__ == "__main__":
    main()
