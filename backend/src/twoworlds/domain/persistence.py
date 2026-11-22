"""Immutable persistence aggregates shared by repository adapters."""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from twoworlds.content.schema import ContentModel, Identifier, Role, Text, Version
from twoworlds.domain.models import GameState
from twoworlds.domain.recap import PublicHistory

Digest = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
DisplayName = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)
]
# Normalized before the pattern runs: trimmed, lowercased, bounded to 254 chars.
Email = Annotated[
    StrictStr,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=254,
        # Pydantic checks the pattern before to_lower, so accept both cases here.
        pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$",
    ),
]
# Argon2id encoded hash; never a plaintext password. repr stays off at field level.
PasswordHash = Annotated[StrictStr, StringConstraints(min_length=20, max_length=512)]
Question = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]


def _utc(value: object) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise ValueError("timestamp must be an ISO datetime or datetime object")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    try:
        return value.astimezone(timezone.utc)
    except OverflowError:
        raise ValueError("timestamp is outside the UTC range") from None


UTCDateTime = Annotated[datetime, BeforeValidator(_utc)]


class _Record(ContentModel):
    model_config = ConfigDict(revalidate_instances="always")


class SessionRecord(_Record):
    token_digest: Digest
    created_at: UTCDateTime
    expires_at: UTCDateTime

    @model_validator(mode="after")
    def check_expiry(self):
        if self.expires_at <= self.created_at:
            raise ValueError("session expiry must be after creation")
        return self


class AccountRecord(_Record):
    id: Identifier
    email: Email
    email_verified_at: UTCDateTime
    password_hash: PasswordHash = Field(repr=False)
    display_name: DisplayName
    sessions: Annotated[tuple[SessionRecord, ...], Field(max_length=5)] = ()
    narrative_consent: Digest | None = None
    version: Annotated[StrictInt, Field(ge=0)] = 0
    created_at: UTCDateTime
    updated_at: UTCDateTime

    @model_validator(mode="after")
    def check_account(self):
        if self.updated_at < self.created_at:
            raise ValueError("account updated_at precedes created_at")
        if self.email_verified_at < self.created_at:
            raise ValueError("email verified before account creation")
        digests = [item.token_digest for item in self.sessions]
        if len(digests) != len(set(digests)):
            raise ValueError("duplicate session digest")
        return self


BudgetMicros = Annotated[StrictInt, Field(ge=0, le=10**13)]


class NarrativeReservation(_Record):
    id: UUID
    price_version: Identifier
    reserved_micros: Annotated[BudgetMicros, Field(gt=0)]
    charged_micros: BudgetMicros | None = None


class NarrativeBudgetRecord(_Record):
    id: Annotated[
        StrictStr, StringConstraints(pattern=r"^ai_budget_[0-9]{4}_[0-9]{2}_[0-9]{2}$")
    ]
    version: Annotated[StrictInt, Field(ge=0)] = 0
    reservations: Annotated[tuple[NarrativeReservation, ...], Field(max_length=1000)]

    @model_validator(mode="after")
    def check_ids(self):
        if len({item.id for item in self.reservations}) != len(self.reservations):
            raise ValueError("duplicate budget reservation")
        return self

    @property
    def committed_micros(self):
        return sum(
            item.reserved_micros if item.charged_micros is None else item.charged_micros
            for item in self.reservations
        )


class VerificationCodeRecord(_Record):
    """One live code per (email, purpose); resend replaces it and invalidates the old."""

    id: Identifier
    email: Email
    purpose: Literal["register", "reset"]
    # Per-issuance identity: a delivery failure may only invalidate its own issue.
    issue_id: Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
    digest: Digest
    created_at: UTCDateTime
    expires_at: UTCDateTime
    attempts: Annotated[StrictInt, Field(ge=0, le=5)] = 0
    consumed_at: UTCDateTime | None = None
    version: Annotated[StrictInt, Field(ge=0)] = 0
    updated_at: UTCDateTime

    @model_validator(mode="after")
    def check_code(self):
        if self.expires_at <= self.created_at:
            raise ValueError("code expiry must be after creation")
        if self.updated_at < self.created_at:
            raise ValueError("code updated_at precedes created_at")
        if self.consumed_at is not None and self.consumed_at < self.created_at:
            raise ValueError("code consumed before creation")
        return self


