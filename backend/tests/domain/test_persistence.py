from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from twoworlds.content import loader
from twoworlds.domain.engine import create_initial_state
from twoworlds.domain.persistence import AccountRecord, CommandReceipt, DialogueTurn, PairRecord, SaveRecord, SessionRecord
from twoworlds.domain.recap import PublicHistory
from twoworlds.storage.serialization import SerializationError, dumps, loads


@pytest.fixture
def script():
    return loader.ScriptLoader(Path(loader.__file__).parent / "scripts").load("lighthouse", "1.0.0")


@pytest.fixture
def now():
    return datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


@pytest.fixture
def save(script, now):
    state = create_initial_state(script)
    history = PublicHistory(script_id=script.metadata.id, script_version=script.metadata.content_version)
    return SaveRecord(id="save_one", pair_id="pair_one", script_id=script.metadata.id,
                      script_version=script.metadata.content_version, version=0,
                      state=state, public_history=history, created_at=now, updated_at=now)


def digest(char):
    return char * 64


def test_save_round_trip_binds_state_and_public_history(save):
    assert loads(dumps(save), SaveRecord) == save


def test_save_rejects_mismatched_state_or_history(save):
    with pytest.raises(ValidationError):
        SaveRecord.model_validate({**save.model_dump(), "version": 1})
    with pytest.raises(ValidationError):
        SaveRecord.model_validate({**save.model_dump(), "public_history": {
            **save.public_history.model_dump(), "through_version": 1}})


def test_receipts_are_actor_scoped_and_versions_are_unique(save, now):
    request_id = uuid4()
    first = CommandReceipt(actor_id="account_a", request_id=request_id, fingerprint=digest("a"),
                           accepted_version=1, created_at=now)
    second = CommandReceipt(actor_id="account_b", request_id=request_id, fingerprint=digest("b"),
                            accepted_version=2, created_at=now + timedelta(seconds=1))
    updated = SaveRecord.model_validate({
        **save.model_dump(), "version": 2,
        "state": save.state.model_dump() | {"version": 2},
        "public_history": save.public_history.model_dump() | {"through_version": 2},
        "receipts": (first.model_dump(), second.model_dump())})
    assert len(loads(dumps(updated), SaveRecord).receipts) == 2
    with pytest.raises(ValidationError):
        SaveRecord.model_validate({**updated.model_dump(), "receipts": (first.model_dump(), first.model_dump())})
    with pytest.raises(ValidationError):
        SaveRecord.model_validate({**updated.model_dump(), "receipts": (second.model_dump(), first.model_dump())})


def test_dialogue_limit_is_twenty_per_role(save, now):
    turns = tuple(DialogueTurn(role=role, question=f"Q{i}", answer="A", mode="demo", created_at=now)
                  for role in ("a", "b") for i in range(20))
    assert len(SaveRecord.model_validate({**save.model_dump(), "dialogues": turns}).dialogues) == 40
    with pytest.raises(ValidationError):
        SaveRecord.model_validate({**save.model_dump(), "dialogues": turns + (turns[0],)})


def test_account_sessions_are_bounded_unique_and_timezone_aware(now):
    sessions = tuple(SessionRecord(token_digest=digest(hex(i)[2:]), created_at=now,
                                   expires_at=now + timedelta(days=7)) for i in range(5))
    account = AccountRecord(id="account_a", display_name="旅人", recovery_digest=digest("f"),
                            sessions=sessions, created_at=now, updated_at=now)
    assert loads(dumps(account), AccountRecord) == account
    with pytest.raises(ValidationError):
        AccountRecord.model_validate({**account.model_dump(), "sessions": sessions + (sessions[0],)})
    with pytest.raises(ValidationError):
        SessionRecord(token_digest=digest("e"), created_at=datetime(2026, 11, 10, 12),
                      expires_at=now + timedelta(days=1))


def test_pair_rejects_self_membership_and_round_trips(now):
    pair = PairRecord(id="pair_one", member_a="account_a", invite_digest=digest("c"),
                      invite_expires_at=now + timedelta(hours=24), created_at=now, updated_at=now)
    assert loads(dumps(pair), PairRecord) == pair
    with pytest.raises(ValidationError):
        PairRecord(id="pair_bad", member_a="account_a", member_b="account_a",
                   invite_digest=digest("d"), invite_expires_at=now + timedelta(hours=24),
                   created_at=now, updated_at=now)


def test_serialization_rejects_duplicate_keys_nonstandard_json_and_extra_fields():
    with pytest.raises(SerializationError):
        loads('{"id":"one","id":"two"}', AccountRecord)
    with pytest.raises(SerializationError):
        loads('{"value":NaN}', AccountRecord)
    with pytest.raises(SerializationError):
        loads('{"unexpected":true}', AccountRecord)
