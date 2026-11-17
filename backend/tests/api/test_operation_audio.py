"""PR27: accepted device events, role-authorized media and unchanged persistence."""

import pytest

from tests.api import test_save_isolation as isolation
from tests.api.test_media import denied, get_media
from tests.contracts.support import command, error

games = isolation.games
save_repository_factory = isolation.save_repository_factory
sqlite_repository_factory = isolation.sqlite_repository_factory


@pytest.mark.parametrize(
    "story,role,target,kind,first,second,sound",
    [
        (
            "lighthouse",
            "a",
            "maintenance_log",
            "set_emitter",
            {"angle": 90, "pattern": "pulse"},
            {"angle": 180, "pattern": "pulse"},
            "emitter_click",
        ),
        (
            "lighthouse",
            "b",
            "sea_chart",
            "set_filter",
            {"filter": "amber"},
            {"filter": "blue"},
            "receiver_tone",
        ),
        (
            "starline",
            "a",
            "station_log",
            "set_echo_gate",
            {"position": "east"},
            {"position": "west"},
            "gate_movement",
        ),
        (
            "starline",
            "b",
            "power_board",
            "allocate_power",
            {"engine": False, "sonar": True, "lamp": False},
            {"engine": True, "sonar": False, "lamp": True},
            "power_switch",
        ),
    ],
)
def test_only_successful_device_changes_emit_repeatable_private_audio(
    games, story, role, target, kind, first, second, sound
):
    factory, _, _ = games
    game, repo = factory()
    a, b, pair = game.pair()
    actor, partner = (a, b) if role == "a" else (b, a)
    save = game.save(actor, pair, story)
    inspected = game.post(
        actor, save, command(save, "inspect", {"target": target})
    ).json()
    assert inspected["audio_events"] == []
    save = inspected["save"]
    assert sound in save["presentation"]["operation_sfx"]
    assert "audio_events" not in game.read(actor, save)
    before = repo.get_save(save["id"])
    failed = game.post(partner, save, command(save, kind, first))
    error(failed, 422, "ROLE_FORBIDDEN")
    assert "audio_events" not in failed.json()
    assert repo.get_save(save["id"]) == before
    seen = []
    for args in (first, second):
        payload = command(save, kind, args)
        response = game.post(actor, save, payload)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["audio_events"] == [
            {
                "accepted_version": result["receipt"]["accepted_version"],
                "cue_id": next(
                    c["id"]
                    for c in result["save"]["presentation"]["cues"]
                    if any(m["asset_id"] == sound for m in c["assets"])
                ),
                "asset_id": sound,
            }
        ]
        seen.append(result["audio_events"][0]["accepted_version"])
        persisted = repo.get_save(save["id"])
        assert "audio_events" not in persisted.model_dump()
        repeated = game.post(actor, save, payload).json()
        assert repeated["receipt"]["duplicate"] is True
        assert repeated["audio_events"] == []
        assert repo.get_save(save["id"]) == persisted
        save = result["save"]
        partner_view = game.read(partner, save)
        assert sound not in partner_view["presentation"]["operation_sfx"]
        denied(get_media(game, partner, save, sound))
        assert get_media(game, actor, save, sound).status_code == 200
    assert seen[0] != seen[1]
    error(game.post(actor, save, command(save, kind, second)), 422, "NO_STATE_CHANGE")


def test_power_router_uses_confirmed_change_not_discovery(games):
    factory, _, _ = games
    game, _ = factory()
    a, b, pair = game.pair()
    save = game.save(a, pair)
    for actor, kind, args in (
        (a, "inspect", {"target": "maintenance_log"}),
        (b, "inspect", {"target": "sea_chart"}),
        (a, "set_emitter", {"angle": 90, "pattern": "pulse"}),
        (b, "set_filter", {"filter": "amber"}),
        (b, "lock_signal", {}),
    ):
        save = game.accept(actor, save, kind, args)
    for target in ("tower", "shore"):
        response = game.post(b, save, command(save, "route_power", {"target": target}))
        assert response.status_code == 200, response.text
        result = response.json()
        assert [e["asset_id"] for e in result["audio_events"]] == ["power_panel"]
        save = result["save"]


def test_two_real_cas_contenders_deliver_operation_audio_only_for_winner(
    games, save_repository_factory
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from tests.api.test_commands import CommitBarrier

    factory, _, _ = games
    game, repo = factory()
    a, _, pair = game.pair()
    save = game.accept(a, game.save(a, pair), "inspect", {"target": "maintenance_log"})
    barrier = Barrier(2)
    clients = [
        factory(CommitBarrier(r, barrier))[0] for r in (repo, save_repository_factory())
    ]
    payload = command(save, "set_emitter", {"angle": 90, "pattern": "pulse"})
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(c.post, a, save, payload) for c in clients]
        responses = [f.result(timeout=25) for f in futures]
    assert all(r.status_code == 200 for r in responses)
    results = [r.json() for r in responses]
    assert sorted(r["receipt"]["duplicate"] for r in results) == [False, True]
    assert sorted(len(r["audio_events"]) for r in results) == [0, 1]
    assert repo.get_save(save["id"]).version == save["version"] + 1


def test_lost_response_confirmation_never_reconstructs_or_replays_audio(games):
    from twoworlds.ports.repository import RepositoryError

    factory, _, _ = games
    game, repo = factory()
    a, _, pair = game.pair()
    save = game.accept(a, game.save(a, pair), "inspect", {"target": "maintenance_log"})

    class LostResponse:
        def __getattr__(self, name):
            return getattr(repo, name)

        def compare_and_swap_save(self, save_id, expected_version, candidate):
            assert repo.compare_and_swap_save(save_id, expected_version, candidate)
            raise RepositoryError("test-only lost response")

    lost, _ = factory(LostResponse())
    payload = command(save, "set_emitter", {"angle": 90, "pattern": "pulse"})
    failed = lost.post(a, save, payload)
    assert failed.status_code == 503
    assert "audio_events" not in failed.json()
    confirmed = game.post(a, save, payload).json()
    assert confirmed["receipt"]["duplicate"] is True
    assert confirmed["audio_events"] == []
    assert repo.get_save(save["id"]).version == save["version"] + 1
