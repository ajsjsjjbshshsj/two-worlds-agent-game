"""Typed, private state for the opt-in P0 ruleset. No puzzle commands live here."""

from enum import StrEnum
from typing import Annotated, ClassVar, Literal, Self
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    UUID5,
    ValidationError,
    model_validator,
)

from twoworlds.content.schema import (
    ContentModel,
    Identifier,
    PositiveInt,
    Role,
    Version,
)

from .errors import DomainError

Revision = Annotated[StrictInt, Field(ge=0)]
Ordinal = Annotated[StrictInt, Field(ge=0, le=255)]
Beat = Literal["short", "long"]
TideWindow = Literal["early", "middle", "late"]
Bridge = Literal["bridge_1", "bridge_2", "bridge_3"]


def _uuid_input(value: object) -> object:
    if not isinstance(value, (str, UUID)):
        raise ValueError("evidence ID must be a UUID string or UUID")
    return value


EvidenceId = Annotated[UUID5, BeforeValidator(_uuid_input)]


class EvidenceKind(StrEnum):
    CHALLENGE = "challenge"
    REPLY = "reply"
    ECHO_VERIFICATION = "echo_verification"
    TIDE_READING = "tide_reading"
    TIDE_RANGE = "tide_range"
    TIDE_SCAN = "tide_scan"
    TIDE_RESCAN = "tide_rescan"
    TIDE_VERIFICATION = "tide_verification"
    SURVEY_BATCH = "survey_batch"
    TRACK_REFERENCE = "track_reference"
    NEAR_SAMPLE = "near_sample"
    FAR_SAMPLE = "far_sample"
    TRACK_VERIFICATION = "track_verification"
    CLEARANCE = "clearance"
    LOCK = "lock"
    PERMIT = "permit"


class EvidenceContext(ContentModel):
    """Supplied by the server when preparing a candidate Save version."""

    save_id: Identifier
    script_id: Identifier
    script_version: Version
    accepted_version: PositiveInt

    def id_for(self, kind: EvidenceKind, *, ordinal: Ordinal = 0) -> UUID:
        if (
            not isinstance(kind, EvidenceKind)
            or type(ordinal) is not int
            or not 0 <= ordinal <= 255
        ):
            raise ValueError("invalid evidence kind or ordinal")
        name = (
            f"twoworlds:p0:{self.save_id}:{self.script_id}:{self.script_version}:"
            f"{kind.value}:{self.accepted_version}:{ordinal}"
        )
        return uuid5(NAMESPACE_URL, name)


class _PuzzleModel(ContentModel):
    model_config = ConfigDict(revalidate_instances="always")


class Evidence(_PuzzleModel):
    kind: ClassVar[EvidenceKind]
    id: EvidenceId
    accepted_version: PositiveInt
    ordinal: Ordinal = 0
    role: Role

    @property
    def parents(self) -> tuple[UUID, ...]:
        return ()


class Challenge(Evidence):
    kind = EvidenceKind.CHALLENGE
    role: Literal["b"] = "b"
    optics_rev: Revision
    beats: tuple[Beat, Beat]

    @model_validator(mode="after")
    def distinct_beats(self) -> Self:
        if self.beats[0] == self.beats[1]:
            raise ValueError("challenge requires distinct beats")
        return self


class Reply(Evidence):
    kind = EvidenceKind.REPLY
    role: Literal["a"] = "a"
    optics_rev: Revision
    challenge_id: EvidenceId
    beats: tuple[Beat, Beat]

    @property
    def parents(self) -> tuple[UUID, ...]:
        return (self.challenge_id,)


class EchoVerification(Evidence):
    kind = EvidenceKind.ECHO_VERIFICATION
    role: Literal["b"] = "b"
    optics_rev: Revision
    challenge_id: EvidenceId
    reply_id: EvidenceId

    @property
    def parents(self) -> tuple[UUID, ...]:
        return (self.challenge_id, self.reply_id)


class TideReading(Evidence):
    kind = EvidenceKind.TIDE_READING
    role: Literal["a"] = "a"
    record_key: Identifier
    windows: Annotated[tuple[TideWindow, ...], Field(min_length=1, max_length=3)]


