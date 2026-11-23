"""Synchronous Mongo aggregates with single-document conditional replacement."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from uuid import UUID

from bson.errors import BSONError
from pydantic import TypeAdapter
from pymongo import MongoClient, timeout
from pymongo.errors import DuplicateKeyError, PyMongoError

from twoworlds.domain.persistence import (
    AccountRecord,
    CommandReceipt,
    Digest,
    NarrativeBudgetRecord,
    PairRecord,
    RateLimitRecord,
    SaveRecord,
    UTCDateTime,
    VerificationCodeRecord,
)
from twoworlds.ports.repository import (
    CorruptRecord,
    DuplicateRecord,
    InvalidRepositoryTransition,
    MissingRecord,
    ReceiptLimitReached,
    RepositoryError,
)

from .indexes import ensure_indexes
from .serialization import SerializationError, dumps, loads

_TIME = TypeAdapter(UTCDateTime)


def _time(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _values(value):
    # ISO UTC strings retain all six microsecond digits; native BSON dates do not.
    if isinstance(value, datetime):
        return _time(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _values(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_values(item) for item in value]
    return value


def _document(record):
    result = _values(record.model_dump(mode="python", warnings=False))
    result["_id"] = result.pop("id")
    # Keep pre-consent account documents canonical and compatible.
    if isinstance(record, AccountRecord) and record.narrative_consent is None:
        result.pop("narrative_consent")
    return result


def _candidate(value, model):
    if not isinstance(value, model):
        raise InvalidRepositoryTransition("Invalid candidate record")
    try:
        record = loads(dumps(value), model)
        # Also enforce the strict JSON budget after fixed-width time encoding.
        raw = _values(record.model_dump(mode="python", warnings=False))
        loads(json.dumps(raw, ensure_ascii=False, allow_nan=False), model)
        return record
    except (SerializationError, ValueError, TypeError, RecursionError):
        raise InvalidRepositoryTransition("Invalid candidate record") from None


def _decode(document, model):
    if document is None:
        return None
    try:
        raw = dict(document)
        if "id" in raw:
            raise ValueError("Conflicting id alias")
        raw["id"] = raw.pop("_id")
        record = loads(json.dumps(raw, ensure_ascii=False, allow_nan=False), model)
        if _document(record) != document:
            raise ValueError("Noncanonical record")
        return record
    except (SerializationError, ValueError, TypeError, KeyError, RecursionError):
        raise CorruptRecord("Stored document failed validation") from None


def _key(value):
    if type(value) is not str:
        raise InvalidRepositoryTransition("Lookup keys must be strings")
    return value


def _expected(value):
    if type(value) is not int or value < 0:
        raise InvalidRepositoryTransition(
            "Expected version must be a nonnegative integer"
        )


def _now(value):
    try:
        return _TIME.validate_python(value)
    except (ValueError, TypeError):
        raise InvalidRepositoryTransition("Invalid timestamp") from None


def _transition(current, candidate, immutable):
    if candidate.version != current.version + 1:
        raise InvalidRepositoryTransition("Candidate must advance exactly one version")
    if any(getattr(current, key) != getattr(candidate, key) for key in immutable):
        raise InvalidRepositoryTransition("Record identity cannot change")
    if candidate.updated_at < current.updated_at:
        raise InvalidRepositoryTransition("Record time cannot move backwards")


class MongoRepository:
    """Explicit URI/database; no fallback, global lock, or multi-document transaction."""

    def __init__(self, uri: str, database_name: str):
        self._closed = False
        self._client = None
        try:
            with self._operation():
                if (
                    type(uri) is not str
                    or not uri
                    or type(database_name) is not str
                    or not database_name
                ):
                    raise RepositoryError(
                        "Explicit Mongo connection and database are required"
                    )
                self._client = MongoClient(
                    uri,
                    serverSelectionTimeoutMS=2000,
                    connectTimeoutMS=2000,
                    socketTimeoutMS=3000,
                    timeoutMS=5000,
                    retryWrites=False,
                    w=1,
                    journal=True,
                )
                self._client.admin.command("ping")
                self._database = self._client[database_name]
                ensure_indexes(self._database)
        except BaseException:
            self.close()
            raise

    @contextmanager
    def _operation(self):
        if self._closed:
            raise RepositoryError("Repository is closed")
        try:
            yield
        except DuplicateKeyError:
            raise DuplicateRecord("A unique record already exists") from None
        except (PyMongoError, BSONError):
            raise RepositoryError("MongoDB operation failed") from None

    def _read(self, collection, query, model):
        return _decode(self._database[collection].find_one(query), model)

    def _replace(self, collection, identifier, expected, candidate):
        result = self._database[collection].replace_one(
            {"_id": identifier, "version": expected}, _document(candidate)
        )
        return result.matched_count == 1

    def create_account(self, account: AccountRecord) -> AccountRecord:
        with self._operation():
            account = _candidate(account, AccountRecord)
            self._database.accounts.insert_one(_document(account))
            return account

    def get_account(self, account_id: str) -> AccountRecord | None:
        with self._operation():
            return self._read("accounts", {"_id": _key(account_id)}, AccountRecord)

    def get_account_by_email(self, email: str) -> AccountRecord | None:
        with self._operation():
            return self._read("accounts", {"email": _key(email)}, AccountRecord)

    def get_account_by_session_digest(
        self, digest: Digest, now: datetime
    ) -> AccountRecord | None:
        with self._operation():
            now = _now(now)
            account = self._read(
                "accounts", {"sessions.token_digest": _key(digest)}, AccountRecord
            )
            if account and any(
                item.token_digest == digest and item.created_at <= now < item.expires_at
                for item in account.sessions
            ):
                return account
            return None

    def compare_and_swap_account(
        self, account_id: str, expected_version: int, candidate: AccountRecord
    ) -> bool:
        with self._operation():
            _expected(expected_version)
            current = self.get_account(account_id)
            if current is None or current.version != expected_version:
                return False
            candidate = _candidate(candidate, AccountRecord)
            _transition(current, candidate, ("id", "email", "created_at"))
            return self._replace("accounts", account_id, expected_version, candidate)

    def get_narrative_budget(self, day_id: str) -> NarrativeBudgetRecord | None:
        with self._operation():
            return self._read(
                "narrative_budgets", {"_id": _key(day_id)}, NarrativeBudgetRecord
            )

    def compare_and_swap_narrative_budget(
        self, candidate: NarrativeBudgetRecord, expected: int | None
    ) -> bool:
        candidate = _candidate(candidate, NarrativeBudgetRecord)
        if expected is not None:
            _expected(expected)
        if candidate.version != (0 if expected is None else expected + 1):
            raise InvalidRepositoryTransition("Invalid narrative budget version")
        try:
            with self._operation():
                if expected is None:
                    self._database.narrative_budgets.insert_one(_document(candidate))
                    return True
                return self._replace(
                    "narrative_budgets", candidate.id, expected, candidate
                )
        except DuplicateRecord:
            return False

    def create_verification_code(
        self, record: VerificationCodeRecord
    ) -> VerificationCodeRecord:
        with self._operation():
            record = _candidate(record, VerificationCodeRecord)
            self._database.verification_codes.insert_one(_document(record))
            return record

    def get_verification_code(self, code_id: str) -> VerificationCodeRecord | None:
        with self._operation():
            return self._read(
                "verification_codes", {"_id": _key(code_id)}, VerificationCodeRecord
            )

    def compare_and_swap_verification_code(
        self, code_id: str, expected_version: int, candidate: VerificationCodeRecord
    ) -> bool:
        with self._operation():
            _expected(expected_version)
            current = self.get_verification_code(code_id)
            if current is None or current.version != expected_version:
                return False
            candidate = _candidate(candidate, VerificationCodeRecord)
            _transition(current, candidate, ("id", "email", "purpose"))
            return self._replace(
                "verification_codes", code_id, expected_version, candidate
            )

    def delete_expired_verification_codes(self, now: datetime) -> int:
        with self._operation():
            now = _now(now)
            # Fixed-width ISO UTC strings compare chronologically as text.
            result = self._database.verification_codes.delete_many(
                {"expires_at": {"$lte": _time(now)}}
            )
            return result.deleted_count

    def create_rate_limit(self, record: RateLimitRecord) -> RateLimitRecord:
        with self._operation():
            record = _candidate(record, RateLimitRecord)
            self._database.rate_limits.insert_one(_document(record))
            return record

    def get_rate_limit(self, rate_id: str) -> RateLimitRecord | None:
        with self._operation():
            return self._read("rate_limits", {"_id": _key(rate_id)}, RateLimitRecord)

    def compare_and_swap_rate_limit(
        self, rate_id: str, expected_version: int, candidate: RateLimitRecord
    ) -> bool:
        with self._operation():
            _expected(expected_version)
            current = self.get_rate_limit(rate_id)
            if current is None or current.version != expected_version:
                return False
            candidate = _candidate(candidate, RateLimitRecord)
            _transition(current, candidate, ("id",))
            return self._replace("rate_limits", rate_id, expected_version, candidate)

    def delete_expired_rate_limits(self, now: datetime) -> int:
        with self._operation():
            now = _now(now)
            result = self._database.rate_limits.delete_many(
                {"expires_at": {"$lte": _time(now)}}
            )
            return result.deleted_count

    def count_rate_limits(self) -> int:
        with self._operation():
            return self._database.rate_limits.count_documents({})

    def create_pair(self, pair: PairRecord) -> PairRecord:
        with self._operation():
            pair = _candidate(pair, PairRecord)
            if pair.member_b is not None:
                raise InvalidRepositoryTransition(
                    "A new pair must have an empty B slot"
                )
            if self.get_account(pair.member_a) is None:
                raise MissingRecord("Parent account is missing")
            self._database.pairs.insert_one(_document(pair))
            return pair

    def get_pair(self, pair_id: str) -> PairRecord | None:
        with self._operation():
            return self._read("pairs", {"_id": _key(pair_id)}, PairRecord)

    def list_pairs_for_member(self, member_id: str) -> tuple[PairRecord, ...]:
        with self._operation():
            member_id = _key(member_id)
            return tuple(
                _decode(document, PairRecord)
                for document in self._database.pairs.find(
                    {"$or": [{"member_a": member_id}, {"member_b": member_id}]}
                ).sort("_id", 1)
            )

    def get_pair_by_invite_digest(self, digest: Digest) -> PairRecord | None:
        with self._operation():
            return self._read("pairs", {"invite_digest": _key(digest)}, PairRecord)

    def join_pair(
        self, pair_id: str, member_id: str, invite_digest: Digest, now: datetime
    ) -> PairRecord | None:
        with self._operation():
            member_id, invite_digest = _key(member_id), _key(invite_digest)
            now = _now(now)
            current = self.get_pair(pair_id)
            if (
                current is None
                or current.invite_digest != invite_digest
                or current.member_a == member_id
            ):
                return None
            if current.member_b == member_id:
                return current
            if current.member_b is not None or now >= current.invite_expires_at:
                return None
            if now < current.updated_at:
                raise InvalidRepositoryTransition("Join time precedes pair update")
            if self.get_account(member_id) is None:
                raise MissingRecord("Joining account is missing")
            candidate = _candidate(
                current.model_copy(
                    update={
                        "member_b": member_id,
                        "version": current.version + 1,
                        "updated_at": now,
                    }
                ),
                PairRecord,
            )
            result = self._database.pairs.replace_one(
                {
                    "_id": pair_id,
                    "version": current.version,
                    "member_b": None,
                    "member_a": {"$ne": member_id},
                    "invite_digest": invite_digest,
                    "invite_expires_at": {"$gt": _time(now)},
                },
                _document(candidate),
            )
            if result.matched_count == 1:
                return candidate
            latest = self.get_pair(pair_id)
            return (
                latest
                if latest
                and latest.member_b == member_id
                and latest.invite_digest == invite_digest
                else None
            )

    def compare_and_swap_pair(
        self, pair_id: str, expected_version: int, candidate: PairRecord
    ) -> bool:
        with self._operation():
            _expected(expected_version)
            current = self.get_pair(pair_id)
            if current is None or current.version != expected_version:
                return False
            candidate = _candidate(candidate, PairRecord)
            _transition(
                current, candidate, ("id", "member_a", "member_b", "created_at")
            )
            if current.member_b is not None and (
                candidate.invite_digest != current.invite_digest
                or candidate.invite_expires_at != current.invite_expires_at
            ):
                raise InvalidRepositoryTransition(
                    "A filled pair cannot change membership or invite"
                )
            return self._replace("pairs", pair_id, expected_version, candidate)

    def create_save(self, save: SaveRecord) -> SaveRecord:
        with self._operation():
            save = _candidate(save, SaveRecord)
            if self.get_pair(save.pair_id) is None:
                raise MissingRecord("Parent pair is missing")
            current = self.get_save_for_pair_script(save.pair_id, save.script_id)
            if current is not None:
                return current
            try:
                self._database.saves.insert_one(_document(save))
            except DuplicateKeyError:
                # Another client may have won the unique pair/story insert.
                current = self.get_save_for_pair_script(save.pair_id, save.script_id)
                if current is not None:
                    return current
                raise
            return save

    def get_save(self, save_id: str) -> SaveRecord | None:
        with self._operation():
            return self._read("saves", {"_id": _key(save_id)}, SaveRecord)

    def list_saves_for_pair(self, pair_id: str) -> tuple[SaveRecord, ...]:
        with self._operation():
            return tuple(
                _decode(document, SaveRecord)
                for document in self._database.saves.find(
                    {"pair_id": _key(pair_id)}
                ).sort("_id", 1)
            )

    def get_save_for_pair_script(
        self, pair_id: str, script_id: str
    ) -> SaveRecord | None:
        with self._operation():
            return self._read(
                "saves",
                {"pair_id": _key(pair_id), "script_id": _key(script_id)},
                SaveRecord,
            )

    def get_receipt(
        self, save_id: str, actor_id: str, request_id: UUID
    ) -> CommandReceipt | None:
        with self._operation():
            save = self.get_save(save_id)
            if save is None:
                return None
            return next(
                (
                    item
                    for item in save.receipts
                    if item.actor_id == actor_id and item.request_id == request_id
                ),
                None,
            )

    def compare_and_swap_save(
        self, save_id: str, expected_version: int, candidate: SaveRecord
    ) -> bool:
        with self._operation():
            _expected(expected_version)
            current = self.get_save(save_id)
            if current is None or current.version != expected_version:
                return False
            if current.version == 512:
                raise ReceiptLimitReached("Save command capacity reached")
            candidate = _candidate(candidate, SaveRecord)
            _transition(
                current,
                candidate,
                ("id", "pair_id", "script_id", "script_version", "created_at"),
            )
            if (
                len(candidate.receipts) != len(current.receipts) + 1
                or candidate.receipts[:-1] != current.receipts
                or candidate.receipts[-1].accepted_version != candidate.version
            ):
                raise InvalidRepositoryTransition(
                    "Candidate must preserve receipts and append exactly one"
                )
            return self._replace("saves", save_id, expected_version, candidate)

    def check_health(self) -> None:
        with self._operation(), timeout(1):
            self._database.command("ping")

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._client is not None:
                try:
                    self._client.close()
                except PyMongoError:
                    raise RepositoryError("MongoDB close failed") from None
