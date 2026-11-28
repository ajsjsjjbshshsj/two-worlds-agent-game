"""Local demo bundle generation and strict mode isolation."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from twoworlds.content.packaged import packaged_content
from twoworlds.demo_content import (
    MARKER,
    DemoContentError,
    generate_demo_content,
    main,
    verify_demo_content,
)
from twoworlds.playtest import PlaytestConfigurationError, create_playtest_app
from twoworlds.server import ServerConfigurationError, create_server_app

ROOT = Path(__file__).resolve().parents[2]


def test_generate_bundle_uses_real_rules_and_synthetic_approved_media(tmp_path):
    root = tmp_path / "demo"
    manifest = generate_demo_content(root)
    assert manifest["mode"] == MARKER
    assert verify_demo_content(root) == manifest
    assert {item["id"] for item in manifest["stories"]} == {"lighthouse", "starline"}
    assert sum(item["media"] for item in manifest["stories"]) == 53
    registry = json.loads((root / "releases/registry.json").read_text("utf-8"))
    assert registry["format"] == "twoworlds-publications-v1"
    releases = list((root / "releases").glob("*/1.0.0/release.json"))
    assert len(releases) == 2
    for path in releases:
        release = json.loads(path.read_text("utf-8"))
        assert release["reviewed_by"] == "automated test fixture only"
        assert release["media"]
        assert all("test-only" in item["license_evidence"] for item in release["media"])
    for relative, digest in manifest["files"].items():
        import hashlib

        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == digest
    # Formal packaged registry stays empty; no draft or formal file was changed.
    with packaged_content() as content:
        assert content.catalog() == ()


def test_integrity_tamper_is_rejected(tmp_path):
    root = tmp_path / "demo"
    generate_demo_content(root)
    media = next((root / "releases").rglob("*.png"))
    media.write_bytes(media.read_bytes() + b"tampered")
    with pytest.raises(DemoContentError, match="integrity"):
        verify_demo_content(root)


def test_force_only_replaces_a_generated_bundle(tmp_path):
    root = tmp_path / "demo"
    generate_demo_content(root)
    with pytest.raises(DemoContentError):
        generate_demo_content(root)
    generate_demo_content(root, force=True)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("user data", encoding="utf-8")
    with pytest.raises(DemoContentError):
        generate_demo_content(foreign, force=True)
    assert (foreign / "keep.txt").read_text("utf-8") == "user data"


def test_demo_server_loads_explicit_bundle_and_keeps_cookie_auth(tmp_path):
    root = tmp_path / "demo"
    generate_demo_content(root)
    app = create_server_app(
        {
            "TWOWORLDS_MODE": "demo",
            "TWOWORLDS_STORAGE_BACKEND": "sqlite",
            "TWOWORLDS_SQLITE_PATH": str(tmp_path / "demo.sqlite"),
            "TWOWORLDS_ALLOWED_ORIGINS": "http://localhost:8080",
            "TWOWORLDS_EMAIL_MODE": "console",
            "TWOWORLDS_AI_MODE": "demo",
            "TWOWORLDS_DEMO_PUBLICATION_ROOT": str(root / "releases"),
        }
    )
    with TestClient(app) as client:
        response = client.get("/api/scripts")
        assert response.status_code == 200
        assert {item["id"] for item in response.json()} == {"lighthouse", "starline"}
        assert client.get("/api/me").status_code == 401


def test_production_rejects_local_demo_root():
    with pytest.raises(ServerConfigurationError, match="forbidden in production"):
        create_server_app(
            {
                "TWOWORLDS_MODE": "production",
                "TWOWORLDS_DEMO_PUBLICATION_ROOT": "/demo-content/releases",
            }
        )


def test_playtest_rejects_local_demo_root_before_any_connection():
    with pytest.raises(PlaytestConfigurationError, match="forbidden in Playtest"):
        create_playtest_app(
            {
                "TWOWORLDS_MODE": "playtest",
                "TWOWORLDS_DEMO_PUBLICATION_ROOT": "/demo-content/releases",
            }
        )


def test_cli_generates_and_reports_test_only(tmp_path, capsys):
    root = tmp_path / "demo"
    assert main([str(root)]) == 0
    output = capsys.readouterr().out
    assert MARKER in output
    assert "lighthouse 1.0.0" in output and "starline 1.0.0" in output
