from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import uuid4

import pytest

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
from twoworlds.domain.recap import PublicHistory, append_public_history


@pytest.fixture
def now():
    return datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


@pytest.fixture
def mongo_database():
    from pymongo import MongoClient

    uri = os.environ.get("MONGO_URI")
    if not uri:
        pytest.fail("Real Mongo tests require MONGO_URI; no mock or fallback is used")
    client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    name = "twoworlds_test_t052_" + uuid4().hex
    owned = False
    try:
        client.admin.command("ping")
        assert name not in client.list_database_names()
        owned = True
        yield client[name], uri
    finally:
        # Only this fixture's random database is eligible for cleanup.
        try:
            if owned:
                client.drop_database(name)
        finally:
            client.close()


@pytest.fixture
def mongo_repository_factory(mongo_database):
    from twoworlds.storage.mongo import MongoRepository

    database, uri = mongo_database
    opened = []

    def factory():
        repo = MongoRepository(uri, database.name)
        opened.append(repo)
        return repo

    yield factory
    for repo in opened:
        repo.close()


@pytest.fixture
def repository_factory(request):
    backend = os.environ.get("TWOWORLDS_TEST_BACKEND", "sqlite")
    if backend not in {"sqlite", "mongo"}:
        pytest.fail("TWOWORLDS_TEST_BACKEND must be sqlite or mongo")
    return request.getfixturevalue(f"{backend}_repository_factory")


@pytest.fixture
def sqlite_repository_factory(tmp_path):
    from twoworlds.storage.sqlite import SQLiteRepository

    opened = []

    def factory():
        repo = SQLiteRepository(tmp_path / "repository.sqlite")
        opened.append(repo)
        return repo

    yield factory
    for repo in opened:
        repo.close()


@pytest.fixture
def account_factory(now):
    def factory(name="a"):
        index = {"a": "1", "b": "2", "c": "3", "d": "4"}[name]
        return AccountRecord(
            id="account_" + name,
            email=f"player-{name}@example.com",
            email_verified_at=now,
            password_hash="$argon2id$v=19$m=65536,t=3,p=4$" + index * 40,
            display_name="玩家" + name,
            sessions=(
                SessionRecord(
                    token_digest=hex(int(index) + 5)[2:] * 64,
                    created_at=now,
                    expires_at=now + timedelta(days=1),
                ),
            ),
            created_at=now,
            updated_at=now,
        )

    return factory


@pytest.fixture
def pair_record(now):
    return PairRecord(
        id="pair_one",
        member_a="account_a",
        invite_digest="e" * 64,
        invite_expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def script():
    return loader.ScriptLoader(Path(loader.__file__).parent / "scripts").load(
        "lighthouse", "1.0.0"
    )


@pytest.fixture
def save_record(script, now):
    return SaveRecord(
        id="save_one",
        pair_id="pair_one",
        script_id="lighthouse",
        script_version="1.0.0",
        version=0,
        state=create_initial_state(script),
        public_history=PublicHistory(script_id="lighthouse", script_version="1.0.0"),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def advance(script, now):
    def factory(save, role="a", request_id=None, kind=None, args=None):
        if kind is None:
            kind = "inspect"
            args = {"target": "maintenance_log" if role == "a" else "sea_chart"}
        state, events = apply_command(
            save.state, script, role, {"kind": kind, "args": args}
        )
        history = append_public_history(
            save.public_history, script, state.version, events
        )
        receipt = CommandReceipt(
            actor_id="account_" + role,
            request_id=request_id or uuid4(),
            fingerprint="a" * 64,
            accepted_version=state.version,
            created_at=now,
        )
        turn = DialogueTurn(
            role=role,
            question=f"第{state.version}步听到了吗？",
            answer="灯塔收到。",
            mode="demo",
            created_at=now,
        )
        return SaveRecord.model_validate(
            save.model_dump()
            | {
                "version": state.version,
                "state": state,
                "public_history": history,
                "receipts": (*save.receipts, receipt),
                "dialogues": (turn,),
            }
        )

    return factory


@pytest.fixture
def world(repository_factory, account_factory, pair_record, save_record, now):
    repo = repository_factory()
    for role in ("a", "b", "c"):
        repo.create_account(account_factory(role))
    repo.create_pair(pair_record)
    repo.join_pair(pair_record.id, "account_b", pair_record.invite_digest, now)
    repo.create_save(save_record)
    return repo
