"""Repository port: persistence operations, not HTTP or game-rule logic."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from twoworlds.domain.persistence import (
    AccountRecord, CommandReceipt, Digest, PairRecord, SaveRecord,
)


class RepositoryError(RuntimeError):
    """Base class for safe, adapter-independent persistence failures."""


class DuplicateRecord(RepositoryError):
    """A unique identifier or digest is already owned by another record."""


class MissingRecord(RepositoryError):
    """A required parent record does not exist."""


class CorruptRecord(RepositoryError):
    """Stored JSON cannot be decoded into its declared immutable model."""


class InvalidRepositoryTransition(RepositoryError):
    """A candidate violates the repository's version/append-only contract."""


class ReceiptLimitReached(RepositoryError):
    """The save has reached its explicit 512-receipt limit."""


class Repository(Protocol):
    def create_account(self, account: AccountRecord) -> AccountRecord: ...
    def get_account(self, account_id: str) -> AccountRecord | None: ...
    def get_account_by_recovery_digest(self, digest: Digest) -> AccountRecord | None: ...
    def get_account_by_session_digest(self, digest: Digest, now: datetime) -> AccountRecord | None: ...
    def compare_and_swap_account(self, account_id: str, expected_version: int, candidate: AccountRecord) -> bool: ...

    def create_pair(self, pair: PairRecord) -> PairRecord: ...
    def get_pair(self, pair_id: str) -> PairRecord | None: ...
    def get_pair_by_invite_digest(self, digest: Digest) -> PairRecord | None: ...
    def join_pair(self, pair_id: str, member_id: str, invite_digest: Digest, now: datetime) -> PairRecord | None: ...
    def compare_and_swap_pair(self, pair_id: str, expected_version: int, candidate: PairRecord) -> bool: ...

    def create_save(self, save: SaveRecord) -> SaveRecord: ...
    def get_save(self, save_id: str) -> SaveRecord | None: ...
    def get_save_for_pair_script(self, pair_id: str, script_id: str) -> SaveRecord | None: ...
    def get_receipt(self, save_id: str, actor_id: str, request_id: UUID) -> CommandReceipt | None: ...
    def compare_and_swap_save(self, save_id: str, expected_version: int, candidate: SaveRecord) -> bool: ...

    def close(self) -> None: ...