class TideRange(Evidence):
    kind = EvidenceKind.TIDE_RANGE
    role: Literal["a"] = "a"
    reading_id: EvidenceId

    @property
    def parents(self) -> tuple[UUID, ...]:
        return (self.reading_id,)


class TideScan(Evidence):
    kind = EvidenceKind.TIDE_SCAN
    role: Literal["b"] = "b"
    tide_config_rev: Revision
    mode: Literal["quick", "outer", "coastal"]
    windows: Annotated[tuple[TideWindow, ...], Field(min_length=1, max_length=3)]


class TideRescan(Evidence):
    kind = EvidenceKind.TIDE_RESCAN
    role: Literal["b"] = "b"
    tide_config_rev: Revision
    scan_id: EvidenceId
    range_id: EvidenceId
    window: TideWindow

    @property
    def parents(self) -> tuple[UUID, ...]:
        return (self.scan_id, self.range_id)


class TideVerification(Evidence):
    kind = EvidenceKind.TIDE_VERIFICATION
    role: Literal["b"] = "b"
    tide_config_rev: Revision
    scan_id: EvidenceId
    range_id: EvidenceId
    rescan_id: EvidenceId

    @property
    def parents(self) -> tuple[UUID, ...]:
        return (self.scan_id, self.range_id, self.rescan_id)


class SurveyBatch(Evidence):
    kind = EvidenceKind.SURVEY_BATCH
    role: Literal["b"] = "b"
    survey_rev: Revision
    reference_id: EvidenceId | None = None


class TrackReference(Evidence):
    kind = EvidenceKind.TRACK_REFERENCE
    role: Literal["a"] = "a"
    survey_rev: Revision
    marker_key: Identifier


class NearSample(Evidence):
    kind = EvidenceKind.NEAR_SAMPLE
    role: Literal["b"] = "b"
    survey_rev: Revision
    batch_id: EvidenceId
    aim: Literal["near_anchor", "near_glare"]
    segments: Annotated[tuple[Bridge, ...], Field(min_length=1, max_length=3)]

    @property
    def parents(self) -> tuple[UUID, ...]:
        return (self.batch_id,)


class FarSample(Evidence):
    kind = EvidenceKind.FAR_SAMPLE
    role: Literal["b"] = "b"
    survey_rev: Revision
    batch_id: EvidenceId
    reference_id: EvidenceId
    aim: Literal["bridge_anchor", "far_edge"]
    segments: Annotated[tuple[Bridge, ...], Field(min_length=1, max_length=3)]

    @property
    def parents(self) -> tuple[UUID, ...]:
        return (self.batch_id, self.reference_id)


class TrackVerification(Evidence):
    kind = EvidenceKind.TRACK_VERIFICATION
    role: Literal["b"] = "b"
    survey_rev: Revision
    batch_id: EvidenceId
    reference_id: EvidenceId
    near_id: EvidenceId
    far_id: EvidenceId
    segment: Bridge

    @property
    def parents(self) -> tuple[UUID, ...]:
        return (self.batch_id, self.reference_id, self.near_id, self.far_id)


class Clearance(Evidence):
    kind = EvidenceKind.CLEARANCE
    role: Literal["a"] = "a"
    track_rev: Revision
    track: Literal["track_2"]


class PlatformLock(Evidence):
    kind = EvidenceKind.LOCK
    role: Literal["a"] = "a"
    track_rev: Revision
    clearance_id: EvidenceId

    @property
    def parents(self) -> tuple[UUID, ...]:
        return (self.clearance_id,)


class ApproachPermit(Evidence):
    kind = EvidenceKind.PERMIT
    role: Literal["b"] = "b"
    track_rev: Revision
    drive_power_rev: Revision
    lock_id: EvidenceId

    @property
    def parents(self) -> tuple[UUID, ...]:
        return (self.lock_id,)


