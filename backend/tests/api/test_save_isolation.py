"""Real dual-story HTTP, repositories and sealed test-only publication content."""

from pathlib import Path
import binascii
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
from io import BytesIO
from threading import Barrier
from uuid import UUID, uuid4
import wave
import zlib

from fastapi.testclient import TestClient
import pytest

from tests.api import test_saves as lifecycle
from tests.api.test_commands import CommitBarrier
from tests.contracts.support import Platform, command, error, ok, starline_to_decision
from twoworlds.api.app import create_app
from twoworlds.content import loader
from twoworlds.ports.repository import RepositoryError

save_repository_factory = lifecycle.save_repository_factory
sqlite_repository_factory = lifecycle.sqlite_repository_factory


@pytest.fixture
def games(save_repository_factory, published_story):
    store, publish = published_story
    publish()
    publish(identifier="starline")
    clock = datetime(2026, 11, 16, tzinfo=timezone.utc)
    with ExitStack() as opened:

        def factory(repository=None):
            repo = repository if repository is not None else save_repository_factory()
            lifetime = opened.enter_context(ExitStack())
            app = create_app(
                repository=repo,
                publication_store=store,
                identity_clock=lambda: clock,
                rate_limit=100,
            )
            client = lifetime.enter_context(TestClient(app))
            return Platform(client, lifetime.close), repo

        yield factory, store, publish


@pytest.fixture
def dual_world(games):
    factory, _, _ = games
    game, repo = factory()
    a, b, pair = game.pair()
    return game, repo, a, b, pair, game.save(a, pair), game.save(a, pair, "starline")


def test_test_publications_use_distinct_formal_story_definitions(published_story):
    store, publish = published_story
    lighthouse = publish()
    starline = publish(identifier="starline")
    source = loader.ScriptLoader(Path(loader.__file__).parent / "scripts")
    assert lighthouse.actions == source.load("lighthouse", "1.0.0").actions
    assert starline.actions == source.load("starline", "1.0.0").actions
    assert starline.initial_state.scene_id == "survey"
    assert lighthouse.initial_state.scene_id == "calibration"
    assert starline.devices != lighthouse.devices
    assert store.load("starline", "1.0.0") == starline
    assert all(
        "test" in m.source.lower() and "Test-only" in m.license for m in starline.media
    )
    assert len(store.catalog()) == 2


@pytest.mark.parametrize("identifier", ["lighthouse", "starline"])
def test_test_media_are_valid_png_and_wav_not_just_matching_extensions(
    published_story, identifier
):
    store, publish = published_story
    content = publish(identifier=identifier)
    png = store.read_media(
        identifier, "1.0.0", content.presentation[0].background_asset_id
    )
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    offset, pixels = 8, b""
    while offset < len(png):
        size = int.from_bytes(png[offset : offset + 4], "big")
        tag = png[offset + 4 : offset + 8]
        raw = png[offset + 8 : offset + 8 + size]
        crc = int.from_bytes(png[offset + 8 + size : offset + 12 + size], "big")
        assert binascii.crc32(tag + raw) == crc
        if tag == b"IDAT":
            pixels += raw
        offset += size + 12
    assert offset == len(png) and zlib.decompress(pixels)
    sound = next(m for m in content.media if m.kind == "ambience")
    with wave.open(
        BytesIO(store.read_media(identifier, "1.0.0", sound.id)), "rb"
    ) as audio:
        assert audio.getnchannels() == 1 and audio.getsampwidth() == 2
        assert audio.getnframes() > 0
        assert len(audio.readframes(audio.getnframes())) == audio.getnframes() * 2


