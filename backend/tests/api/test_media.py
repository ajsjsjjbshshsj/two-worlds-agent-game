"""Protected bytes through real HTTP, sealed publications and SQLite/Mongo."""

from contextlib import ExitStack
import binascii
from datetime import datetime, timedelta, timezone
import os
import subprocess
import struct
import zlib

from fastapi.testclient import TestClient
import pytest

from tests.api import test_saves as lifecycle
from tests.contracts.support import Platform, error
from twoworlds.api.app import create_app

save_repository_factory = lifecycle.save_repository_factory
sqlite_repository_factory = lifecycle.sqlite_repository_factory


@pytest.fixture
def media_world(save_repository_factory, published_story):
    store, publish = published_story
    script = publish()
    repo = save_repository_factory()
    clock = [datetime(2026, 11, 15, tzinfo=timezone.utc)]
    with ExitStack() as stack:
        app = create_app(
            repository=repo,
            publication_store=store,
            identity_clock=lambda: clock[0],
            rate_limit=100,
        )
        client = stack.enter_context(TestClient(app))
        game = Platform(client, lambda: None)
        a, b, pair = game.pair()
        save = game.save(a, pair)
        yield game, a, b, save, repo, store, publish, script, clock


def get_media(game, actor, save, asset, **headers):
    return game.http.get(
        f"/api/saves/{save['id']}/media/{asset}",
        headers={**(actor.headers if actor else {}), **headers},
    )


def granted(response, raw, mime):
    assert response.status_code == 200, response.text
    assert response.content == raw
    assert response.headers["content-type"] == mime
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "location" not in response.headers
    assert "etag" not in response.headers and "last-modified" not in response.headers


