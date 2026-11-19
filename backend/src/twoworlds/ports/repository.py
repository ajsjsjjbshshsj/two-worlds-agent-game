"""Repository port: persistence operations, not HTTP or game-rule logic."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from twoworlds.domain.persistence import (
    AccountRecord,
    CommandReceipt,
    Digest,
    PairRecord,
    RateLimitRecord,
    SaveRecord,
    VerificationCodeRecord,
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
    """Adapters provide atomic writes. Callers supply authorization and rule decisions."""

    def create_account(self, account: AccountRecord) -> AccountRecord: ...
    def get_account(self, account_id: str) -> AccountRecord | None: ...
    def get_account_by_email(self, email: str) -> AccountRecord | None: ...
    def get_account_by_session_digest(
        self, digest: Digest, now: datetime
    ) -> AccountRecord | None: ...
    def compare_and_swap_account(
        self, account_id: str, expected_version: int, candidate: AccountRecord
    ) -> bool: ...

    def create_verification_code(
        self, code: VerificationCodeRecord
    ) -> VerificationCodeRecord:
        """Store one live code per (email, purpose); a duplicate id is rejected."""
        ...

    def get_verification_code(self, code_id: str) -> VerificationCodeRecord | None: ...
    def compare_and_swap_verification_code(
        self, code_id: str, expected_version: int, candidate: VerificationCodeRecord
    ) -> bool:
        """Atomically advance attempts/consumption/resend by one version."""
        ...

    def delete_expired_verification_codes(self, now: datetime) -> int: ...

    def create_rate_limit(self, record: RateLimitRecord) -> RateLimitRecord: ...
    def get_rate_limit(self, rate_id: str) -> RateLimitRecord | None: ...
    def compare_and_swap_rate_limit(
        self, rate_id: str, expected_version: int, candidate: RateLimitRecord
    ) -> bool:
        """Atomically increment or reset one shared fixed-window counter."""
        ...

    def delete_expired_rate_limits(self, now: datetime) -> int: ...
    def count_rate_limits(self) -> int: ...

    def create_pair(self, pair: PairRecord) -> PairRecord: ...
    def get_pair(self, pair_id: str) -> PairRecord | None: ...
    def list_pairs_for_member(self, member_id: str) -> tuple[PairRecord, ...]:
        """Return only this member's pairs, ordered by id ascending."""
        ...

    def get_pair_by_invite_digest(self, digest: Digest) -> PairRecord | None: ...
    def join_pair(
        self, pair_id: str, member_id: str, invite_digest: Digest, now: datetime
    ) -> PairRecord | None:
        """Atomically claim an empty B slot with a matching, unexpired invite."""
        ...

    def compare_and_swap_pair(
        self, pair_id: str, expected_version: int, candidate: PairRecord
    ) -> bool: ...

    def create_save(self, save: SaveRecord) -> SaveRecord:
        """Create once per (pair_id, script_id), or return the existing save."""
        ...

    def get_save(self, save_id: str) -> SaveRecord | None: ...
    def list_saves_for_pair(self, pair_id: str) -> tuple[SaveRecord, ...]:
        """Return this pair's fully validated saves, ordered by id ascending."""
        ...

    def get_save_for_pair_script(
        self, pair_id: str, script_id: str
    ) -> SaveRecord | None: ...
    def get_receipt(
        self, save_id: str, actor_id: str, request_id: UUID
    ) -> CommandReceipt | None:
        """Look up a receipt scoped to one save and actor."""
        ...

    def compare_and_swap_save(
        self, save_id: str, expected_version: int, candidate: SaveRecord
    ) -> bool:
        """Commit the aggregate and one appended receipt in a single write.

        The candidate keeps the save identity and pinned script, advances the
        version by one, and preserves prior receipts. A stale version returns
        False. An invalid candidate or exhausted receipt capacity raises the
        corresponding repository error.
        """
        ...

    def close(self) -> None: ...