class InvalidatedEvidence(_PuzzleModel):
    kind: EvidenceKind
    id: EvidenceId
    accepted_version: PositiveInt
    ordinal: Ordinal = 0
    reason: Literal["configuration_changed", "replaced", "consumed"]


class Milestone(_PuzzleModel):
    accepted_version: PositiveInt


class TrackPublication(Milestone):
    segment: Literal["bridge_2"]


class PuzzleState(_PuzzleModel):
    evidence_slots: ClassVar[dict[str, type[Evidence]]]
    milestone_fields: ClassVar[tuple[str, ...]]
    history: Annotated[tuple[InvalidatedEvidence, ...], Field(max_length=5)] = ()

    def active_evidence(self) -> tuple[Evidence, ...]:
        return tuple(
            item
            for name in self.evidence_slots
            if (item := getattr(self, name)) is not None
        )

    def records(self) -> tuple[Evidence, ...]:
        return self.active_evidence()

    def milestones(self) -> tuple[Milestone, ...]:
        return tuple(
            item
            for name in self.milestone_fields
            if (item := getattr(self, name)) is not None
        )

    @model_validator(mode="after")
    def check_history(self) -> Self:
        active = self.records()
        allowed_kinds = {record.kind for record in self.evidence_slots.values()}
        keys = {item.kind for item in self.history}
        if len(keys) != len(self.history) or not keys <= allowed_kinds:
            raise ValueError("invalid evidence history")
        ids = [item.id for item in (*active, *self.history)]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence identity")
        current = {item.kind: item.accepted_version for item in self.active_evidence()}
        if any(
            item.kind in current and item.accepted_version >= current[item.kind]
            for item in self.history
        ):
            raise ValueError("historical evidence must precede its replacement")
        return self

    def _invalidate(self, fields: tuple[str, ...], **revisions: int) -> Self:
        latest = {item.kind: item for item in self.history}
        for field in fields:
            item = getattr(self, field)
            if item is not None:
                latest[item.kind] = InvalidatedEvidence(
                    kind=item.kind,
                    id=item.id,
                    accepted_version=item.accepted_version,
                    ordinal=item.ordinal,
                    reason="configuration_changed",
                )
        return type(self).model_validate(
            self.model_dump()
            | dict.fromkeys(fields)
            | {"history": tuple(latest.values())}
            | revisions
        )


def _require_parents(
    child: Evidence | None,
    *parents: Evidence | None,
    same_commit: Evidence | None = None,
) -> None:
    if child is None:
        return
    if any(
        parent is None
        or (
            parent is not same_commit
            and parent.accepted_version >= child.accepted_version
        )
        for parent in parents
    ):
        raise ValueError("missing or newer evidence parent")
    if (
        same_commit is not None
        and same_commit.accepted_version != child.accepted_version
    ):
        raise ValueError("evidence must be committed together")
    if child.parents != tuple(parent.id for parent in parents if parent is not None):
        raise ValueError("mismatched evidence parents")


class EchoState(PuzzleState):
    evidence_slots = {
        "challenge": Challenge,
        "reply": Reply,
        "verification": EchoVerification,
    }
    milestone_fields = ("locked",)

    optics_rev: Revision = 0
    challenge: Challenge | None = None
    reply: Reply | None = None
    verification: EchoVerification | None = None
    locked: Milestone | None = None

    @model_validator(mode="after")
    def check_challenge(self) -> Self:
        if any(item.optics_rev != self.optics_rev for item in self.active_evidence()):
            raise ValueError("stale active optical evidence")
        _require_parents(self.reply, self.challenge)
        _require_parents(self.verification, self.challenge, self.reply)
        if (
            self.challenge
            and self.reply
            and self.reply.beats != self.challenge.beats[::-1]
        ):
            raise ValueError("reply does not reverse the active challenge")
        if self.locked is not None and self.active_evidence():
            raise ValueError("locked signal cannot have an active challenge")
        return self

    def change_optics(self) -> Self:
        return self._invalidate(
            tuple(self.evidence_slots), optics_rev=self.optics_rev + 1
        )


