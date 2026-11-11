from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from twoworlds.content import loader
from twoworlds.domain.engine import apply_command, create_initial_state
from twoworlds.domain.persistence import (
    AccountRecord,
    CommandReceipt,
    DialogueTurn,
    PairRecord,
    SaveRecord,
    SessionRecord,
)
from twoworlds.domain.projection import project_save
from twoworlds.domain.recap import PublicHistory, append_public_history
from twoworlds.storage import serialization
from twoworlds.storage.serialization import SerializationError, dumps, loads


@pytest.fixture
def script():
    return loader.ScriptLoader(Path(loader.__file__).parent / "scripts").load(
        "lighthouse", "1.0.0"
    )


@pytest.fixture
def now():
    return datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


@pytest.fixture
def save(script, now):
    state = create_initial_state(script)
    history = PublicHistory(
        script_id=script.metadata.id, script_version=script.metadata.content_version
    )
    return SaveRecord(
        id="save_one",
        pair_id="pair_one",
        script_id=script.metadata.id,
        script_version=script.metadata.content_version,
        version=0,
        state=state,
        public_history=history,
        created_at=now,
        updated_at=now,
    )


def digest(char):
    return char * 64


def test_save_round_trip_binds_state_and_public_history(save):
    assert loads(dumps(save), SaveRecord) == save


def test_save_rejects_mismatched_state_or_history(save):
    with pytest.raises(ValidationError):
        SaveRecord.model_validate({**save.model_dump(), "version": 1})
    with pytest.raises(ValidationError):
        SaveRecord.model_validate(
            {
                **save.model_dump(),
                "public_history": {
                    **save.public_history.model_dump(),
                    "through_version": 1,
                },
            }
        )


def test_receipts_are_actor_scoped_and_versions_are_unique(save, now):
    request_id = uuid4()
    first = CommandReceipt(
        actor_id="account_a",
        request_id=request_id,
        fingerprint=digest("a"),
        accepted_version=1,
        created_at=now,
    )
    second = CommandReceipt(
        actor_id="account_b",
        request_id=request_id,
        fingerprint=digest("b"),
        accepted_version=2,
        created_at=now + timedelta(seconds=1),
    )
    updated = SaveRecord.model_validate(
        {
            **save.model_dump(),
            "version": 2,
            "state": save.state.model_dump() | {"version": 2},
            "public_history": save.public_history.model_dump() | {"through_version": 2},
            "receipts": (first.model_dump(), second.model_dump()),
        }
    )
    assert len(loads(dumps(updated), SaveRecord).receipts) == 2
    with pytest.raises(ValidationError):
        SaveRecord.model_validate(
            {
                **updated.model_dump(),
                "receipts": (first.model_dump(), first.model_dump()),
            }
        )
    with pytest.raises(ValidationError):
        SaveRecord.model_validate(
            {
                **updated.model_dump(),
                "receipts": (second.model_dump(), first.model_dump()),
            }
        )


def test_dialogue_limit_is_twenty_per_role(save, now):
    turns = tuple(
        DialogueTurn(
            role=role, question=f"Q{i}", answer="A", mode="demo", created_at=now
        )
        for role in ("a", "b")
        for i in range(20)
    )
    assert (
        len(
            SaveRecord.model_validate(
                {**save.model_dump(), "dialogues": turns}
            ).dialogues
        )
        == 40
    )
    with pytest.raises(ValidationError):
        SaveRecord.model_validate(
            {**save.model_dump(), "dialogues": turns + (turns[0],)}
        )


def test_account_sessions_are_bounded_unique_and_timezone_aware(now):
    sessions = tuple(
        SessionRecord(
            token_digest=digest(hex(i)[2:]),
            created_at=now,
            expires_at=now + timedelta(days=7),
        )
        for i in range(5)
    )
    account = AccountRecord(
        id="account_a",
        display_name="旅人",
        recovery_digest=digest("f"),
        sessions=sessions,
        created_at=now,
        updated_at=now,
    )
    assert loads(dumps(account), AccountRecord) == account
    with pytest.raises(ValidationError):
        AccountRecord.model_validate(
            {**account.model_dump(), "sessions": sessions + (sessions[0],)}
        )
    with pytest.raises(ValidationError):
        SessionRecord(
            token_digest=digest("e"),
            created_at=datetime(2026, 11, 10, 12),
            expires_at=now + timedelta(days=1),
        )


