"""Real Mongo tests; shared behavior stays in test_repository_contract.py."""

from datetime import timedelta
import json
import os
import socket
import subprocess
import time
from uuid import uuid4

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, DuplicateKeyError
import pytest

from twoworlds.ports.repository import (
    CorruptRecord,
    DuplicateRecord,
    InvalidRepositoryTransition,
    RepositoryError,
)


@pytest.fixture
def repository_factory(mongo_repository_factory):
    return mongo_repository_factory


def test_save_list_revalidates_every_document(mongo_database, world):
    database, _ = mongo_database
    database.saves.update_one({"_id": "save_one"}, {"$set": {"version": 1}})
    with pytest.raises(CorruptRecord):
        world.list_saves_for_pair("pair_one")


def test_indexes_are_named_exact_and_idempotent(mongo_database, repository_factory):
    from twoworlds.storage.indexes import ensure_indexes

    database, _ = mongo_database
    first, second = repository_factory(), repository_factory()
    assert first._client is not second._client
    before = {
        name: database[name].index_information()
        for name in ("accounts", "pairs", "saves")
    }
    ensure_indexes(database)
    ensure_indexes(database)
    assert before == {name: database[name].index_information() for name in before}
    expected = {
        "accounts": {
            "accounts_recovery_unique": ([("recovery_digest", 1)], True),
            "accounts_session_unique": ([("sessions.token_digest", 1)], True),
        },
        "pairs": {
            "pairs_invite_unique": ([("invite_digest", 1)], True),
            "pairs_member_a": ([("member_a", 1)], False),
            "pairs_member_b": ([("member_b", 1)], False),
        },
        "saves": {
            "saves_pair_script_unique": ([("pair_id", 1), ("script_id", 1)], True),
            "saves_pair_updated": ([("pair_id", 1), ("updated_at", -1)], False),
        },
    }
    for collection, indexes in expected.items():
        assert set(before[collection]) == {"_id_", *indexes}
        for name, (keys, unique) in indexes.items():
            assert before[collection][name]["key"] == keys
            assert before[collection][name].get("unique", False) == unique
            assert "expireAfterSeconds" not in before[collection][name]
    assert before["accounts"]["accounts_session_unique"]["partialFilterExpression"] == {
        "sessions.token_digest": {"$type": "string"}
    }


def test_conflicting_index_fails_without_deleting_it(mongo_database):
    from twoworlds.storage.mongo import MongoRepository

    database, uri = mongo_database
    database.accounts.create_index("recovery_digest", name="accounts_recovery_unique")
    with pytest.raises(RepositoryError):
        MongoRepository(uri, database.name)
    assert not database.accounts.index_information()["accounts_recovery_unique"].get(
        "unique", False
    )


def test_real_unique_indexes_and_account_cas_rollback(
    world, mongo_database, account_factory, now
):
    database, _ = mongo_database
    a, b = world.get_account("account_a"), world.get_account("account_b")
    raw = database.accounts.find_one({"_id": a.id})
    with pytest.raises(DuplicateKeyError):
        database.accounts.insert_one(raw | {"_id": "raw_duplicate"})
    candidate = a.model_copy(
        update={"version": 1, "sessions": b.sessions, "display_name": "不可写入"}
    )
    with pytest.raises(DuplicateRecord):
        world.compare_and_swap_account(a.id, 0, candidate)
    assert world.get_account(a.id) == a
    assert world.get_account_by_session_digest(a.sessions[0].token_digest, now) == a
    assert world.get_account_by_session_digest(b.sessions[0].token_digest, now) == b
    pair = database.pairs.find_one({"_id": "pair_one"})
    with pytest.raises(DuplicateKeyError):
        database.pairs.insert_one(pair | {"_id": "pair_duplicate"})
    save = database.saves.find_one({"_id": "save_one"})
    with pytest.raises(DuplicateKeyError):
        database.saves.insert_one(save | {"_id": "save_duplicate"})