def denied(response, status=404, code="MEDIA_NOT_FOUND"):
    body = error(response, status, code)
    assert set(body) == {"code", "message", "retryable"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"] == "application/json"
    assert not response.content.startswith((b"\x89PNG", b"RIFF"))


@pytest.mark.parametrize(
    "role,asset,mime",
    [
        ("a", "old_tower", "image/png"),
        ("a", "sea_wind", "audio/wav"),
        ("b", "sea_wind", "audio/wav"),
        ("a", "opening_voice", "audio/wav"),
        ("b", "receiver_tone", "audio/wav"),
    ],
)
def test_visible_binary_headers_and_complete_save_unchanged(
    media_world, role, asset, mime, caplog
):
    game, a, b, save, repo, store, _, script, _ = media_world
    actor = a if role == "a" else b
    if asset == "receiver_tone":
        save = game.accept(b, save, "inspect", {"target": "sea_chart"})
    before = repo.get_save(save["id"])
    raw = store.read_media("lighthouse", "1.0.0", asset)
    response = get_media(game, actor, save, asset)
    granted(response, raw, mime)
    assert repo.get_save(save["id"]) == before
    for media in script.media:
        assert media.path.encode() not in response.content
        assert media.source.encode() not in response.content
    assert (
        a.token.encode() not in response.content
        and b.token.encode() not in response.content
    )
    for secret in (a.token, a.recovery_key, b.token, b.recovery_key, repr(raw)):
        assert secret not in caplog.text


@pytest.mark.parametrize(
    "role,asset",
    [
        ("a", "future_station"),
        ("b", "old_tower"),
        ("a", "receiver_tone"),
        ("b", "emitter_click"),
        ("a", "unknown"),
        ("a", "tower_unpowered"),
        ("b", "beam_90"),
        ("b", "receiver_tone"),
    ],
)
def test_hidden_unknown_wrong_scene_and_condition_all_same_404(
    media_world, role, asset
):
    game, a, b, save, repo, _, _, _, _ = media_world
    before = repo.get_save(save["id"])
    response = get_media(game, a if role == "a" else b, save, asset)
    denied(response)
    assert response.json() == get_media(game, a, save, "unknown").json()
    assert repo.get_save(save["id"]) == before


def test_identity_membership_and_range_never_bypass_authorization(media_world):
    game, a, _, save, repo, _, _, _, _ = media_world
    outsider = game.account("Outsider")
    before = repo.get_save(save["id"])
    for headers in ({}, {"Range": "bytes=0-7", "If-None-Match": "*"}):
        denied(
            get_media(game, None, save, "old_tower", **headers), 401, "UNAUTHENTICATED"
        )
        denied(
            get_media(game, outsider, save, "old_tower", **headers),
            404,
            "SAVE_NOT_FOUND",
        )
        denied(
            get_media(game, a, {"id": "missing"}, "old_tower", **headers),
            404,
            "SAVE_NOT_FOUND",
        )
        denied(get_media(game, a, save, "future_station", **headers))
    assert repo.get_save(save["id"]) == before


def test_range_and_conditional_requests_return_full_authorized_bytes(media_world):
    game, a, _, save, _, store, _, _, _ = media_world
    response = get_media(
        game,
        a,
        save,
        "old_tower",
        Range="bytes=0-7",
        **{
            "If-None-Match": "*",
            "If-Modified-Since": "Wed, 01 Jan 2100 00:00:00 GMT",
            "Content-Type": "text/html",
        },
    )
    granted(response, store.read_media("lighthouse", "1.0.0", "old_tower"), "image/png")
    assert "content-range" not in response.headers


def test_current_session_rechecked_after_revoke_and_expiry(media_world):
    game, a, _, save, repo, _, _, _, clock = media_world
    other_session = game.recover(a)
    assert (
        game.http.delete("/api/sessions/current", headers=a.headers).status_code == 204
    )
    before = repo.get_save(save["id"])
    denied(get_media(game, a, save, "old_tower"), 401, "UNAUTHENTICATED")
    clock[0] += timedelta(days=31)
    denied(get_media(game, other_session, save, "old_tower"), 401, "UNAUTHENTICATED")
    denied(
        get_media(game, None, save, "old_tower", Authorization="Bearer invalid"),
        401,
        "UNAUTHENTICATED",
    )
    assert repo.get_save(save["id"]) == before


def test_http_commands_change_asset_and_cue_visibility_then_scene(media_world):
    game, a, b, save, repo, store, _, _, _ = media_world
    denied(get_media(game, b, save, "beam_90"))
    save = game.accept(a, save, "inspect", {"target": "maintenance_log"})
    save = game.accept(b, save, "inspect", {"target": "sea_chart"})
    save = game.accept(a, save, "set_emitter", {"angle": 90, "pattern": "pulse"})
    denied(get_media(game, b, save, "beam_90"))  # asset filter condition false
    save = game.accept(b, save, "set_filter", {"filter": "amber"})
    before = repo.get_save(save["id"])
    granted(
        get_media(game, b, save, "beam_90"),
        store.read_media("lighthouse", "1.0.0", "beam_90"),
        "image/png",
    )
    # beam_blurred's own condition is true, but none of its cues is active.
    denied(get_media(game, b, save, "beam_blurred"))
    assert repo.get_save(save["id"]) == before
    save = game.accept(a, save, "set_emitter", {"angle": 180, "pattern": "pulse"})
    denied(get_media(game, b, save, "beam_90"))
    save = game.accept(a, save, "set_emitter", {"angle": 90, "pattern": "pulse"})
    save = game.accept(b, save, "lock_signal")
    assert save["scene_id"] == "repair"
    denied(get_media(game, b, save, "beam_90"))
    denied(get_media(game, a, save, "opening_voice"))  # public but wrong scene


def test_public_asset_with_cue_only_condition_is_not_automatically_public(media_world):
    game, a, b, _, repo, store, publish, _, _ = media_world

    def restrict(document):
        for view in document["presentation"]:
            for cue in view["cues"]:
                if "sea_wind" in cue["asset_ids"]:
                    cue["conditions"] = [
                        {
                            "kind": "device",
                            "device_id": "emitter",
                            "field": "pattern",
                            "equals": "pulse",
                        }
                    ]

    publish(version="2.0.0", transform=restrict)
    a, b, pair = game.pair(a=a, b=b)
    save = game.save(a, pair, version="2.0.0")
    denied(get_media(game, a, save, "sea_wind"))
    save = game.accept(a, save, "inspect", {"target": "maintenance_log"})
    save = game.accept(a, save, "set_emitter", {"angle": 90, "pattern": "pulse"})
    before = repo.get_save(save["id"])
    for actor in (a, b):
        granted(
            get_media(game, actor, save, "sea_wind"),
            store.read_media("lighthouse", "2.0.0", "sea_wind"),
            "audio/wav",
        )
    assert repo.get_save(save["id"]) == before
    save = game.accept(a, save, "set_emitter", {"angle": 90, "pattern": "steady"})
    denied(get_media(game, a, save, "sea_wind"))


def test_exact_version_not_latest_and_other_version_assets_unavailable(media_world):
    game, a, b, save, repo, store, publish, _, _ = media_world
    old = store.read_media("lighthouse", "1.0.0", "old_tower")

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", binascii.crc32(kind + data))
        )

    different_png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x11\x22\x33\xff"))
        + chunk(b"IEND", b"")
    )

    def rename(document):
        for asset in document["media"]:
            if asset["id"] == "future_station":
                asset["id"] = "future_station_v2"
        for view in document["presentation"]:
            if view["background_asset_id"] == "future_station":
                view["background_asset_id"] = "future_station_v2"

    publish(version="2.0.0", transform=rename, media={"old_tower": different_png})
    assert store.read_media("lighthouse", "2.0.0", "old_tower") != old
    before = repo.get_save(save["id"])
    granted(get_media(game, a, save, "old_tower"), old, "image/png")
    # This asset would be visible to B in v2, but is absent from B's pinned v1.
    denied(get_media(game, b, save, "future_station_v2"))
    assert repo.get_save(save["id"]) == before