@pytest.mark.parametrize("ending", ["rescue_detour", "return_station"])
def test_two_stories_complete_independently_then_restore_after_real_close(
    games, ending
):
    factory, store, _ = games
    game, repo = factory()
    a, b, pair = game.pair()
    lighthouse = game.save(a, pair)
    first_payload = command(lighthouse, "inspect", {"target": "maintenance_log"})
    lighthouse = ok(game.post(a, lighthouse, first_payload))["save"]
    lighthouse = game.accept(
        a, lighthouse, "set_emitter", {"angle": 90, "pattern": "pulse"}
    )
    saved_lighthouse = repo.get_save(lighthouse["id"])
    before_views = [game.read(actor, lighthouse) for actor in (a, b)]
    starline = game.save(b, pair, "starline")
    assert starline["id"] != lighthouse["id"] and starline["version"] == 0
    starline = starline_to_decision(game, a, b, starline)
    for actor in (a, b):
        starline = game.accept(actor, starline, "vote_ending", {"choice": ending})
    saved_starline = repo.get_save(starline["id"])
    assert saved_starline.state.completed and saved_starline.state.ending_id == ending
    assert {
        m.kind
        for m in saved_starline.public_history.milestones
        if m.kind
        in {"track_scanned", "rail_installed", "signal_confirmed", "train_dispatched"}
    } == {"track_scanned", "rail_installed", "signal_confirmed", "train_dispatched"}
    assert repo.get_save(lighthouse["id"]) == saved_lighthouse
    assert [game.read(actor, lighthouse) for actor in (a, b)] == before_views
    remaining = [
        (b, "inspect", {"target": "sea_chart"}),
        (b, "set_filter", {"filter": "amber"}),
        (b, "lock_signal", {}),
        (b, "route_power", {"target": "tower"}),
        (a, "inspect", {"target": "clock_gears"}),
        (a, "repair_clock", {"mode": "steady"}),
        (b, "confirm_route", {}),
    ]
    for actor, kind, args in remaining:
        lighthouse = game.accept(actor, lighthouse, kind, args)
    lighthouse_ending = "guide_now" if ending == "rescue_detour" else "wait_tide"
    for actor in (a, b):
        lighthouse = game.accept(
            actor, lighthouse, "vote_ending", {"choice": lighthouse_ending}
        )
    assert lighthouse["completed"] and repo.get_save(starline["id"]) == saved_starline
    expected = {s["id"]: repo.get_save(s["id"]) for s in (lighthouse, starline)}
    assert expected[lighthouse["id"]].public_history != saved_starline.public_history
    game.close()
    with pytest.raises(RepositoryError):
        repo.get_save(lighthouse["id"])
    reopened, new_repo = factory()
    assert new_repo is not repo
    a2, b2 = reopened.recover(a), reopened.recover(b)
    assert (a2.account_id, b2.account_id) == (a.account_id, b.account_id)
    for saved in (lighthouse, starline):
        record = expected[saved["id"]]
        assert new_repo.get_save(saved["id"]) == record
        assert record.script_version == record.state.script_version == "1.0.0"
        for actor, role in ((a2, "a"), (b2, "b")):
            view = reopened.read(actor, saved)
            assert view["role"] == role and view["version"] == record.version
            assert view["public"]["recap"]["ending_id"] == record.state.ending_id
            for clue in store.load(record.script_id, "1.0.0").clues:
                if clue.role != role:
                    assert clue.text not in str(view)
        first = record.receipts[0]
        assert (
            reopened.receipt(a2, saved, str(first.request_id))["accepted_version"] == 1
        )
        assert reopened.receipt(b2, saved, str(first.request_id)) == {"accepted": False}
    # Old accepted requests still confirm after completion and device recovery.
    retried = ok(reopened.post(a2, lighthouse, first_payload))
    assert (
        retried["receipt"]["duplicate"] and retried["receipt"]["accepted_version"] == 1
    )
    assert new_repo.get_save(lighthouse["id"]) == expected[lighthouse["id"]]
    assert {
        s["id"] for s in ok(reopened.http.get("/api/saves", headers=b2.headers))
    } == set(expected)