def test_pair_rejects_self_membership_and_round_trips(now):
    pair = PairRecord(
        id="pair_one",
        member_a="account_a",
        invite_digest=digest("c"),
        invite_expires_at=now + timedelta(hours=24),
        created_at=now,
        updated_at=now,
    )
    assert loads(dumps(pair), PairRecord) == pair
    with pytest.raises(ValidationError):
        PairRecord(
            id="pair_bad",
            member_a="account_a",
            member_b="account_a",
            invite_digest=digest("d"),
            invite_expires_at=now + timedelta(hours=24),
            created_at=now,
            updated_at=now,
        )


def test_serialization_rejects_duplicate_keys_nonstandard_json_and_extra_fields():
    with pytest.raises(SerializationError):
        loads('{"id":"one","id":"two"}', AccountRecord)
    with pytest.raises(SerializationError):
        loads('{"value":NaN}', AccountRecord)
    with pytest.raises(SerializationError):
        loads('{"unexpected":true}', AccountRecord)


def _advanced_save(save, script, now):
    state, history, receipts = save.state, save.public_history, []
    shared_request_id = uuid4()
    for role, actor, request, action in (
        (
            "a",
            "account_a",
            shared_request_id,
            {"kind": "inspect", "args": {"target": "maintenance_log"}},
        ),
        (
            "b",
            "account_b",
            shared_request_id,
            {"kind": "inspect", "args": {"target": "sea_chart"}},
        ),
        (
            "a",
            "account_a",
            uuid4(),
            {"kind": "share_clue", "args": {"clue_id": "a_maintenance_log"}},
        ),
    ):
        state, events = apply_command(state, script, role, action)
        history = append_public_history(history, script, state.version, events)
        receipts.append(
            CommandReceipt(
                actor_id=actor,
                request_id=request,
                fingerprint=digest("a"),
                accepted_version=state.version,
                created_at=now,
            )
        )
    turn = DialogueTurn(
        role="a",
        question="信号稳定了吗？",
        answer="灯亮了 🌊",
        mode="demo",
        created_at=now,
    )
    return SaveRecord.model_validate(
        {
            **save.model_dump(),
            "state": state,
            "public_history": history,
            "version": state.version,
            "dialogues": (turn,),
            "receipts": tuple(receipts),
        }
    )


def test_real_save_round_trip_keeps_history_receipts_and_chinese(save, script, now):
    source = _advanced_save(save, script, now.astimezone(timezone(timedelta(hours=8))))
    raw = dumps(source)
    restored = loads(raw, SaveRecord)
    assert "灯亮了 🌊" in raw
    assert restored == source
    assert restored.dialogues[0].created_at.tzinfo is timezone.utc
    assert restored.receipts[0].request_id == restored.receipts[1].request_id
    assert restored.receipts[0].actor_id != restored.receipts[1].actor_id
    assert [entry.accepted_version for entry in restored.receipts] == [1, 2, 3]
    assert project_save(
        restored.state, script, "b", restored.public_history
    ).public.events
    for record, attr in (
        (restored, "version"),
        (restored.state, "version"),
        (restored.public_history, "through_version"),
        (restored.dialogues[0], "answer"),
        (restored.receipts[0], "accepted_version"),
    ):
        with pytest.raises(ValidationError, match="frozen_instance"):
            setattr(record, attr, getattr(record, attr))


@pytest.mark.parametrize(
    "field, child, value",
    [
        ("state", "script_id", "starline"),
        ("state", "script_version", "2.0.0"),
        ("state", "version", 1),
        ("public_history", "script_id", "starline"),
        ("public_history", "script_version", "2.0.0"),
        ("public_history", "through_version", 1),
    ],
)
def test_decode_revalidates_aggregate_bindings(save, field, child, value):
    data = json.loads(dumps(save))
    data[field][child] = value
    with pytest.raises(SerializationError):
        loads(json.dumps(data), SaveRecord)


@pytest.mark.parametrize(
    "case", ["same_actor_request", "same_version", "future_version", "unordered"]
)
def test_decode_revalidates_receipt_identity_and_version(save, script, now, case):
    data = json.loads(dumps(_advanced_save(save, script, now)))
    first, second, _ = data["receipts"]
    if case == "same_actor_request":
        second["actor_id"] = first["actor_id"]
    elif case == "same_version":
        second["accepted_version"] = first["accepted_version"]
    elif case == "future_version":
        data["receipts"][-1]["accepted_version"] = data["version"] + 1
    else:
        data["receipts"].reverse()
    with pytest.raises(SerializationError):
        loads(json.dumps(data), SaveRecord)