class TideState(PuzzleState):
    evidence_slots = {
        "reading": TideReading,
        "tide_range": TideRange,
        "scan": TideScan,
        "rescan": TideRescan,
        "verification": TideVerification,
    }
    milestone_fields = ("confirmed",)

    tide_config_rev: Revision = 0
    # The submitted reading remains pinned even if A opens another record.
    reading: TideReading | None = None
    submitted_reading: TideReading | None = None
    tide_range: TideRange | None = None
    scan: TideScan | None = None
    rescan: TideRescan | None = None
    verification: TideVerification | None = None
    confirmed: Milestone | None = None

    def records(self) -> tuple[Evidence, ...]:
        records = self.active_evidence()
        if (
            self.submitted_reading is not None
            and self.submitted_reading != self.reading
        ):
            return (*records, self.submitted_reading)
        return records

    @model_validator(mode="after")
    def check_tide_chain(self) -> Self:
        if (self.submitted_reading is None) != (self.tide_range is None):
            raise ValueError("submitted reading and range must be paired")
        _require_parents(self.tide_range, self.submitted_reading)
        _require_parents(self.rescan, self.scan, self.tide_range)
        _require_parents(
            self.verification,
            self.scan,
            self.tide_range,
            self.rescan,
            same_commit=self.rescan,
        )
        if (self.rescan is None) != (self.verification is None):
            raise ValueError("tide rescan and verification must be committed together")
        if self.rescan and self.scan and self.submitted_reading:
            if set(self.scan.windows).intersection(self.submitted_reading.windows) != {
                self.rescan.window
            }:
                raise ValueError("rescan window must match the unique intersection")
        for item in (self.reading, self.submitted_reading, self.scan):
            if item is not None and len(set(item.windows)) != len(item.windows):
                raise ValueError("duplicate tide window")
        scans = tuple(
            item
            for item in (self.scan, self.rescan, self.verification)
            if item is not None
        )
        if any(item.tide_config_rev != self.tide_config_rev for item in scans):
            raise ValueError("stale active tide scan")
        if self.confirmed is not None and scans:
            raise ValueError("confirmed route cannot have active scans")
        return self

    def change_tide_config(self) -> Self:
        return self._invalidate(
            ("scan", "rescan", "verification"), tide_config_rev=self.tide_config_rev + 1
        )


class SurveyState(PuzzleState):
    evidence_slots = {
        "batch": SurveyBatch,
        "reference": TrackReference,
        "near": NearSample,
        "far": FarSample,
        "verification": TrackVerification,
    }
    milestone_fields = ("published", "installed")

    survey_rev: Revision = 0
    batch: SurveyBatch | None = None
    reference: TrackReference | None = None
    near: NearSample | None = None
    far: FarSample | None = None
    verification: TrackVerification | None = None
    published: TrackPublication | None = None
    installed: Milestone | None = None

    @model_validator(mode="after")
    def check_batch(self) -> Self:
        if any(item.survey_rev != self.survey_rev for item in self.active_evidence()):
            raise ValueError("stale active survey evidence")
        if self.batch and self.batch.reference_id != (
            self.reference.id if self.reference else None
        ):
            raise ValueError("batch must reference the current survey marker")
        _require_parents(self.near, self.batch)
        _require_parents(self.far, self.batch, self.reference)
        _require_parents(
            self.verification, self.batch, self.reference, self.near, self.far
        )
        if self.far and (
            self.near is None or self.near.accepted_version >= self.far.accepted_version
        ):
            raise ValueError("far sample requires an earlier near sample")
        if any(
            item and len(set(item.segments)) != len(item.segments)
            for item in (self.near, self.far)
        ):
            raise ValueError("duplicate survey segment")
        if self.verification and self.near and self.far:
            if self.verification.segment != "bridge_2" or set(
                self.near.segments
            ).intersection(self.far.segments) != {self.verification.segment}:
                raise ValueError(
                    "survey verification must match the unique track segment"
                )
        if self.published is not None and self.active_evidence():
            raise ValueError("published location cannot have an active survey")
        if self.installed and (
            self.published is None
            or self.installed.accepted_version <= self.published.accepted_version
        ):
            raise ValueError("installation requires an earlier publication")
        return self

    def change_survey_config(self) -> Self:
        return self._invalidate(
            tuple(self.evidence_slots), survey_rev=self.survey_rev + 1
        )