class RateLimitRecord(_Record):
    """Shared fixed-window counter; the id is a desensitized digest, never raw email/IP."""

    id: Identifier
    count: Annotated[StrictInt, Field(ge=0)]
    window_start: UTCDateTime
    expires_at: UTCDateTime
    version: Annotated[StrictInt, Field(ge=0)] = 0
    updated_at: UTCDateTime

    @model_validator(mode="after")
    def check_window(self):
        if self.expires_at <= self.window_start:
            raise ValueError("rate window expiry must be after its start")
        if self.updated_at < self.window_start:
            raise ValueError("rate updated_at precedes window start")
        return self


class PairRecord(_Record):
    id: Identifier
    member_a: Identifier
    member_b: Identifier | None = None
    invite_digest: Digest
    invite_expires_at: UTCDateTime
    version: Annotated[StrictInt, Field(ge=0)] = 0
    created_at: UTCDateTime
    updated_at: UTCDateTime

    @model_validator(mode="after")
    def check_pair(self):
        if self.member_b == self.member_a:
            raise ValueError("a member cannot join their own pair")
        if self.updated_at < self.created_at:
            raise ValueError("pair updated_at precedes created_at")
        if self.invite_expires_at <= self.created_at:
            raise ValueError("invite expiry must be after pair creation")
        return self


class DialogueTurn(_Record):
    role: Role
    question: Question
    answer: Text
    mode: Literal["demo", "provider", "fallback"]
    created_at: UTCDateTime


class CommandReceipt(_Record):
    actor_id: Identifier
    request_id: UUID
    fingerprint: Digest
    accepted_version: Annotated[StrictInt, Field(gt=0)]
    created_at: UTCDateTime


class SaveRecord(_Record):
    """One room/story aggregate; state, public history and receipts move together."""

    id: Identifier
    pair_id: Identifier
    script_id: Identifier
    script_version: Version
    version: Annotated[StrictInt, Field(ge=0, le=512)]
    state: GameState
    public_history: PublicHistory
    dialogues: Annotated[tuple[DialogueTurn, ...], Field(max_length=40)] = ()
    receipts: Annotated[tuple[CommandReceipt, ...], Field(max_length=512)] = ()
    created_at: UTCDateTime
    updated_at: UTCDateTime

    @field_validator("state", "public_history", mode="before")
    @classmethod
    def revalidate_domain_values(cls, value: object) -> object:
        # These domain models do not revalidate instances built with model_copy/construct.
        if isinstance(value, (GameState, PublicHistory)):
            return value.model_dump(mode="python", warnings=False)
        return value

    @model_validator(mode="after")
    def check_aggregate(self):
        if self.updated_at < self.created_at:
            raise ValueError("save updated_at precedes created_at")
        if (self.state.script_id, self.state.script_version, self.state.version) != (
            self.script_id,
            self.script_version,
            self.version,
        ):
            raise ValueError("save and game state identity/version differ")
        if (
            self.public_history.script_id,
            self.public_history.script_version,
            self.public_history.through_version,
        ) != (self.script_id, self.script_version, self.version):
            raise ValueError("save and public history identity/version differ")
        role_counts = {"a": 0, "b": 0}
        for turn in self.dialogues:
            role_counts[turn.role] += 1
        if any(count > 20 for count in role_counts.values()):
            raise ValueError("dialogue history exceeds 20 turns per role")
        receipt_keys = [(item.actor_id, item.request_id) for item in self.receipts]
        receipt_versions = [item.accepted_version for item in self.receipts]
        if len(receipt_keys) != len(set(receipt_keys)):
            raise ValueError("duplicate actor/request receipt")
        # Every accepted command retains its receipt for the lifetime of this save.
        if receipt_versions != list(range(1, self.version + 1)):
            raise ValueError(
                "receipt versions must cover every version from 1 to save.version"
            )
        return self