@pytest.mark.parametrize(
    "bad", ["event_count", "event_version", "ordinal", "milestone_version"]
)
def test_load_rejects_history_with_invalid_structure(save, script, now, bad):
    data = json.loads(dumps(_advanced_save(save, script, now)))
    history = data["public_history"]
    if bad == "event_count":
        history["event_count"] += 1
    elif bad == "event_version":
        history["events"][0]["version"] = data["version"] + 1
    elif bad == "milestone_version":
        history["milestones"][0]["version"] = 1
    else:
        history["events"][0]["ordinal"] += 1
    with pytest.raises(SerializationError):
        loads(json.dumps(data), SaveRecord)


def test_aggregate_revalidates_unchecked_nested_state_and_receipts(save, script, now):
    advanced = _advanced_save(save, script, now)
    data = advanced.model_dump()
    with pytest.raises(ValidationError):
        SaveRecord.model_validate(
            data | {"state": advanced.state.model_copy(update={"version": 3.0})}
        )
    invalid = advanced.receipts[0].model_copy(update={"accepted_version": True})
    with pytest.raises(ValidationError):
        SaveRecord.model_validate(
            data | {"receipts": (invalid, *advanced.receipts[1:])}
        )


def test_account_revalidates_unchecked_session_instances(now):
    session = SessionRecord(
        token_digest=digest("a"), created_at=now, expires_at=now + timedelta(hours=1)
    )
    forged = session.model_copy(update={"token_digest": "not-a-digest"})
    with pytest.raises(ValidationError):
        AccountRecord(
            id="account_a",
            display_name="旅人",
            recovery_digest=digest("b"),
            sessions=(forged,),
            created_at=now,
            updated_at=now,
        )


def test_write_revalidates_save_after_model_copy(save):
    forged = save.model_copy(update={"version": 1})
    with pytest.raises(SerializationError):
        dumps(forged)


@pytest.mark.parametrize("answer", [" ", "长" * 2001], ids=["blank", "too-long"])
def test_dialogue_answer_must_have_bounded_text(now, answer):
    with pytest.raises(ValidationError):
        DialogueTurn(
            role="a", question="你好？", answer=answer, mode="demo", created_at=now
        )


def test_fallback_dialogue_round_trips(now):
    fallback = DialogueTurn(
        role="b", question="还在吗？", answer="在。", mode="fallback", created_at=now
    )
    assert loads(dumps(fallback), DialogueTurn) == fallback


def test_pair_expiry_must_follow_creation(now):
    with pytest.raises(ValidationError):
        PairRecord(
            id="pair_bad",
            member_a="account_a",
            invite_digest=digest("c"),
            invite_expires_at=now,
            created_at=now,
            updated_at=now,
        )


@pytest.mark.parametrize(
    "invalid",
    [1_700_000_000, "1700000000", "2026-11-10T12:00:00", "0001-01-01T00:00:00+14:00"],
)
def test_storage_rejects_invalid_timestamp_inputs(now, invalid):
    with pytest.raises(SerializationError):
        loads(
            json.dumps(
                {
                    "token_digest": digest("a"),
                    "created_at": invalid,
                    "expires_at": (now + timedelta(days=1)).isoformat(),
                }
            ),
            SessionRecord,
        )


class JsonProbe(BaseModel):
    values: dict[str, float | str]


@pytest.mark.parametrize(
    "raw",
    [
        '{"values":{"key":1,"key":2}}',
        '{"values":{"key":NaN}}',
        '{"values":{"key":Infinity}}',
        '{"values":{"key":-Infinity}}',
        '{"values":{"key":1e999}}',
        '{"values":{"key":"\\ud800"}}',
        '{"values":{"\\ud800":"text"}}',
        '{"values":{"key":"' + chr(0xD800) + '"}}',
    ],
)
def test_json_rejects_ambiguous_numbers_and_invalid_unicode(raw):
    with pytest.raises(SerializationError):
        loads(raw, JsonProbe)


