"""Immutable persistence aggregates shared by repository adapters."""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictInt, StrictStr, StringConstraints, field_validator, model_validator

from twoworlds.content.schema import ContentModel, Identifier, Role, Version
from twoworlds.domain.models import GameState
from twoworlds.domain.recap import PublicHistory

Digest = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
DisplayName = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Question = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc)


class SessionRecord(ContentModel):
    token_digest: Digest
    created_at: datetime
    expires_at: datetime

    @field_validator("created_at", "expires_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def check_expiry(self):
        if self.expires_at <= self.created_at:
            raise ValueError("session expiry must be after creation")
        return self


class AccountRecord(ContentModel):
    id: Identifier
    display_name: DisplayName
    recovery_digest: Digest
    sessions: Annotated[tuple[SessionRecord, ...], Field(max_length=5)] = ()
    version: Annotated[StrictInt, Field(ge=0)] = 0
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def check_account(self):
        if self.updated_at < self.created_at:
            raise ValueError("account updated_at precedes created_at")
        digests = [item.token_digest for item in self.sessions]
        if len(digests) != len(set(digests)):
            raise ValueError("duplicate session digest")
        return self


class PairRecord(ContentModel):
    id: Identifier
    member_a: Identifier
    member_b: Identifier | None = None
    invite_digest: Digest
    invite_expires_at: datetime
    version: Annotated[StrictInt, Field(ge=0)] = 0
    created_at: datetime
    updated_at: datetime

    @field_validator("invite_expires_at", "created_at", "updated_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def check_pair(self):
        if self.member_b == self.member_a:
            raise ValueError("a member cannot join their own pair")
        if self.updated_at < self.created_at:
            raise ValueError("pair updated_at precedes created_at")
        return self


class DialogueTurn(ContentModel):
    role: Role
    question: Question
    answer: StrictStr
    mode: Literal["demo", "provider"]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)


class CommandReceipt(ContentModel):
    actor_id: Identifier
    request_id: UUID
    fingerprint: Digest
    accepted_version: Annotated[StrictInt, Field(gt=0)]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)


class SaveRecord(ContentModel):
    """One room/story aggregate; state, public history and receipts move together."""

    id: Identifier
    pair_id: Identifier
    script_id: Identifier
    script_version: Version
    version: Annotated[StrictInt, Field(ge=0)]
    state: GameState
    public_history: PublicHistory
    dialogues: Annotated[tuple[DialogueTurn, ...], Field(max_length=40)] = ()
    receipts: Annotated[tuple[CommandReceipt, ...], Field(max_length=512)] = ()
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def check_aggregate(self):
        if self.updated_at < self.created_at:
            raise ValueError("save updated_at precedes created_at")
        if (self.state.script_id, self.state.script_version, self.state.version) != (
            self.script_id, self.script_version, self.version
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
        if (
            len(receipt_versions) != len(set(receipt_versions))
            or receipt_versions != sorted(receipt_versions)
            or any(version > self.version for version in receipt_versions)
        ):
            raise ValueError("receipt versions must be unique and ordered")
        return self