def test_receipts_are_save_actor_scoped_and_retries_preserve_both_aggregates(
    dual_world,
):
    game, repo, a, b, _, lighthouse, starline = dual_world
    request = str(uuid4())
    payloads = []
    for saved, target in ((lighthouse, "maintenance_log"), (starline, "station_log")):
        assert game.receipt(a, saved, request) == {"accepted": False}
        payload = command(saved, "inspect", {"target": target}, request)
        reply = ok(game.post(a, saved, payload))
        assert reply["receipt"]["accepted_version"] == 1
        payloads.append(payload)
    originals = [repo.get_save(s["id"]) for s in (lighthouse, starline)]
    assert originals[0].receipts[0].fingerprint != originals[1].receipts[0].fingerprint
    for saved, payload in zip((lighthouse, starline), payloads):
        stored = repo.get_receipt(saved["id"], a.account_id, UUID(request))
        assert stored is not None and stored.accepted_version == 1
        assert repo.get_receipt(saved["id"], b.account_id, UUID(request)) is None
        duplicate = ok(game.post(a, saved, payload))
        assert duplicate["receipt"]["duplicate"]
        error(
            game.post(a, saved, payload | {"args": {"target": "changed"}}),
            409,
            "REQUEST_ID_REUSED",
        )
    only_lighthouse = str(uuid4())
    current = game.read(a, lighthouse)
    game.accept(
        a, current, "set_emitter", {"angle": 270, "pattern": "pulse"}, only_lighthouse
    )
    assert game.receipt(a, lighthouse, only_lighthouse)["accepted"]
    assert game.receipt(a, starline, only_lighthouse) == {"accepted": False}
    assert repo.get_save(starline["id"]) == originals[1]
    assert repo.get_save(lighthouse["id"]).receipts[0] == originals[0].receipts[0]


@pytest.mark.parametrize("identifier", ["lighthouse", "starline"])
def test_other_room_members_cannot_read_write_or_list_private_saves(
    dual_world, identifier
):
    game, repo, a, _, _, lighthouse, starline = dual_world
    owned = lighthouse if identifier == "lighthouse" else starline
    c, _, other_pair = game.pair()
    other = game.save(c, other_pair, identifier)
    assert owned["id"] != other["id"]
    before_owned, before_other = (repo.get_save(s["id"]) for s in (owned, other))
    target = "maintenance_log" if identifier == "lighthouse" else "station_log"
    request = str(uuid4())
    game.accept(a, owned, "inspect", {"target": target}, request)
    assert game.receipt(c, other, request) == {"accepted": False}
    assert repo.get_save(other["id"]) == before_other
    for actor, hidden in ((a, other), (c, owned)):
        missing = game.http.get("/api/saves/missing", headers=actor.headers)
        denied = game.http.get(f"/api/saves/{hidden['id']}", headers=actor.headers)
        error(denied, 404, "SAVE_NOT_FOUND")
        assert denied.content == missing.content
        payload = command(hidden, "inspect", {"target": target})
        error(game.post(actor, hidden, payload), 404, "SAVE_NOT_FOUND")
    assert {s["id"] for s in ok(game.http.get("/api/saves", headers=a.headers))} == {
        lighthouse["id"],
        starline["id"],
    }
    assert [s["id"] for s in ok(game.http.get("/api/saves", headers=c.headers))] == [
        other["id"]
    ]
    assert repo.get_save(owned["id"]).version == before_owned.version + 1
    assert repo.get_save(other["id"]) == before_other


@pytest.mark.parametrize(
    "role,kind,args,code",
    [
        ("a", "install_rail", {"segment": "bridge_2"}, "TRACK_NOT_SCANNED"),
        ("b", "dispatch_train", {}, "ACTION_UNAVAILABLE"),
        (
            "a",
            "allocate_power",
            {"engine": False, "sonar": True, "lamp": False},
            "ROLE_FORBIDDEN",
        ),
        ("b", "set_echo_gate", {"position": "east"}, "ROLE_FORBIDDEN"),
    ],
)
def test_invalid_starline_commands_preserve_state_history_and_receipts(
    dual_world, role, kind, args, code
):
    game, repo, a, b, _, lighthouse, starline = dual_world
    before = [repo.get_save(s["id"]) for s in (lighthouse, starline)]
    actor = a if role == "a" else b
    payload = command(starline, kind, args)
    error(game.post(actor, starline, payload), 422, code)
    assert game.receipt(actor, starline, payload["request_id"]) == {"accepted": False}
    assert [repo.get_save(s["id"]) for s in (lighthouse, starline)] == before


