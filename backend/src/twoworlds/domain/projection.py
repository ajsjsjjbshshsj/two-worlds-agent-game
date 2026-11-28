"""从完整世界逐字段构造个人展示值；不输出内部规则、文件路径或伙伴秘密。"""

from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, field_serializer, field_validator

from twoworlds.content.schema import (
    ContentModel,
    Identifier,
    PositiveInt,
    Role,
    Scalar,
    ScriptVersion,
    Text,
    Version,
)

from .audio import operation_sounds
from .engine import shareable_clue_ids, validate_state_and_script
from .errors import DomainError
from .mechanics.common import conditions_met
from .models import GameState
from .persistence import DialogueTurn, Question, UTCDateTime
from .puzzles import (
    Beat,
    Bridge,
    Challenge,
    EvidenceId,
    EvidenceKind,
    FarSample,
    LighthousePuzzles,
    NearSample,
    Reply,
    TideReading,
    TideScan,
    TideWindow,
)
from .visuals import VisualEffect, project_visuals
from .recap import (
    PUBLIC_PROGRESS_FACTS,
    PublicEvent,
    PublicHistory,
    PublicRecap,
    read_public_history,
)


class ClueView(ContentModel):
    id: Identifier
    text: Text


class DeviceFieldView(ContentModel):
    id: Identifier
    value: Scalar


class DeviceView(ContentModel):
    id: Identifier
    fields: tuple[DeviceFieldView, ...]


class ObservationView(ContentModel):
    topic: Identifier
    text: Text


class PuzzleMilestoneView(ContentModel):
    kind: Literal[
        "signal_locked",
        "route_confirmed",
        "track_published",
        "rail_installed",
        "train_dispatched",
    ]
    accepted_version: PositiveInt