class ApproachState(PuzzleState):
    evidence_slots = {
        "clearance": Clearance,
        "lock": PlatformLock,
        "permit": ApproachPermit,
    }
    milestone_fields = ("dispatched",)

    track_rev: Revision = 0
    drive_power_rev: Revision = 0
    clearance: Clearance | None = None
    lock: PlatformLock | None = None
    permit: ApproachPermit | None = None
    dispatched: Milestone | None = None

    @model_validator(mode="after")
    def check_approach(self) -> Self:
        if any(item.track_rev != self.track_rev for item in self.active_evidence()):
            raise ValueError("stale active alignment")
        if (
            self.permit is not None
            and self.permit.drive_power_rev != self.drive_power_rev
        ):
            raise ValueError("stale active power permit")
        _require_parents(self.lock, self.clearance)
        _require_parents(self.permit, self.lock)
        if self.dispatched is not None and self.active_evidence():
            raise ValueError("dispatched train cannot have an active permit")
        return self

    def change_alignment(self, *, power_changed: bool) -> Self:
        return self._invalidate(
            tuple(self.evidence_slots),
            track_rev=self.track_rev + 1,
            drive_power_rev=self.drive_power_rev + int(power_changed),
        )

    def change_drive_power(self) -> Self:
        return self._invalidate(("permit",), drive_power_rev=self.drive_power_rev + 1)


class LighthousePuzzles(_PuzzleModel):
    story: Literal["lighthouse"] = "lighthouse"
    l03: EchoState = EchoState()
    l05: TideState = TideState()

    def chapters(self) -> tuple[PuzzleState, ...]:
        return (self.l03, self.l05)


class StarlinePuzzles(_PuzzleModel):
    story: Literal["starline"] = "starline"
    s03: SurveyState = SurveyState()
    s05: ApproachState = ApproachState()

    def chapters(self) -> tuple[PuzzleState, ...]:
        return (self.s03, self.s05)


Puzzles = Annotated[LighthousePuzzles | StarlinePuzzles, Field(discriminator="story")]


def _matches_scope(
    context: EvidenceContext, item: Evidence | InvalidatedEvidence
) -> bool:
    origin = context.model_copy(update={"accepted_version": item.accepted_version})
    return item.id == origin.id_for(item.kind, ordinal=item.ordinal)


def validate_puzzle_scope(context: EvidenceContext, puzzles: Puzzles) -> None:
    """Called at the aggregate boundary, where the actual Save ID is known."""
    for chapter in puzzles.chapters():
        for item in (*chapter.records(), *chapter.history):
            if item.accepted_version >= context.accepted_version or not _matches_scope(
                context, item
            ):
                raise ValueError("invalid evidence scope or version")
        if any(
            milestone.accepted_version >= context.accepted_version
            for milestone in chapter.milestones()
        ):
            raise ValueError("puzzle milestone is newer than the save")


def require_current_evidence(
    context: EvidenceContext,
    puzzles: Puzzles,
    evidence_id: UUID,
    kind: EvidenceKind,
    *,
    issuer: Role,
    parents: tuple[UUID, ...] | None = None,
) -> Evidence:
    """Resolve only committed active slots; callers authorize the action first."""
    try:
        puzzles = type(puzzles).model_validate(puzzles)
    except ValidationError:
        raise DomainError("EVIDENCE_STALE") from None
    if context.script_id != puzzles.story:
        raise DomainError("EVIDENCE_STALE")
    for chapter in puzzles.chapters():
        for item in chapter.active_evidence():
            if (
                item.id == evidence_id
                and item.kind == kind
                and item.role == issuer
                and item.accepted_version < context.accepted_version
                and _matches_scope(context, item)
                and (parents is None or item.parents == parents)
            ):
                return item
    raise DomainError("EVIDENCE_STALE")