@pytest.mark.parametrize("lamp", [False, True])
def test_starline_overbudget_refuses_entire_nonzero_power_group(dual_world, lamp):
    game, repo, _, b, _, lighthouse, starline = dual_world
    starline = game.accept(b, starline, "inspect", {"target": "power_board"})
    starline = game.accept(
        b, starline, "allocate_power", {"engine": False, "sonar": True, "lamp": True}
    )
    before = [repo.get_save(s["id"]) for s in (lighthouse, starline)]
    payload = command(
        starline, "allocate_power", {"engine": True, "sonar": True, "lamp": lamp}
    )
    error(game.post(b, starline, payload), 422, "POWER_BUDGET_EXCEEDED")
    assert game.receipt(b, starline, payload["request_id"]) == {"accepted": False}
    assert [repo.get_save(s["id"]) for s in (lighthouse, starline)] == before


def test_clients_cannot_override_role_account_or_world_on_starline(dual_world):
    game, repo, a, b, _, _, starline = dual_world
    before = repo.get_save(starline["id"])
    payload = command(starline, "inspect", {"target": "power_board"})
    for forged in (
        {"role": "b"},
        {"account_id": b.account_id},
        {"state": {"completed": True}},
    ):
        error(game.post(a, starline, payload | forged), 422, "INVALID_INPUT")
        assert repo.get_save(starline["id"]) == before
        assert game.receipt(a, starline, payload["request_id"]) == {"accepted": False}


def test_starline_http_power_observations_unlock_only_for_board_owner(dual_world):
    game, _, a, b, _, _, starline = dual_world
    before_a, before_b = (game.read(actor, starline) for actor in (a, b))
    assert "/5" not in str(before_b["personal"]["observations"])
    starline = game.accept(b, starline, "inspect", {"target": "power_board"})
    after_a, after_b = (game.read(actor, starline) for actor in (a, b))
    assert "使用0/5" in str(after_b["personal"]["observations"])
    assert before_a["personal"] == after_a["personal"]
    assert after_b["personal"]["clues"][0]["text"] not in str(after_a)


STORIES = {
    "lighthouse": (
        "maintenance_log",
        "set_emitter",
        {"angle": 270, "pattern": "pulse"},
        "a_maintenance_log",
        "sea_wind",
    ),
    "starline": (
        "station_log",
        "set_echo_gate",
        {"position": "west"},
        "a_station_log",
        "station_ambience",
    ),
}


def newer_test_version(document, identifier):
    document["metadata"]["title"] += "（test-only v2）"
    _, kind, _, clue_id, _ = STORIES[identifier]
    for clue in document["clues"]:
        if clue["id"] == clue_id:
            clue["text"] = "TEST_V2_PRIVATE_" + clue["text"]
    # Restrict one wrong exploration option while retaining every solution path.
    field, value = (
        ("angle", 270) if identifier == "lighthouse" else ("position", "west")
    )
    option = next(
        p
        for a in document["actions"]
        if a["kind"] == kind
        for p in a["parameters"]
        if p["id"] == field
    )
    option["choices"].remove(value)


def different_test_wav():
    stream = BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x01\x00\xff\xff" * 40)
    return stream.getvalue()