def test_empty_sessions_and_duplicate_internal_sessions(
    repository_factory, account_factory
):
    repo = repository_factory()
    for role in ("a", "b"):
        empty = account_factory(role).model_copy(update={"sessions": ()})
        assert repo.create_account(empty) == empty
    c = account_factory("c")
    with pytest.raises(InvalidRepositoryTransition):
        repo.create_account(
            c.model_copy(update={"sessions": (*c.sessions, *c.sessions)})
        )
    assert repo.get_account(c.id) is None


@pytest.mark.parametrize(
    "collection,key",
    [("accounts", "account_a"), ("pairs", "pair_one"), ("saves", "save_one")],
)
def test_unknown_fields_are_not_silently_discarded(
    world, mongo_database, collection, key
):
    database, _ = mongo_database
    database[collection].update_one({"_id": key}, {"$set": {"unexpected": "hidden"}})
    getter = {
        "accounts": world.get_account,
        "pairs": world.get_pair,
        "saves": world.get_save,
    }[collection]
    with pytest.raises(CorruptRecord):
        getter(key)


@pytest.mark.parametrize(
    "change", ["id_alias", "bson_date", "nan", "oversize", "nested_extra"]
)
def test_corrupt_native_documents_are_rejected(world, mongo_database, now, change):
    database, _ = mongo_database
    changes = {
        "id_alias": {"id": "account_a"},
        "bson_date": {"updated_at": now},
        "nan": {"version": float("nan")},
        "oversize": {"display_name": "中" * 400000},
        "nested_extra": {"sessions.0.secret": "unknown"},
    }
    database.accounts.update_one({"_id": "account_a"}, {"$set": changes[change]})
    with pytest.raises(CorruptRecord):
        world.get_account("account_a")


def test_microseconds_utc_and_chinese_roundtrip(
    repository_factory,
    account_factory,
    mongo_database,
    save_record,
    pair_record,
    advance,
    now,
):
    repo = repository_factory()
    database, _ = mongo_database
    precise = now.replace(microsecond=123456)
    a = account_factory().model_copy(
        update={
            "created_at": precise,
            "updated_at": precise,
            "sessions": (
                account_factory()
                .sessions[0]
                .model_copy(
                    update={
                        "created_at": precise,
                        "expires_at": precise + timedelta(days=1),
                    }
                ),
            ),
        }
    )
    repo.create_account(a)
    repo.create_account(account_factory("b"))
    assert repo.get_account(a.id) == a
    raw = database.accounts.find_one({"_id": a.id})
    assert raw["updated_at"] == "2026-11-11T12:00:00.123456Z"
    assert raw["sessions"][0]["created_at"].endswith(".123456Z")
    repo.create_pair(pair_record)
    repo.join_pair(pair_record.id, "account_b", pair_record.invite_digest, now)
    repo.create_save(save_record)
    advanced = advance(save_record)
    candidate = advanced.model_copy(
        update={
            "updated_at": precise,
            "dialogues": (
                advanced.dialogues[0].model_copy(update={"created_at": precise}),
            ),
            "receipts": (
                advanced.receipts[0].model_copy(update={"created_at": precise}),
            ),
        }
    )
    assert repo.compare_and_swap_save(candidate.id, 0, candidate)
    assert repo.get_save(candidate.id) == candidate
    doc = database.saves.find_one({"_id": candidate.id})
    assert "第1步" in doc["dialogues"][0]["question"]
    assert doc["dialogues"][0]["created_at"].endswith(".123456Z")
    assert doc["receipts"][0]["created_at"].endswith(".123456Z")
    assert doc["receipts"][0]["request_id"] == str(candidate.receipts[0].request_id)
    # Fixed-width UTC strings sort in true time order across second boundaries.
    later = precise.replace(microsecond=0) + timedelta(seconds=1)
    second = a.model_copy(update={"version": 1, "updated_at": later})
    assert repo.compare_and_swap_account(a.id, 0, second)
    assert raw["updated_at"] < database.accounts.find_one({"_id": a.id})["updated_at"]


