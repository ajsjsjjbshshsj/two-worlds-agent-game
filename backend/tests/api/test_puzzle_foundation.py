"""Real Save commands and projections around fixture-only typed puzzle evidence."""

from contextlib import contextmanager
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from tests.contracts.support import (
    Platform,
    command,
    error,
    lighthouse_to_decision,
    ok,
    starline_to_decision,
)
from tests.identity_support import RELAXED_POLICIES, TEST_SECRET, FakeEmailSender
from tests.storage.conftest import (  # noqa: F401
    mongo_database,
    mongo_repository_factory,
    sqlite_repository_factory,
)
from twoworlds.api.app import create_app
from twoworlds.domain.errors import DomainError
from twoworlds.domain.persistence import CommandReceipt, SaveRecord
from twoworlds.domain.puzzles import (
    Challenge,
    EchoState,
    EvidenceKind,
    LighthousePuzzles,
    Reply,
    require_current_evidence,
)
from twoworlds.domain.recap import append_public_history

ORIGIN = "http://testserver"


@pytest.fixture(params=["sqlite", "mongo"])
def repository(request):
    return request.getfixturevalue(f"{request.param}_repository_factory")


@contextmanager
def open_game(repo, store):
    app = create_app(
        repository=repo,
        publication_store=store,
        allowed_origins=[ORIGIN],
        ai_mode="demo",
        email_sender=FakeEmailSender(),
        verification_secret=TEST_SECRET,
        rate_policies=RELAXED_POLICIES,
    )
    with TestClient(app) as client:
        yield Platform(client, lambda: None)


def with_staged_echo(save, script, actor, chapter):
    # Simulate trusted candidates from a future rule without exposing a test command.
    context = save.next_evidence_context()
    return SaveRecord.model_validate(
        save.model_dump()
        | {
            "state": save.state.model_dump()
            | {
                "version": context.accepted_version,
                "puzzles": LighthousePuzzles(l03=chapter),
            },
            "version": context.accepted_version,
            "public_history": append_public_history(
                save.public_history, script, context.accepted_version, ()
            ),
            "receipts": (
                *save.receipts,
                CommandReceipt(
                    actor_id=actor.account_id,
                    request_id=uuid4(),
                    fingerprint="a" * 64,
                    accepted_version=context.accepted_version,
                    created_at=save.updated_at,
                ),
            ),
        }
    )


def test_echo_evidence_is_private_across_http_ws_and_save_restart(
    repository, published_story
):
    store, publish = published_story
    script = publish(
        version="1.1.0", transform=lambda data: data.update(puzzle_rules="p0_v1")
    )
    repo = repository()
    with open_game(repo, store) as game:
        a, b, pair = game.pair()
        save = game.save(a, pair, version="1.1.0")
        save = game.accept(a, save, "inspect", {"target": "maintenance_log"})
        save = game.accept(b, save, "inspect", {"target": "sea_chart"})
        before = repo.get_save(save["id"])
        context = before.next_evidence_context()
        challenge = Challenge(
            id=context.id_for(EvidenceKind.CHALLENGE),
            accepted_version=context.accepted_version,
            optics_rev=0,
            beats=("short", "long"),
        )
        first = with_staged_echo(before, script, b, EchoState(challenge=challenge))
        assert repo.compare_and_swap_save(before.id, before.version, first)
        context = first.next_evidence_context()
        reply = Reply(
            id=context.id_for(EvidenceKind.REPLY),
            accepted_version=context.accepted_version,
            challenge_id=challenge.id,
            optics_rev=0,
            beats=("long", "short"),
        )
        staged = with_staged_echo(
            first, script, a, EchoState(challenge=challenge, reply=reply)
        )
        assert repo.compare_and_swap_save(first.id, first.version, staged)
        forged = command(
            game.read(a, save),
            "set_emitter",
            {
                "angle": 90,
                "pattern": "pulse",
                "evidence_id": str(reply.id),
                "optics_rev": 0,
            },
        )
        error(game.post(a, save, forged), 422, "INVALID_ARGUMENTS")
        assert repo.get_save(save["id"]) == staged
        for actor, own, partner in ((a, reply, challenge), (b, challenge, reply)):
            view = game.read(actor, save)
            assert view["personal"]["puzzle_evidence"] == [
                {"id": str(own.id), "kind": own.kind.value, "beats": list(own.beats)}
            ]
            assert str(partner.id) not in str(view) and str(own.id) not in str(
                view["public"]
            )
            with game.http.websocket_connect(
                f"/api/ws/saves/{save['id']}", headers=actor.headers
            ) as ws:
                assert ws.receive_json() == {"type": "snapshot", "save": view}
        payload = command(
            game.read(a, save), "set_emitter", {"angle": 90, "pattern": "pulse"}
        )
        updated = ok(game.post(a, save, payload))
        final = game.accept(
            a, updated["save"], "set_emitter", {"angle": 0, "pattern": "steady"}
        )
    reopened = repository()
    with open_game(reopened, store) as game:
        current = reopened.get_save(save["id"])
        assert (
            current.version
            == current.state.version
            == current.public_history.through_version
            == final["version"]
        )
        assert current.receipts[-1].accepted_version == current.version
        echo = current.state.puzzles.l03
        assert echo.optics_rev == 2 and echo.challenge is None and echo.reply is None
        assert {item.id for item in echo.history} == {challenge.id, reply.id}
        with pytest.raises(DomainError) as stale:
            require_current_evidence(
                current.next_evidence_context(),
                current.state.puzzles,
                reply.id,
                EvidenceKind.REPLY,
                issuer="a",
            )
        assert stale.value.code == "EVIDENCE_STALE"
        duplicate = ok(game.post(a, save, payload))
        assert duplicate["receipt"] == (updated["receipt"] | {"duplicate": True})
        assert duplicate["save"] == game.read(a, save)
        assert reopened.get_save(save["id"]) == current


@pytest.mark.parametrize(
    "story, ending, to_decision",
    [
        ("lighthouse", "guide_now", lighthouse_to_decision),
        ("lighthouse", "wait_tide", lighthouse_to_decision),
        ("starline", "rescue_detour", starline_to_decision),
        ("starline", "return_station", starline_to_decision),
    ],
)
def test_legacy_save_reopens_without_puzzle_fields_and_keeps_endings(
    repository, published_story, story, ending, to_decision
):
    store, publish = published_story
    publish(identifier=story)
    first_repo = repository()
    with open_game(first_repo, store) as game:
        a, b, pair = game.pair()
        save = to_decision(game, a, b, game.save(a, pair, story))
        save = game.accept(a, save, "vote_ending", {"choice": ending})
        stored = first_repo.get_save(save["id"])
        assert "puzzles" not in stored.model_dump(mode="json")["state"]
    second_repo = repository()
    with open_game(second_repo, store) as game:
        assert second_repo.get_save(save["id"]) == stored
        assert game.read(a, save) == save
        completed = game.accept(b, save, "vote_ending", {"choice": ending})
        assert completed["completed"] and completed["public"]["ending"] == ending
        assert "puzzle_milestones" not in completed["public"]
        assert "puzzle_evidence" not in completed["personal"]
        record = second_repo.get_save(save["id"])
        assert record.state.puzzles is None
        assert "puzzles" not in record.model_dump(mode="json")["state"]