@pytest.mark.parametrize("identifier", list(STORIES))
def test_pinned_rules_clues_and_media_survive_new_publication_and_restart(
    games, identifier
):
    factory, store, publish = games
    game, repo = factory()
    a, b, pair = game.pair()
    old = game.save(a, pair, identifier)
    target, kind, args, _, ambience = STORIES[identifier]
    old = game.accept(a, old, "inspect", {"target": target})
    before = repo.get_save(old["id"])
    views = [game.read(actor, old) for actor in (a, b)]
    old_bytes = store.read_media(identifier, "1.0.0", ambience)
    newer = publish(
        identifier=identifier,
        version="2.0.0",
        transform=lambda d: newer_test_version(d, identifier),
        media={ambience: different_test_wav()},
    )
    assert newer.metadata.content_version == "2.0.0"
    assert store.read_media(identifier, "2.0.0", ambience) != old_bytes
    game.close()
    game, repo = factory()
    assert [game.read(actor, old) for actor in (a, b)] == views
    assert repo.get_save(old["id"]) == before
    for actor in (a, b):
        response = game.http.get(
            f"/api/saves/{old['id']}/media/{ambience}", headers=actor.headers
        )
        assert response.status_code == 200 and response.content == old_bytes
        assert response.headers["cache-control"] == "no-store"
    conflict = game.http.post(
        "/api/saves",
        headers=a.headers,
        json={
            "pair_id": pair["id"],
            "script_id": identifier,
            "script_version": "2.0.0",
        },
    )
    error(conflict, 409, "SCRIPT_VERSION_CONFLICT")
    omitted = game.http.post(
        "/api/saves",
        headers=a.headers,
        json={"pair_id": pair["id"], "script_id": identifier},
    )
    error(omitted, 422, "INVALID_INPUT")
    assert repo.get_save(old["id"]) == before
    # v1 still accepts its old exploration option; genuine sealed v2 rejects it.
    old = game.accept(a, old, kind, args)
    assert old["script_version"] == "1.0.0"
    _, _, new_pair = game.pair(a=a, b=b)
    new = game.save(a, new_pair, identifier, version="2.0.0")
    new = game.accept(a, new, "inspect", {"target": target})
    assert "TEST_V2_PRIVATE_" in new["personal"]["clues"][0]["text"]
    assert "TEST_V2_PRIVATE_" not in str(game.read(a, old))
    before_new = repo.get_save(new["id"])
    rejected = command(new, kind, args)
    error(game.post(a, new, rejected), 422, "INVALID_ARGUMENTS")
    assert repo.get_save(new["id"]) == before_new
    assert repo.get_save(old["id"]).script_version == "1.0.0"


@pytest.mark.parametrize("identifier", list(STORIES))
def test_missing_bound_version_is_not_replaced_by_available_new_version(
    games, tmp_path, identifier
):
    factory, _, publish = games
    game, repo = factory()
    a, _, pair = game.pair()
    old = game.save(a, pair, identifier)
    target = STORIES[identifier][0]
    old = game.accept(a, old, "inspect", {"target": target})
    before = repo.get_save(old["id"])
    publish(identifier=identifier, version="2.0.0")
    release = tmp_path / "releases" / identifier / "1.0.0"
    unavailable = release.with_name("unavailable-test-version")
    release.rename(unavailable)
    try:
        error(
            game.http.get(f"/api/saves/{old['id']}", headers=a.headers),
            404,
            "SCRIPT_NOT_FOUND",
        )
        assert repo.get_save(old["id"]) == before
        first = before.receipts[0]
        assert game.receipt(a, old, str(first.request_id))["accepted_version"] == 1
    finally:
        unavailable.rename(release)
    assert game.read(a, old)["script_version"] == "1.0.0"


@pytest.mark.parametrize("same_request", [False, True])
def test_two_real_app_connections_keep_starline_cas_and_duplicate_semantics(
    games, dual_world, save_repository_factory, same_request
):
    factory, _, _ = games
    game, repo, a, _, _, lighthouse, starline = dual_world
    starline = game.accept(a, starline, "inspect", {"target": "station_log"})
    untouched = repo.get_save(lighthouse["id"])
    second_repo = save_repository_factory()
    assert second_repo is not repo
    barrier = Barrier(2)
    first_game, _ = factory(CommitBarrier(repo, barrier))
    second_game, _ = factory(CommitBarrier(second_repo, barrier))
    first = command(starline, "set_echo_gate", {"position": "east"})
    second = (
        first
        if same_request
        else command(starline, "set_echo_gate", {"position": "west"})
    )
    with ThreadPoolExecutor(2) as pool:
        futures = [
            pool.submit(client.post, a, starline, body)
            for client, body in ((first_game, first), (second_game, second))
        ]
        responses = [future.result(timeout=25) for future in futures]
    if same_request:
        assert [r.status_code for r in responses] == [200, 200]
        assert sorted(r.json()["receipt"]["duplicate"] for r in responses) == [
            False,
            True,
        ]
    else:
        assert sorted(r.status_code for r in responses) == [200, 409]
        error(
            next(r for r in responses if r.status_code == 409), 409, "VERSION_CONFLICT"
        )
    saved = repo.get_save(starline["id"])
    assert (
        saved.version
        == saved.state.version
        == saved.public_history.through_version
        == 2
    )
    assert len(saved.receipts) == 2
    assert saved.state.device("echo_gate", "position") in {"east", "west"}
    assert repo.get_save(lighthouse["id"]) == untouched
