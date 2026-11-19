"""Adapter-neutral behavior. Mongo can supply the same repository_factory fixture."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from twoworlds.application.commands import GameCommand
from twoworlds.content import loader
from twoworlds.domain.engine import apply_command, create_initial_state
from twoworlds.domain.persistence import (
    CommandReceipt,
    DialogueTurn,
    RateLimitRecord,
    SaveRecord,
    VerificationCodeRecord,
)
from twoworlds.domain.recap import PublicHistory, append_public_history
from twoworlds.ports.repository import (
    DuplicateRecord,
    InvalidRepositoryTransition,
    MissingRecord,
    ReceiptLimitReached,
)


def test_two_story_dialogues_keep_save_and_role_identity_after_reopen(
    world, repository_factory, script, save_record, now
):
    """Storage preservation only: this does not implement a private dialogue API."""
    starline = loader.ScriptLoader(Path(loader.__file__).parent / "scripts").load(
        "starline", "1.0.0"
    )
    other = world.create_save(
        SaveRecord(
            id="save_starline",
            pair_id=save_record.pair_id,
            script_id="starline",
            script_version="1.0.0",
            version=0,
            state=create_initial_state(starline),
            public_history=PublicHistory(script_id="starline", script_version="1.0.0"),
            created_at=now,
            updated_at=now,
        )
    )
    ids = (save_record.id, other.id)
    requests = {role: uuid4() for role in ("a", "b")}
    expected = {}
    for source, save_id, targets in (
        (script, save_record.id, {"a": "maintenance_log", "b": "sea_chart"}),
        (starline, other.id, {"a": "station_log", "b": "power_board"}),
    ):
        for role in ("a", "b"):
            current = world.get_save(save_id)
            untouched_id = next(
                identifier for identifier in ids if identifier != save_id
            )
            untouched = world.get_save(untouched_id)
            command = GameCommand(
                request_id=requests[role],
                expected_version=current.version,
                kind="inspect",
                args={"target": targets[role]},
            )
            state, events = apply_command(
                current.state,
                source,
                role,
                {"kind": command.kind, "args": command.args},
            )
            marker = f"{source.metadata.id}/{role}"
            turn = DialogueTurn(
                role=role,
                question=f"{marker} 私有问题",
                answer=f"{marker} 私有回答",
                mode="demo",
                created_at=now,
            )
            candidate = SaveRecord.model_validate(
                current.model_dump()
                | {
                    "version": state.version,
                    "state": state,
                    "public_history": append_public_history(
                        current.public_history, source, state.version, events
                    ),
                    "dialogues": (*current.dialogues, turn),
                    "receipts": (
                        *current.receipts,
                        CommandReceipt(
                            actor_id="account_" + role,
                            request_id=command.request_id,
                            fingerprint=command.fingerprint(),
                            accepted_version=state.version,
                            created_at=now,
                        ),
                    ),
                }
            )
            assert world.compare_and_swap_save(save_id, current.version, candidate)
            assert world.get_save(untouched_id) == untouched
            expected[save_id] = candidate
    world.close()
    reopened = repository_factory()
    for save_id, aggregate in expected.items():
        restored = reopened.get_save(save_id)
        assert restored == aggregate
        assert restored.version == restored.state.version == 2
        assert restored.public_history.through_version == 2
        assert tuple(turn.role for turn in restored.dialogues) == ("a", "b")
        for role in ("a", "b"):
            # Check stored role attribution, not a fabricated authorization endpoint.
            turns = tuple(turn for turn in restored.dialogues if turn.role == role)
            marker = f"{restored.script_id}/{role}"
            assert len(turns) == 1
            assert turns[0].question == f"{marker} 私有问题"
            assert turns[0].answer == f"{marker} 私有回答"
            receipt = reopened.get_receipt(save_id, "account_" + role, requests[role])
            assert receipt in restored.receipts


def test_member_pairs_query_is_isolated_ordered_and_fresh(
    repository_factory, account_factory, pair_record, now
):
    repo = repository_factory()
    for name in ("a", "b", "c"):
        repo.create_account(account_factory(name))
    first = repo.create_pair(pair_record.model_copy(update={"id": "pair_z"}))
    second = repo.create_pair(
        pair_record.model_copy(
            update={"id": "pair_a", "member_a": "account_b", "invite_digest": "f" * 64}
        )
    )
    third = repo.create_pair(
        pair_record.model_copy(
            update={"id": "pair_c", "member_a": "account_c", "invite_digest": "0" * 64}
        )
    )
    assert repo.list_pairs_for_member("missing") == ()
    assert repo.list_pairs_for_member("account_a") == (first,)
    assert repo.join_pair(second.id, "account_a", second.invite_digest, now)
    joined = repo.get_pair(second.id)
    assert repo.list_pairs_for_member("account_a") == (joined, first)
    assert repo.list_pairs_for_member("account_b") == (joined,)
    assert repo.list_pairs_for_member("account_c") == (third,)


def test_pair_saves_query_is_isolated_ordered_and_validated(
    world, save_record, pair_record
):
    first = world.get_save(save_record.id)
    other_pair = world.create_pair(
        pair_record.model_copy(
            update={
                "id": "pair_other",
                "member_a": "account_c",
                "invite_digest": "f" * 64,
            }
        )
    )
    world.create_save(
        save_record.model_copy(
            update={"id": "save_elsewhere", "pair_id": other_pair.id}
        )
    )
    # Persistence supports independent story IDs; rule dispatch remains a domain concern.
    second = world.create_save(
        save_record.model_copy(
            update={
                "id": "save_aaa",
                "script_id": "other_story",
                "state": save_record.state.model_copy(
                    update={"script_id": "other_story"}
                ),
                "public_history": save_record.public_history.model_copy(
                    update={"script_id": "other_story"}
                ),
            }
        )
    )
    assert world.list_saves_for_pair("missing") == ()
    assert world.list_saves_for_pair(first.pair_id) == (second, first)
    assert world.list_saves_for_pair(other_pair.id)[0].id == "save_elsewhere"


def test_account_creation_email_lookup_and_uniqueness(
    repository_factory, account_factory
):
    repo = repository_factory()
    account = account_factory()
    assert repo.create_account(account) == account
    assert repo.get_account(account.id) == account
    assert repo.get_account_by_email(account.email) == account
    assert repo.get_account("missing") is None
    assert repo.get_account_by_email("nobody@example.com") is None
    with pytest.raises(DuplicateRecord):
        repo.create_account(account)
    other = account_factory("b")
    for forged in (
        other.model_copy(update={"email": account.email}),
        other.model_copy(update={"sessions": account.sessions}),
    ):
        with pytest.raises(DuplicateRecord):
            repo.create_account(forged)
    assert repo.get_account(other.id) is None


def test_account_session_expiry_and_cas_are_atomic(
    repository_factory, account_factory, now
):
    repo = repository_factory()
    account = repo.create_account(account_factory())
    token = account.sessions[0].token_digest
    assert repo.get_account_by_session_digest(token, now) == account
    assert (
        repo.get_account_by_session_digest(token, account.sessions[0].expires_at)
        is None
    )
    assert repo.get_account_by_session_digest("0" * 64, now) is None
    updated = account.model_copy(
        update={"version": 1, "sessions": (), "display_name": "新名字"}
    )
    assert repo.compare_and_swap_account(account.id, 0, updated)
    assert not repo.compare_and_swap_account(account.id, 0, updated)
    assert repo.get_account_by_session_digest(token, now) is None
    assert repo.get_account(account.id) == updated


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "other"),
        ("email", "other@example.com"),
        ("version", 2),
    ],
)
def test_account_cas_rejects_invalid_candidate(
    repository_factory, account_factory, field, value
):
    repo = repository_factory()
    account = repo.create_account(account_factory())
    candidate = account.model_copy(update={"version": 1, field: value})
    with pytest.raises(InvalidRepositoryTransition):
        repo.compare_and_swap_account(account.id, 0, candidate)
    assert repo.get_account(account.id) == account


def test_pair_creation_invite_and_parent_requirements(
    repository_factory, account_factory, pair_record
):
    repo = repository_factory()
    with pytest.raises(MissingRecord):
        repo.create_pair(pair_record)
    repo.create_account(account_factory())
    assert repo.create_pair(pair_record) == pair_record
    assert repo.get_pair_by_invite_digest(pair_record.invite_digest) == pair_record
    with pytest.raises(DuplicateRecord):
        repo.create_pair(pair_record.model_copy(update={"id": "pair_other"}))


def test_pair_creation_rejects_prefilled_b_without_writing(
    repository_factory, account_factory, pair_record
):
    repo = repository_factory()
    for role in ("a", "b"):
        repo.create_account(account_factory(role))
    candidate = pair_record.model_copy(update={"member_b": "account_b"})
    with pytest.raises(InvalidRepositoryTransition):
        repo.create_pair(candidate)
    assert repo.get_pair(pair_record.id) is None
    assert repo.get_pair_by_invite_digest(pair_record.invite_digest) is None
    assert repo.create_pair(pair_record) == pair_record


@pytest.mark.parametrize("rotate_invite", [False, True])
def test_pair_cas_cannot_claim_b_even_with_a_new_invite(
    repository_factory, account_factory, pair_record, rotate_invite
):
    repo = repository_factory()
    for role in ("a", "b"):
        repo.create_account(account_factory(role))
    repo.create_pair(pair_record)
    candidate = pair_record.model_copy(
        update={
            "version": 1,
            "member_b": "account_b",
            "invite_digest": "f" * 64 if rotate_invite else pair_record.invite_digest,
        }
    )
    with pytest.raises(InvalidRepositoryTransition):
        repo.compare_and_swap_pair(pair_record.id, 0, candidate)
    assert repo.get_pair(pair_record.id) == pair_record
    assert repo.get_pair_by_invite_digest(pair_record.invite_digest) == pair_record
    assert repo.get_pair_by_invite_digest("f" * 64) is None


@pytest.mark.parametrize("replacement", [None, "account_c"])
def test_full_pair_cas_cannot_replace_or_remove_b(
    repository_factory, account_factory, pair_record, now, replacement
):
    repo = repository_factory()
    for role in ("a", "b", "c"):
        repo.create_account(account_factory(role))
    repo.create_pair(pair_record)
    joined = repo.join_pair(pair_record.id, "account_b", pair_record.invite_digest, now)
    assert joined.member_b == "account_b"
    with pytest.raises(InvalidRepositoryTransition):
        repo.compare_and_swap_pair(
            joined.id,
            joined.version,
            joined.model_copy(
                update={"version": joined.version + 1, "member_b": replacement}
            ),
        )
    assert repo.get_pair(joined.id) == joined


def test_pair_join_expiry_self_wrong_invite_and_retry(
    repository_factory, account_factory, pair_record, now
):
    repo = repository_factory()
    for role in ("a", "b", "c"):
        repo.create_account(account_factory(role))
    repo.create_pair(pair_record)
    assert (
        repo.join_pair(pair_record.id, "account_a", pair_record.invite_digest, now)
        is None
    )
    assert repo.join_pair(pair_record.id, "account_b", "0" * 64, now) is None
    assert (
        repo.join_pair(
            pair_record.id,
            "account_b",
            pair_record.invite_digest,
            pair_record.invite_expires_at,
        )
        is None
    )
    joined = repo.join_pair(pair_record.id, "account_b", pair_record.invite_digest, now)
    assert joined.member_b == "account_b" and joined.version == 1
    assert (
        repo.join_pair(
            pair_record.id,
            "account_b",
            pair_record.invite_digest,
            now + timedelta(days=1),
        )
        == joined
    )
    assert (
        repo.join_pair(pair_record.id, "account_c", pair_record.invite_digest, now)
        is None
    )


def test_pair_cas_can_rotate_only_an_unfilled_invite(
    repository_factory, account_factory, pair_record, now
):
    repo = repository_factory()
    for role in ("a", "b"):
        repo.create_account(account_factory(role))
    repo.create_pair(pair_record)
    updated = pair_record.model_copy(update={"version": 1, "invite_digest": "f" * 64})
    assert repo.compare_and_swap_pair(pair_record.id, 0, updated)
    assert not repo.compare_and_swap_pair(pair_record.id, 0, updated)
    assert repo.get_pair_by_invite_digest(pair_record.invite_digest) is None
    assert repo.get_pair_by_invite_digest(updated.invite_digest) == updated
    assert repo.join_pair(updated.id, "account_b", updated.invite_digest, now)
    full = repo.get_pair(updated.id)
    with pytest.raises(InvalidRepositoryTransition):
        repo.compare_and_swap_pair(
            full.id,
            full.version,
            full.model_copy(update={"version": full.version + 1, "member_b": None}),
        )


def test_independent_repositories_compete_for_one_b_slot(
    repository_factory, account_factory, pair_record, now
):
    first, second = repository_factory(), repository_factory()
    assert first is not second
    for role in ("a", "b", "c"):
        first.create_account(account_factory(role))
    first.create_pair(pair_record)
    barrier = Barrier(2)

    def join(params):
        repo, member = params
        barrier.wait(timeout=10)
        return repo.join_pair(pair_record.id, member, pair_record.invite_digest, now)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(join, [(first, "account_b"), (second, "account_c")]))
    assert sum(result is not None for result in results) == 1
    assert first.get_pair(pair_record.id) == second.get_pair(pair_record.id)


def test_save_requires_parent_and_is_unique_per_pair_script(
    repository_factory, world, save_record
):
    assert world.get_save(save_record.id) == save_record
    other = save_record.model_copy(
        update={
            "id": "other_save",
            "script_version": "2.0.0",
            "state": save_record.state.model_copy(update={"script_version": "2.0.0"}),
            "public_history": save_record.public_history.model_copy(
                update={"script_version": "2.0.0"}
            ),
        }
    )
    assert world.create_save(other) == save_record
    assert world.get_save(other.id) is None
    assert (
        world.get_save_for_pair_script(save_record.pair_id, save_record.script_id)
        == save_record
    )
    with pytest.raises(MissingRecord):
        world.create_save(
            save_record.model_copy(update={"id": "orphan", "pair_id": "missing"})
        )


def test_independent_repositories_create_one_save(
    repository_factory, account_factory, pair_record, save_record
):
    first, second = repository_factory(), repository_factory()
    first.create_account(account_factory())
    first.create_pair(pair_record)
    barrier = Barrier(2)

    def create(params):
        repo, identifier = params
        barrier.wait(timeout=10)
        return repo.create_save(save_record.model_copy(update={"id": identifier}))

    with ThreadPoolExecutor(2) as pool:
        records = list(pool.map(create, [(first, "save_a"), (second, "save_b")]))
    assert records[0] == records[1]
    assert (
        first.get_save_for_pair_script(pair_record.id, save_record.script_id)
        == records[0]
    )


def test_pair_join_foreign_key_failure_preserves_old_pair(
    repository_factory, account_factory, pair_record, now
):
    repo = repository_factory()
    repo.create_account(account_factory())
    repo.create_pair(pair_record)
    with pytest.raises(MissingRecord):
        repo.join_pair(
            pair_record.id,
            "missing_account",
            pair_record.invite_digest,
            now,
        )
    assert repo.get_pair(pair_record.id) == pair_record


def test_save_and_receipts_survive_close_and_reopen(
    repository_factory, world, save_record, advance
):
    updated = advance(save_record)
    assert world.compare_and_swap_save(save_record.id, 0, updated)
    world.close()
    reopened = repository_factory()
    assert reopened.get_save(save_record.id) == updated
    receipt = updated.receipts[0]
    assert (
        reopened.get_receipt(save_record.id, receipt.actor_id, receipt.request_id)
        == receipt
    )


def test_receipt_lookup_is_scoped_to_save_and_actor(world, save_record, advance):
    request = uuid4()
    a = advance(save_record, "a", request)
    assert world.compare_and_swap_save(a.id, 0, a)
    b = advance(a, "b", request)
    assert world.compare_and_swap_save(b.id, 1, b)
    assert world.get_receipt(b.id, "account_a", request) == b.receipts[0]
    assert world.get_receipt(b.id, "account_b", request) == b.receipts[1]
    assert world.get_receipt("other", "account_a", request) is None
    assert world.get_receipt(b.id, "account_c", request) is None


def test_existing_saves_keep_versions_and_receipts_independent(
    world, save_record, pair_record, now, advance
):
    pair = pair_record.model_copy(update={"id": "pair_two", "invite_digest": "f" * 64})
    world.create_pair(pair)
    world.join_pair(pair.id, "account_b", pair.invite_digest, now)
    other = save_record.model_copy(update={"id": "save_two", "pair_id": pair.id})
    world.create_save(other)
    request = uuid4()
    first = advance(save_record, "a", request)
    second = advance(other, "b", request)
    assert world.compare_and_swap_save(first.id, 0, first)
    assert world.get_save(other.id) == other
    assert world.get_receipt(other.id, "account_a", request) is None
    assert world.compare_and_swap_save(second.id, 0, second)
    assert world.get_save(first.id) == first
    assert world.get_save(second.id) == second
    assert world.get_receipt(first.id, "account_b", request) is None
    assert world.get_receipt(second.id, "account_a", request) is None


def test_save_cas_updates_entire_aggregate_and_rejects_stale(
    world, save_record, advance
):
    first = advance(save_record)
    assert world.compare_and_swap_save(first.id, 0, first)
    shared = advance(first, kind="share_clue", args={"clue_id": "a_maintenance_log"})
    assert world.compare_and_swap_save(first.id, 1, shared)
    assert world.get_save(first.id) == shared
    assert (
        shared.public_history.milestones
        and shared.dialogues
        and len(shared.receipts) == 2
    )
    assert not world.compare_and_swap_save(first.id, 0, first)
    assert world.get_save(first.id) == shared


def test_independent_connections_compete_on_same_version(
    repository_factory, world, save_record, advance
):
    first, second = repository_factory(), repository_factory()
    candidates = [advance(save_record, "a"), advance(save_record, "b")]
    barrier = Barrier(2)

    def submit(params):
        repo, candidate = params
        barrier.wait(timeout=10)
        return repo.compare_and_swap_save(candidate.id, 0, candidate)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(submit, zip((first, second), candidates)))
    assert sorted(results) == [False, True]
    winner = candidates[results.index(True)]
    assert world.get_save(save_record.id) == winner
    assert (
        world.get_receipt(
            winner.id, winner.receipts[0].actor_id, winner.receipts[0].request_id
        )
        == winner.receipts[0]
    )


@pytest.mark.parametrize(
    "change",
    [
        "identity",
        "pair",
        "script",
        "content_version",
        "version_jump",
        "receipt_rewrite",
        "creation_time",
    ],
)
def test_save_cas_rejects_invalid_transitions(world, save_record, advance, now, change):
    first = advance(save_record)
    assert world.compare_and_swap_save(first.id, 0, first)
    candidate = advance(first, "b")
    fields = {
        "identity": {"id": "other"},
        "pair": {"pair_id": "other"},
        "script": {
            "script_id": "other",
            "state": candidate.state.model_copy(update={"script_id": "other"}),
            "public_history": candidate.public_history.model_copy(
                update={"script_id": "other"}
            ),
        },
        "content_version": {
            "script_version": "2.0.0",
            "state": candidate.state.model_copy(update={"script_version": "2.0.0"}),
            "public_history": candidate.public_history.model_copy(
                update={"script_version": "2.0.0"}
            ),
        },
        "version_jump": {"version": 3},
        "receipt_rewrite": {
            "receipts": (
                candidate.receipts[0].model_copy(update={"fingerprint": "b" * 64}),
                candidate.receipts[1],
            )
        },
        "creation_time": {"created_at": now - timedelta(seconds=1)},
    }[change]
    with pytest.raises(InvalidRepositoryTransition):
        world.compare_and_swap_save(first.id, 1, candidate.model_copy(update=fields))
    assert world.get_save(first.id) == first


def test_full_save_stays_readable_but_rejects_new_cas(world, save_record, now):
    receipts = tuple(
        CommandReceipt(
            actor_id="account_a",
            request_id=uuid4(),
            fingerprint="a" * 64,
            accepted_version=i,
            created_at=now,
        )
        for i in range(1, 513)
    )
    full = SaveRecord.model_validate(
        save_record.model_dump()
        | {
            "id": "full_save",
            "script_id": "full_story",
            "version": 512,
            "state": save_record.state.model_dump()
            | {"script_id": "full_story", "version": 512},
            "public_history": save_record.public_history.model_dump()
            | {"script_id": "full_story", "through_version": 512},
            "receipts": receipts,
        }
    )
    world.create_save(full)
    assert world.get_save(full.id) == full
    assert (
        world.get_receipt(full.id, "account_a", receipts[0].request_id) == receipts[0]
    )
    assert (
        world.get_receipt(full.id, "account_a", receipts[-1].request_id) == receipts[-1]
    )
    with pytest.raises(ReceiptLimitReached):
        world.compare_and_swap_save(full.id, 512, full)
    assert world.get_save(full.id) == full


def code_record(now, **changes):
    base = VerificationCodeRecord(
        id="code_" + "a" * 59,
        email="player-a@example.com",
        purpose="register",
        issue_id="a" * 32,
        digest="d" * 64,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        attempts=0,
        consumed_at=None,
        version=0,
        updated_at=now,
    )
    return base.model_copy(update=changes) if changes else base


def rate_record(now, **changes):
    base = RateLimitRecord(
        id="rate_" + "b" * 59,
        count=1,
        window_start=now,
        expires_at=now + timedelta(seconds=60),
        version=0,
        updated_at=now,
    )
    return base.model_copy(update=changes) if changes else base


def test_verification_code_unique_per_email_purpose_and_round_trip(
    repository_factory, now
):
    repo = repository_factory()
    record = code_record(now)
    assert repo.create_verification_code(record) == record
    assert repo.get_verification_code(record.id) == record
    assert repo.get_verification_code("code_missing") is None
    with pytest.raises(DuplicateRecord):
        repo.create_verification_code(record)
    # Same email with a different purpose is a separate live code.
    other = code_record(now, id="code_" + "c" * 59, purpose="reset")
    assert repo.create_verification_code(other) == other
    # Same email+purpose under a new id still collides on the unique pair.
    with pytest.raises(DuplicateRecord):
        repo.create_verification_code(code_record(now, id="code_" + "e" * 59))


def test_verification_code_cas_consumes_once_under_competition(repository_factory, now):
    barrier = Barrier(2)

    class Aligned:
        def __init__(self, repo):
            self._repo = repo
            self._first = True

        def __getattr__(self, name):
            return getattr(self._repo, name)

        def compare_and_swap_verification_code(self, *args):
            # 只对齐双方的第一次CAS；重试时对方可能已返回，不能再次等待屏障。
            if self._first:
                self._first = False
                barrier.wait(timeout=15)
            return self._repo.compare_and_swap_verification_code(*args)

    first, second = repository_factory(), repository_factory()
    assert first is not second
    first.create_verification_code(code_record(now))
    consumed = code_record(now, version=1, consumed_at=now, updated_at=now)
    with ThreadPoolExecutor(2) as pool:
        futures = [
            pool.submit(
                repo.compare_and_swap_verification_code, consumed.id, 0, consumed
            )
            for repo in (Aligned(first), Aligned(second))
        ]
        results = [f.result(timeout=25) for f in futures]
    assert sorted(results) == [False, True]
    assert first.get_verification_code(consumed.id) == consumed


def test_verification_code_attempts_advance_atomically(repository_factory, now):
    barrier = Barrier(2)

    class Aligned:
        def __init__(self, repo):
            self._repo = repo
            self._first = True

        def __getattr__(self, name):
            return getattr(self._repo, name)

        def compare_and_swap_verification_code(self, *args):
            # 只对齐双方的第一次CAS；重试时对方可能已返回，不能再次等待屏障。
            if self._first:
                self._first = False
                barrier.wait(timeout=15)
            return self._repo.compare_and_swap_verification_code(*args)

    repos = [repository_factory(), repository_factory()]
    repos[0].create_verification_code(code_record(now))

    def bump(repo):
        for _ in range(8):
            current = repo.get_verification_code("code_" + "a" * 59)
            candidate = current.model_copy(
                update={
                    "attempts": current.attempts + 1,
                    "version": current.version + 1,
                    "updated_at": now,
                }
            )
            if repo.compare_and_swap_verification_code(
                current.id, current.version, candidate
            ):
                return

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(bump, [Aligned(repo) for repo in repos]))
    stored = repos[0].get_verification_code("code_" + "a" * 59)
    assert stored.attempts == 2 and stored.version == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "code_" + "f" * 59),
        ("email", "other@example.com"),
        ("purpose", "reset"),
        ("version", 2),
    ],
)
def test_verification_code_cas_rejects_invalid_candidate(
    repository_factory, now, field, value
):
    repo = repository_factory()
    record = repo.create_verification_code(code_record(now))
    candidate = record.model_copy(update={"version": 1, field: value})
    with pytest.raises(InvalidRepositoryTransition):
        repo.compare_and_swap_verification_code(record.id, 0, candidate)
    assert repo.get_verification_code(record.id) == record


def test_expired_verification_codes_cleanup(repository_factory, now):
    repo = repository_factory()
    live = repo.create_verification_code(code_record(now))
    expired = repo.create_verification_code(
        code_record(
            now,
            id="code_" + "d" * 59,
            purpose="reset",
            expires_at=now + timedelta(seconds=1),
        )
    )
    assert repo.delete_expired_verification_codes(now) == 0
    later = now + timedelta(seconds=2)
    assert repo.delete_expired_verification_codes(later) == 1
    assert repo.get_verification_code(expired.id) is None
    assert repo.get_verification_code(live.id) == live


def test_rate_limit_counter_atomic_competition(repository_factory, now):
    repos = [repository_factory() for _ in range(4)]
    repos[0].create_rate_limit(rate_record(now))

    def bump(repo):
        for _ in range(16):
            current = repo.get_rate_limit("rate_" + "b" * 59)
            candidate = current.model_copy(
                update={
                    "count": current.count + 1,
                    "version": current.version + 1,
                    "updated_at": now,
                }
            )
            if repo.compare_and_swap_rate_limit(current.id, current.version, candidate):
                return
        raise AssertionError("CAS never accepted")

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(bump, repos))
    stored = repos[0].get_rate_limit("rate_" + "b" * 59)
    assert stored.count == 5 and stored.version == 4
    assert repos[0].count_rate_limits() == 1


def test_rate_limit_create_uniqueness_cas_and_cleanup(repository_factory, now):
    repo = repository_factory()
    record = repo.create_rate_limit(rate_record(now))
    assert repo.get_rate_limit(record.id) == record
    assert repo.get_rate_limit("rate_missing") is None
    with pytest.raises(DuplicateRecord):
        repo.create_rate_limit(record)
    candidate = record.model_copy(update={"version": 2, "count": 9})
    with pytest.raises(InvalidRepositoryTransition):
        repo.compare_and_swap_rate_limit(record.id, 0, candidate)
    reset = record.model_copy(
        update={
            "version": 1,
            "count": 1,
            "window_start": now + timedelta(seconds=61),
            "expires_at": now + timedelta(seconds=121),
            "updated_at": now + timedelta(seconds=61),
        }
    )
    assert repo.compare_and_swap_rate_limit(record.id, 0, reset)
    assert not repo.compare_and_swap_rate_limit(record.id, 0, reset)
    assert repo.delete_expired_rate_limits(now + timedelta(seconds=60)) == 0
    assert repo.delete_expired_rate_limits(now + timedelta(seconds=121)) == 1
    assert repo.count_rate_limits() == 0