def test_size_limit_uses_utf8_bytes_in_both_directions(monkeypatch):
    model = JsonProbe(values={"key": "灯🌊"})
    raw = dumps(model)
    size = len(raw.encode("utf-8"))
    monkeypatch.setattr(serialization, "MAX_DOCUMENT_BYTES", size)
    assert loads(dumps(model), JsonProbe) == model
    monkeypatch.setattr(serialization, "MAX_DOCUMENT_BYTES", size - 1)
    assert len(raw) < serialization.MAX_DOCUMENT_BYTES
    with pytest.raises(SerializationError):
        dumps(model)
    with pytest.raises(SerializationError):
        loads(raw, JsonProbe)


def test_write_rejects_invalid_unicode_without_leaking_encoding_error():
    with pytest.raises(SerializationError):
        dumps(JsonProbe(values={"key": chr(0xD800)}))


def test_offset_in_stored_json_restores_utc_and_microseconds():
    raw = json.dumps(
        {
            "token_digest": digest("a"),
            "created_at": "2026-11-10T20:00:00.123456+08:00",
            "expires_at": "2026-11-11T20:00:00.123456+08:00",
        }
    )
    restored = loads(raw, SessionRecord)
    assert restored.created_at == datetime(
        2026, 11, 10, 12, 0, 0, 123456, tzinfo=timezone.utc
    )
    assert restored.created_at.tzinfo is timezone.utc
    assert loads(dumps(restored), SessionRecord) == restored


def test_receipt_capacity_is_readable_and_cannot_be_exceeded(save, now):
    receipts = tuple(
        CommandReceipt(
            actor_id="account_a",
            request_id=uuid4(),
            fingerprint=digest("a"),
            accepted_version=i,
            created_at=now,
        )
        for i in range(1, 514)
    )
    data = save.model_dump() | {
        "version": 512,
        "state": save.state.model_dump() | {"version": 512},
        "public_history": save.public_history.model_dump() | {"through_version": 512},
        "receipts": receipts[:512],
    }
    full = SaveRecord.model_validate(data)
    restored = loads(dumps(full), SaveRecord)
    assert restored.version == 512
    assert [receipt.accepted_version for receipt in restored.receipts] == list(
        range(1, 513)
    )
    assert restored.receipts[0] == receipts[0]
    assert restored.receipts[-1] == receipts[511]
    with pytest.raises(ValidationError):
        SaveRecord.model_validate(data | {"receipts": receipts})


@pytest.mark.parametrize(
    "version,versions",
    [(0, []), (1, [1]), (512, list(range(1, 513)))],
    ids=["new-save", "first-command", "full-save"],
)
def test_save_accepts_complete_continuous_receipts(save, now, version, versions):
    receipts = tuple(
        CommandReceipt(
            actor_id="account_a",
            request_id=uuid4(),
            fingerprint=digest("a"),
            accepted_version=accepted,
            created_at=now,
        )
        for accepted in versions
    )
    data = save.model_dump() | {
        "version": version,
        "state": save.state.model_dump() | {"version": version},
        "public_history": save.public_history.model_dump()
        | {"through_version": version},
        "receipts": receipts,
    }
    restored = loads(dumps(SaveRecord.model_validate(data)), SaveRecord)
    assert [item.accepted_version for item in restored.receipts] == versions


@pytest.mark.parametrize(
    "version,versions",
    [
        (0, [1]),
        (1, []),
        (2, [2]),
        (3, [1, 3]),
        (3, [2, 1, 3]),
        (3, [1, 2]),
        (513, list(range(1, 513))),
        (513, list(range(1, 514))),
    ],
    ids=[
        "zero-with-receipt",
        "missing-only",
        "missing-first",
        "missing-middle",
        "unordered",
        "missing-last",
        "over-version-with-512",
        "over-version-with-513",
    ],
)
def test_save_rejects_incomplete_or_over_limit_receipts(save, now, version, versions):
    receipts = tuple(
        CommandReceipt(
            actor_id="account_a",
            request_id=uuid4(),
            fingerprint=digest("a"),
            accepted_version=accepted,
            created_at=now,
        )
        for accepted in versions
    )
    data = save.model_dump() | {
        "version": version,
        "state": save.state.model_dump() | {"version": version},
        "public_history": save.public_history.model_dump()
        | {"through_version": version},
        "receipts": receipts,
    }
    with pytest.raises(ValidationError):
        SaveRecord.model_validate(data)
    with pytest.raises(SerializationError):
        loads(
            json.dumps(
                data | {"receipts": [r.model_dump(mode="json") for r in receipts]},
                default=str,
            ),
            SaveRecord,
        )