class PuzzleEvidenceView(ContentModel):
    id: EvidenceId
    kind: EvidenceKind
    beats: tuple[Beat, Beat] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    windows: tuple[TideWindow, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    segments: tuple[Bridge, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class PublicView(ContentModel):
    clues: tuple[ClueView, ...]
    ending: Identifier | None
    events: tuple[PublicEvent, ...] = ()
    recap: PublicRecap = PublicRecap()
    puzzle_milestones: tuple[PuzzleMilestoneView, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class DialogueView(ContentModel):
    """本人私聊轮次；角色过滤在投影内完成，伙伴看不到提问原文。"""

    question: Question
    answer: Text
    mode: Literal["demo", "provider", "fallback"]
    created_at: UTCDateTime


class PersonalView(ContentModel):
    clues: tuple[ClueView, ...]
    dialogue: tuple[DialogueView, ...] = ()
    devices: tuple[DeviceView, ...]
    observations: tuple[ObservationView, ...]
    puzzle_evidence: tuple[PuzzleEvidenceView, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @field_serializer("devices")
    def device_object(
        self, devices: tuple[DeviceView, ...]
    ) -> dict[str, dict[str, Scalar]]:
        # 内部保持嵌套冻结；每次序列化才新建既定JSON装置对象，不共享字典。
        return {
            item.id: {field.id: field.value for field in item.fields}
            for item in devices
        }

    @field_validator("devices", mode="before")
    @classmethod
    def read_device_object(cls, value):
        if type(value) is dict:
            if any(
                type(identifier) is not str
                or type(fields) is not dict
                or any(type(field) is not str for field in fields)
                for identifier, fields in value.items()
            ):
                raise ValueError("devices must map string IDs to field objects")
            return tuple(
                {
                    "id": identifier,
                    "fields": tuple(
                        {"id": field, "value": current}
                        for field, current in sorted(fields.items())
                    ),
                }
                for identifier, fields in sorted(value.items())
            )
        return value


class ParameterView(ContentModel):
    id: Identifier
    value_type: Literal["boolean", "integer", "string"]
    choices: tuple[Scalar, ...]
    max_length: PositiveInt | None


class ActionView(ContentModel):
    id: Identifier
    kind: Identifier
    parameters: tuple[ParameterView, ...]


class MediaReference(ContentModel):
    asset_id: Identifier
    kind: Literal["image", "ambience", "sfx", "narration"]
    alt_text: Text
    transcript: Text | None


class CueView(ContentModel):
    id: Identifier
    alt_text: Text
    assets: tuple[MediaReference, ...]


class PresentationView(ContentModel):
    operation_sfx: tuple[Identifier, ...] = ()
    background: MediaReference | None
    cues: tuple[CueView, ...]
    visual_state: tuple[VisualEffect, ...] = ()


class PlayerSnapshot(ContentModel):
    """独立的个人快照，不继承或嵌入GameState/ScriptVersion。"""

    script_id: Identifier
    script_version: Version
    version: Annotated[StrictInt, Field(ge=0)]
    role: Role
    scene_id: Identifier
    completed: StrictBool
    public: PublicView
    personal: PersonalView
    available_actions: tuple[ActionView, ...]
    presentation: PresentationView


def _actions(
    state: GameState, script: ScriptVersion, role: Role
) -> tuple[ActionView, ...]:
    if state.completed:
        return ()
    actions = [
        ActionView(
            id=action.id,
            kind=action.kind,
            parameters=tuple(
                ParameterView(
                    id=parameter.id,
                    value_type=parameter.value_type,
                    choices=tuple(choice for choice in parameter.choices),
                    max_length=parameter.max_length,
                )
                for parameter in sorted(action.parameters, key=lambda item: item.id)
            ),
        )
        for action in sorted(script.actions, key=lambda item: item.id)
        if role in action.roles
        and state.scene_id in action.scene_ids
        and conditions_met(state, action.preconditions)
    ]
    choices = shareable_clue_ids(state, script, role)
    if choices:
        actions.append(
            ActionView(
                id="share_clue",
                kind="share_clue",
                parameters=(
                    ParameterView(
                        id="clue_id",
                        value_type="string",
                        choices=choices,
                        max_length=64,
                    ),
                ),
            )
        )
    return tuple(sorted(actions, key=lambda action: action.id))


def _presentation(
    state: GameState, script: ScriptVersion, role: Role
) -> PresentationView:
    view = next(
        item
        for item in script.presentation
        if item.scene_id == state.scene_id and item.role == role
    )
    assets = {item.id: item for item in script.media}

    def reference(identifier: str) -> MediaReference | None:
        asset = assets[identifier]
        if (
            asset.audience not in {"public", role}
            or state.scene_id not in asset.scene_ids
            or not conditions_met(state, asset.conditions)
        ):
            return None
        return MediaReference(
            asset_id=asset.id,
            kind=asset.kind,
            alt_text=asset.alt_text,
            transcript=asset.transcript,
        )

    cues = []
    for cue in sorted(view.cues, key=lambda item: item.id):
        if not conditions_met(state, cue.conditions):
            continue
        allowed = tuple(
            media
            for identifier in cue.asset_ids
            if (media := reference(identifier)) is not None
        )
        # 不返回空演出的ID/文字；它也可能透露尚未开放的内容。
        if allowed:
            cues.append(CueView(id=cue.id, alt_text=cue.alt_text, assets=allowed))
    return PresentationView(
        background=reference(view.background_asset_id),
        cues=tuple(cues),
        visual_state=project_visuals(state, script.metadata.id, role),
        operation_sfx=tuple(
            sorted(
                {
                    asset.asset_id
                    for cue in cues
                    for asset in cue.assets
                    if asset.kind == "sfx"
                    and asset.asset_id in operation_sounds(script.metadata.id)
                }
            )
        ),
    )


def _puzzle_evidence(
    state: GameState, role: Role
) -> tuple[PuzzleEvidenceView, ...] | None:
    if state.puzzles is None:
        return None
    return tuple(
        PuzzleEvidenceView(
            id=item.id,
            kind=item.kind,
            beats=item.beats if isinstance(item, (Challenge, Reply)) else None,
            windows=item.windows if isinstance(item, (TideReading, TideScan)) else None,
            segments=item.segments
            if isinstance(item, (NearSample, FarSample))
            else None,
        )
        for chapter in state.puzzles.chapters()
        for item in chapter.active_evidence()
        if item.role == role
    )


def _puzzle_milestones(state: GameState) -> tuple[PuzzleMilestoneView, ...] | None:
    puzzles = state.puzzles
    if puzzles is None:
        return None
    if isinstance(puzzles, LighthousePuzzles):
        values = (
            ("signal_locked", puzzles.l03.locked),
            ("route_confirmed", puzzles.l05.confirmed),
        )
    else:
        values = (
            ("track_published", puzzles.s03.published),
            ("rail_installed", puzzles.s03.installed),
            ("train_dispatched", puzzles.s05.dispatched),
        )
    return tuple(
        PuzzleMilestoneView(kind=kind, accepted_version=item.accepted_version)
        for kind, item in values
        if item is not None
    )


def project_save(
    state: GameState,
    script: ScriptVersion,
    role: str,
    public_history: PublicHistory | None = None,
    dialogues: Sequence[DialogueTurn] = (),
) -> PlayerSnapshot:
    """role须由可信调用方提供；本函数只做内容权限投影，不执行身份认证。"""
    state, script = validate_state_and_script(state, script)
    if type(role) is not str or role not in {"a", "b"}:
        raise DomainError("ROLE_FORBIDDEN")
    events, recap = (), PublicRecap()
    if public_history is not None:
        history, recap = read_public_history(public_history, script, state.ending_id)
        scenes = [
            step.subject_id for step in recap.milestones if step.kind == "scene_entered"
        ]
        shared = {
            step.subject_id for step in recap.milestones if step.kind == "clue_shared"
        }
        facts = {
            step.kind for step in recap.milestones if step.kind in PUBLIC_PROGRESS_FACTS
        }
        expected_facts = {
            fact.id
            for fact in script.facts
            if fact.audience == "public"
            and fact.id in PUBLIC_PROGRESS_FACTS
            and state.fact(fact.id) is True
            and fact.initial_value is not True
        }
        if (
            history.through_version != state.version
            or (scenes[-1] if scenes else script.initial_state.scene_id)
            != state.scene_id
            or shared != set(state.shared_clues)
            or facts != expected_facts
        ):
            raise DomainError("INVALID_PUBLIC_HISTORY")
        events = history.events
    scene = next(item for item in script.scenes if item.id == state.scene_id)
    clues = sorted(script.clues, key=lambda item: item.id)
    devices = {item.id: item for item in state.devices}
    return PlayerSnapshot(
        script_id=state.script_id,
        script_version=state.script_version,
        version=state.version,
        role=role,
        scene_id=state.scene_id,
        completed=state.completed,
        public=PublicView(
            clues=tuple(
                ClueView(id=clue.id, text=clue.text)
                for clue in clues
                if clue.id in state.shared_clues
            ),
            ending=state.ending_id if state.completed else None,
            events=events,
            recap=recap,
            puzzle_milestones=_puzzle_milestones(state),
        ),
        personal=PersonalView(
            puzzle_evidence=_puzzle_evidence(state, role),
            clues=tuple(
                ClueView(id=clue.id, text=clue.text)
                for clue in clues
                if clue.role == role and clue.id in state.discovered_clues
            ),
            dialogue=tuple(
                DialogueView(**turn.model_dump(exclude={"role"}))
                for turn in dialogues
                if turn.role == role
            ),
            devices=tuple(
                DeviceView(
                    id=definition.id,
                    fields=tuple(
                        DeviceFieldView(
                            id=field.id,
                            value=next(
                                item.value
                                for item in devices[definition.id].fields
                                if item.id == field.id
                            ),
                        )
                        for field in sorted(definition.fields, key=lambda item: item.id)
                    ),
                )
                for definition in sorted(script.devices, key=lambda item: item.id)
                if definition.role == role
            ),
            observations=(
                ObservationView(
                    topic="scene",
                    text=next(
                        item.text for item in scene.observations if item.role == role
                    ),
                ),
            )
            + tuple(
                ObservationView(topic=item.topic, text=item.text)
                for item in sorted(state.observations, key=lambda item: item.topic)
                if item.audience == role
            ),
        ),
        available_actions=_actions(state, script, role),
        presentation=_presentation(state, script, role),
    )
