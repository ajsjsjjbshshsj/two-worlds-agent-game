"""Real Save commands and projections around fixture-only typed puzzle evidence."""

from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from tests.contracts.support import (
    Platform,
    command,
    error,
    lighthouse_to_decision,
    ok,
    starline_to_decision,
)
from tests.domain.test_puzzle_foundation import COMPLETIONS, completion
from tests.identity_support import RELAXED_POLICIES, TEST_SECRET, FakeEmailSender
from tests.storage.conftest import (  # noqa: F401
    mongo_database,
    mongo_repository_factory,
    sqlite_repository_factory,
)
from twoworlds.api.app import create_app
from twoworlds.domain.engine import apply_command
from twoworlds.domain.errors import DomainError
from twoworlds.domain.persistence import CommandReceipt, SaveRecord
from twoworlds.domain.puzzles import (
    Challenge,
    EchoState,
    EvidenceKind,
    LighthousePuzzles,
    Reply,
    TideRange,
    TideReading,
    TideState,
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
    return staged_candidate(save, script, actor, LighthousePuzzles(l03=chapter))


def staged_candidate(save, script, actor, puzzles, *, result=None):
    # Simulate trusted candidates from a future rule without exposing a test command.
    context = save.next_evidence_context()
    state, events = result if result is not None else (save.state, ())
    return SaveRecord.model_validate(
        save.model_dump()
        | {
            "state": state.model_dump()
            | {
                "version": context.accepted_version,
                "puzzles": puzzles,
            },
            "version": context.accepted_version,
            "public_history": append_public_history(
                save.public_history, script, context.accepted_version, events
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
        for actor, own, partner in ((a, reply, challenge), (b, challenge, reply)):
            view = game.read(actor, save)
            assert view["personal"]["puzzle_evidence"] == []
            assert view["personal"]["puzzle_evidence_history"] == [
                {
                    "id": str(own.id),
                    "kind": own.kind.value,
                    "accepted_version": own.accepted_version,
                    "reason": "configuration_changed",
                }
            ]
            assert str(partner.id) not in str(view)
            assert str(own.id) not in str(view["public"])
            with game.http.websocket_connect(
                f"/api/ws/saves/{save['id']}", headers=actor.headers
            ) as ws:
                assert ws.receive_json() == {"type": "snapshot", "save": view}
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


def test_tide_current_and_submitted_readings_survive_http_and_ws_reconnect(
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
        state = repo.get_save(save["id"])

        def stage(**fields):
            nonlocal state
            chapter = TideState.model_validate(
                state.state.puzzles.l05.model_dump() | fields
            )
            candidate = staged_candidate(
                state, script, a, LighthousePuzzles(l05=chapter)
            )
            assert repo.compare_and_swap_save(state.id, state.version, candidate)
            state = candidate

        def new_reading(key, windows):
            ctx = state.next_evidence_context()
            return TideReading(
                id=ctx.id_for(EvidenceKind.TIDE_READING),
                accepted_version=ctx.accepted_version,
                record_key=key,
                windows=windows,
            )

        old = new_reading("private_pinned_tide", ("early", "middle"))
        stage(reading=old)
        ref = state.next_evidence_context()
        submitted = TideRange(
            id=ref.id_for(EvidenceKind.TIDE_RANGE),
            accepted_version=ref.accepted_version,
            reading_id=old.id,
        )
        stage(submitted_reading=old, tide_range=submitted)
        current = new_reading("private_current_tide", ("late",))
        stage(reading=current)
    reopened = repository()
    with open_game(reopened, store) as game:
        for actor in (a, b):
            view = game.read(actor, save)
            evidence = {
                item["id"]: item for item in view["personal"]["puzzle_evidence"]
            }
            if actor == a:
                assert evidence == {
                    str(current.id): {
                        "id": str(current.id),
                        "kind": "tide_reading",
                        "windows": ["late"],
                    },
                    str(old.id): {
                        "id": str(old.id),
                        "kind": "tide_reading",
                        "windows": ["early", "middle"],
                    },
                    str(submitted.id): {
                        "id": str(submitted.id),
                        "kind": "tide_range",
                        "reading_id": str(old.id),
                        "windows": ["early", "middle"],
                    },
                }
            else:
                assert evidence == {
                    str(submitted.id): {"id": str(submitted.id), "kind": "tide_range"}
                }
                assert str(old.id) not in str(view) and str(current.id) not in str(view)
            for identifier in (old.id, current.id, submitted.id):
                assert str(identifier) not in str(view["public"])
            with game.http.websocket_connect(
                f"/api/ws/saves/{save['id']}", headers=actor.headers
            ) as ws:
                assert ws.receive_json() == {"type": "snapshot", "save": view}
        restored = reopened.get_save(save["id"])
        # HTTP/WS expose the pinned reading for recovery, but it is no longer a submit candidate.
        persisted = restored.state.puzzles
        with pytest.raises(DomainError) as stale:
            require_current_evidence(
                state.next_evidence_context(),
                persisted,
                old.id,
                EvidenceKind.TIDE_READING,
                issuer="a",
            )
        assert stale.value.code == "EVIDENCE_STALE"


LIGHTHOUSE_PATH = (
    ("a", "inspect", {"target": "maintenance_log"}),
    ("b", "inspect", {"target": "sea_chart"}),
    ("a", "set_emitter", {"angle": 90, "pattern": "pulse"}),
    ("b", "set_filter", {"filter": "amber"}),
    ("b", "lock_signal", {}),
    ("b", "route_power", {"target": "tower"}),
    ("a", "inspect", {"target": "clock_gears"}),
    ("a", "repair_clock", {"mode": "steady"}),
    ("b", "confirm_route", {}),
)
STARLINE_PATH = (
    ("a", "inspect", {"target": "station_log"}),
    ("b", "inspect", {"target": "power_board"}),
    ("a", "set_echo_gate", {"position": "east"}),
    ("b", "allocate_power", {"engine": False, "sonar": True, "lamp": True}),
    ("a", "set_echo_gate", {"position": "west"}),
    ("a", "set_echo_gate", {"position": "east"}),
    ("b", "scan_track", {}),
    ("a", "install_rail", {"segment": "bridge_2"}),
    ("b", "allocate_power", {"engine": True, "sonar": False, "lamp": True}),
    ("b", "confirm_signal", {}),
    ("a", "set_platform", {"track": "track_2"}),
    ("b", "dispatch_train", {}),
)


def rebased_proof(save, chapter, template):
    # Give fixtures the real save scope and command versions without adding fake API actions.
    next_context = save.next_evidence_context()
    offset = next_context.accepted_version - template.accepted_version
    records = template.evidence()
    ids = {
        item.id: next_context.model_copy(
            update={
                "accepted_version": item.accepted_version + offset,
            }
        ).id_for(item.kind, ordinal=item.ordinal)
        for item in records
    }
    revisions = {field: getattr(chapter, field) for field in template.revision_fields}

    def rebase(value):
        if isinstance(value, UUID):
            return ids[value]
        return value

    by_id = {
        item.id: {
            field: revisions.get(field, rebase(value))
            for field, value in item.model_dump().items()
        }
        | {"accepted_version": item.accepted_version + offset}
        for item in records
    }
    payload = (
        template.model_dump()
        | revisions
        | {"accepted_version": next_context.accepted_version}
    )
    for field in type(template).model_fields:
        record = getattr(template, field)
        if hasattr(record, "id"):
            payload[field] = by_id[record.id]
    return type(template).model_validate(payload)


@pytest.mark.parametrize(
    "chapter_name, target, path, fixture",
    [
        ("l03", "lock_signal", LIGHTHOUSE_PATH, COMPLETIONS[0]),
        ("l05", "confirm_route", LIGHTHOUSE_PATH, COMPLETIONS[1]),
        ("s03", "scan_track", STARLINE_PATH, COMPLETIONS[2]),
        ("s05", "dispatch_train", STARLINE_PATH, COMPLETIONS[3]),
    ],
)
def test_consumed_milestone_remains_valid_after_repository_restart(
    repository,
    published_story,
    chapter_name,
    target,
    path,
    fixture,
):
    story = "lighthouse" if chapter_name.startswith("l") else "starline"
    store, publish = published_story
    script = publish(
        identifier=story,
        version="1.1.0",
        transform=lambda doc: doc.update(puzzle_rules="p0_v1"),
    )
    make, proof_type, slot, _, _, _, version, extra = fixture
    repo = repository()
    with open_game(repo, store) as game:
        a, b, pair = game.pair()
        save = game.save(a, pair, story, version="1.1.0")
        for role, kind, args in path:
            if kind == target:
                break
            save = game.accept(a if role == "a" else b, save, kind, args)
        previous = repo.get_save(save["id"])
        chapter = getattr(previous.state.puzzles, chapter_name)
        proof = rebased_proof(
            previous, chapter, completion(make(), proof_type, version, **extra)
        )
        finished = type(chapter).model_validate(chapter.model_dump() | {slot: proof})
        puzzles = type(previous.state.puzzles).model_validate(
            previous.state.puzzles.model_dump() | {chapter_name: finished}
        )
        result = apply_command(
            previous.state, script, role, {"kind": kind, "args": args}
        )
        candidate = staged_candidate(previous, script, b, puzzles, result=result)
        assert repo.compare_and_swap_save(previous.id, previous.version, candidate)
        stale_proof = proof.model_copy(
            update={"accepted_version": proof.accepted_version + 1}
        )
        bad_chapter = finished.model_copy(update={slot: stale_proof})
        bad_puzzles = puzzles.model_copy(update={chapter_name: bad_chapter})
        with pytest.raises(ValidationError, match="public history version"):
            staged_candidate(candidate, script, b, bad_puzzles)

    reopened = repository()
    with open_game(reopened, store) as game:
        loaded = reopened.get_save(save["id"])
        restored_chapter = getattr(loaded.state.puzzles, chapter_name)
        assert loaded == candidate and getattr(restored_chapter, slot) == proof
        assert not restored_chapter.active_evidence()
        assert proof.accepted_version == loaded.receipts[-1].accepted_version
        public = game.read(a, save)["public"]
        assert (
            public["puzzle_milestones"][0]["accepted_version"] == proof.accepted_version
        )
        for record in proof.evidence():
            assert str(record.id) not in str(public)
        with pytest.raises(ValidationError, match="evidence scope"):
            SaveRecord.model_validate(loaded.model_dump() | {"id": "another_save"})