def test_save_server_rejection_changes_no_aggregate_field(
    world, mongo_database, save_record, advance
):
    database, _ = mongo_database
    database.command(
        "collMod", "saves", validator={"version": {"$eq": 0}}, validationLevel="strict"
    )
    candidate = advance(save_record)
    with pytest.raises(RepositoryError):
        world.compare_and_swap_save(candidate.id, 0, candidate)
    assert world.get_save(save_record.id) == save_record
    assert (
        world.get_receipt(candidate.id, "account_a", candidate.receipts[0].request_id)
        is None
    )


def test_close_is_idempotent_and_blocks_operations(repository_factory):
    repo = repository_factory()
    repo.close()
    repo.close()
    with pytest.raises(RepositoryError):
        repo.get_account("missing")
    with pytest.raises(RepositoryError):
        repo.get_receipt("missing", "account_a", uuid4())


def test_unreachable_mongo_fails_initialization_without_leaking_credentials():
    from twoworlds.storage.mongo import MongoRepository

    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        # Bound but not listening: this known-unused port cannot become a Mongo server.
        uri = f"mongodb://probe-user:do-not-log@127.0.0.1:{reserved.getsockname()[1]}/?directConnection=true"
        with pytest.raises(RepositoryError) as caught:
            MongoRepository(uri, "twoworlds_test_t052_unreachable")
    assert "do-not-log" not in str(caught.value)
    assert uri not in str(caught.value)


@pytest.fixture
def outage_mongo():
    """Own ephemeral server: never stop the shared/user MongoDB instance."""
    name = "twoworlds-t052-outage-" + uuid4().hex
    image = os.environ.get(
        "TWOWORLDS_TEST_MONGO_IMAGE", "mongodb/mongodb-atlas-local:8.0"
    )

    def docker(*args):
        return subprocess.run(
            ["docker", *args], check=True, capture_output=True, text=True
        )

    identifier = docker(
        "run",
        "-d",
        "--pull",
        "never",
        "--name",
        name,
        "--label",
        "com.twoworlds.test=T05.2-outage",
        "--publish",
        "127.0.0.1::27017",
        "--tmpfs",
        "/data/db:mode=1777",
        "--no-healthcheck",
        "--entrypoint",
        "mongod",
        image,
        "--bind_ip_all",
        "--dbpath",
        "/data/db",
    ).stdout.strip()
    client = None
    try:
        state = json.loads(docker("inspect", name).stdout)[0]
        port = state["NetworkSettings"]["Ports"]["27017/tcp"][0]["HostPort"]
        uri = f"mongodb://127.0.0.1:{port}/?directConnection=true"
        client = MongoClient(uri, serverSelectionTimeoutMS=1000)
        for attempt in range(20):
            try:
                client.admin.command("ping")
                break
            except ConnectionFailure:
                if attempt == 19:
                    raise
                time.sleep(0.2)

        def stop():
            owned = json.loads(docker("inspect", name).stdout)[0]
            assert owned["Id"] == identifier
            assert owned["Config"]["Labels"]["com.twoworlds.test"] == "T05.2-outage"
            docker("stop", "--timeout", "10", name)

        yield uri, stop
    finally:
        if client is not None:
            client.close()
        owned = json.loads(docker("inspect", name).stdout)[0]
        assert owned["Id"] == identifier
        assert owned["Config"]["Labels"]["com.twoworlds.test"] == "T05.2-outage"
        docker("rm", "--force", "--volumes", name)


def test_real_disconnect_never_returns_missing_conflict_or_success(
    outage_mongo, account_factory
):
    from twoworlds.storage.mongo import MongoRepository

    uri, stop = outage_mongo
    repo = MongoRepository(uri, "twoworlds_test_t052_" + uuid4().hex)
    account = repo.create_account(account_factory())
    stop()
    try:
        with pytest.raises(RepositoryError):
            repo.get_account(account.id)
        with pytest.raises(RepositoryError):
            repo.compare_and_swap_account(
                account.id, 0, account.model_copy(update={"version": 1})
            )
    finally:
        repo.close()