@pytest.mark.parametrize("damage", ["modified", "missing", "version_missing"])
def test_corrupt_missing_content_never_falls_back_or_leaks_paths(
    media_world, tmp_path, damage
):
    game, a, _, save, repo, store, publish, script, _ = media_world
    publish(version="2.0.0")
    # Test-only filesystem fault injection; the endpoint still uses PublicationStore.
    root = tmp_path / "releases"
    asset = next(asset for asset in script.media if asset.id == "old_tower")
    path = root / "lighthouse/1.0.0/assets" / asset.path
    if damage == "modified":
        path.write_bytes(b"private corrupted bytes")
    elif damage == "missing":
        path.unlink()
    else:
        (root / "lighthouse/1.0.0").rename(root / "lighthouse/missing-version")
    before = repo.get_save(save["id"])
    response = get_media(game, a, save, "old_tower")
    denied(
        response,
        503 if damage != "version_missing" else 404,
        "CONTENT_UNAVAILABLE" if damage != "version_missing" else "SCRIPT_NOT_FOUND",
    )
    assert str(tmp_path) not in response.text and "corrupted" not in response.text
    assert repo.get_save(save["id"]) == before


@pytest.mark.parametrize(
    "asset",
    [
        "..%5Csecret",
        "%2e%2e%2fsecret",
        "https:%2F%2Fexample.com%2Fx",
        "C:%5Csecret.png",
        "old_tower.png",
        "old_tower%00",
    ],
)
def test_abnormal_ids_paths_urls_never_return_media(media_world, asset):
    game, a, _, save, repo, _, _, _, _ = media_world
    before = repo.get_save(save["id"])
    response = get_media(game, a, save, asset)
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"] == "application/json"
    assert not response.content.startswith((b"\x89PNG", b"RIFF"))
    assert repo.get_save(save["id"]) == before


def test_junction_or_symlink_cannot_escape_publication_root(media_world, tmp_path):
    game, a, _, save, repo, _, _, script, _ = media_world
    asset = next(asset for asset in script.media if asset.id == "old_tower")
    path = tmp_path / "releases/lighthouse/1.0.0/assets" / asset.path
    parent = path.parent
    moved = parent.with_name(parent.name + "-original")
    parent.rename(moved)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / path.name).write_bytes(b"outside private bytes")
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(parent), str(outside)],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    else:
        parent.symlink_to(outside, target_is_directory=True)
    try:
        before = repo.get_save(save["id"])
        response = get_media(game, a, save, "old_tower")
        denied(response, 503, "CONTENT_UNAVAILABLE")
        assert (
            "outside private bytes" not in response.text
            and str(tmp_path) not in response.text
        )
        assert repo.get_save(save["id"]) == before
    finally:
        # Remove only the link itself; never recursively delete its target.
        if os.name == "nt":
            parent.rmdir()
        else:
            parent.unlink()


def test_non_media_bytes_in_approved_image_are_refused(media_world):
    game, a, b, _, repo, _, publish, _, _ = media_world
    publish(version="2.0.0", media={"old_tower": b"<html>not a PNG</html>"})
    _, _, pair = game.pair(a=a, b=b)
    save = game.save(a, pair, version="2.0.0")
    before = repo.get_save(save["id"])
    response = get_media(game, a, save, "old_tower")
    denied(response, 503, "CONTENT_UNAVAILABLE")
    assert "<html>" not in response.text and repo.get_save(save["id"]) == before
