"""服务端剧本声明：只校验数据，不执行动作，也不读取媒体文件。"""

import re
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

Role = Literal["a", "b"]
Audience = Literal["public", "a", "b"]
Identifier = Annotated[StrictStr, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Version = Annotated[
    StrictStr,
    StringConstraints(
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$", max_length=32
    ),
]
Text = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
Scalar = StrictBool | StrictInt | StrictStr
PositiveInt = Annotated[StrictInt, Field(gt=0)]
ErrorCode = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]


class ContentModel(BaseModel):
    # 拒绝拼错/偷偷增加的字段；tuple与冻结模型也避免校验后意外改写定义。
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class RoleDefinition(ContentModel):
    id: Role
    name: Text
    description: Text


class ScriptMetadata(ContentModel):
    """唯一可供公开目录使用的模型；不嵌入规则、线索或媒体清单。"""

    id: Identifier
    content_version: Version
    title: Text
    summary: Text
    roles: tuple[RoleDefinition, RoleDefinition]
    difficulty: Literal["easy", "medium", "hard"]
    estimated_minutes: PositiveInt

    @model_validator(mode="after")
    def require_both_roles(self) -> Self:
        if {role.id for role in self.roles} != {"a", "b"}:
            raise ValueError("metadata.roles must contain a and b exactly once")
        return self


class FactCondition(ContentModel):
    kind: Literal["fact"]
    fact_id: Identifier
    equals: Scalar


class ClueCondition(ContentModel):
    kind: Literal["clue"]
    clue_id: Identifier
    discovered: StrictBool


class DeviceCondition(ContentModel):
    kind: Literal["device"]
    device_id: Identifier
    field: Identifier
    equals: Scalar


Condition = Annotated[
    FactCondition | ClueCondition | DeviceCondition, Field(discriminator="kind")
]


class RoleObservation(ContentModel):
    role: Role
    text: Text


class SceneDefinition(ContentModel):
    id: Identifier
    title: Text
    observations: tuple[RoleObservation, RoleObservation]
    entry_conditions: tuple[Condition, ...] = ()
    completion_conditions: tuple[Condition, ...] = ()
    next_scene_ids: tuple[Identifier, ...] = ()
    terminal: StrictBool = False

    @model_validator(mode="after")
    def require_both_views(self) -> Self:
        if {view.role for view in self.observations} != {"a", "b"}:
            raise ValueError("scene.observations must contain a and b exactly once")
        if len(set(self.next_scene_ids)) != len(self.next_scene_ids):
            raise ValueError("scene.next_scene_ids contains duplicate references")
        if self.terminal and self.next_scene_ids:
            raise ValueError("terminal scene cannot have next_scene_ids")
        return self


class FactDefinition(ContentModel):
    id: Identifier
    audience: Audience
    initial_value: Scalar


class ClueDefinition(ContentModel):
    id: Identifier
    role: Role
    text: Text
    shareable: StrictBool
    discovery_conditions: tuple[Condition, ...] = ()


class ParameterDefinition(ContentModel):
    id: Identifier
    value_type: Literal["boolean", "integer", "string"]
    choices: tuple[Scalar, ...] = ()
    max_length: PositiveInt | None = None

    @model_validator(mode="after")
    def check_choices(self) -> Self:
        expected = {"boolean": bool, "integer": int, "string": str}[self.value_type]
        if any(type(value) is not expected for value in self.choices):
            raise ValueError("choices must match value_type without coercion")
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("choices contains duplicate values")
        if self.max_length is not None and self.value_type != "string":
            raise ValueError("max_length is only valid for strings")
        if self.value_type == "string":
            if not self.choices and self.max_length is None:
                raise ValueError("free string parameter needs max_length")
            if self.max_length is not None and any(
                len(value) > self.max_length for value in self.choices
            ):
                raise ValueError("choices exceeds max_length")
        return self


class DeviceField(ParameterDefinition):
    choices: Annotated[tuple[Scalar, ...], Field(min_length=1)]
    initial_value: Scalar

    @model_validator(mode="after")
    def check_initial_value(self) -> Self:
        if not any(
            type(self.initial_value) is type(value) and self.initial_value == value
            for value in self.choices
        ):
            raise ValueError("initial_value must be one of choices, with the same type")
        return self


class DeviceDefinition(ContentModel):
    id: Identifier
    role: Role
    fields: Annotated[tuple[DeviceField, ...], Field(min_length=1)]


class DiscoverClue(ContentModel):
    op: Literal["discover_clue"]
    clue_id: Identifier


class SetDevice(ContentModel):
    op: Literal["set_device"]
    device_id: Identifier
    field: Identifier
    parameter: Identifier


class SetFact(ContentModel):
    op: Literal["set_fact"]
    fact_id: Identifier
    value: Scalar


class EnterScene(ContentModel):
    op: Literal["enter_scene"]
    scene_id: Identifier


class RecordVote(ContentModel):
    op: Literal["record_vote"]
    parameter: Identifier


class Observe(ContentModel):
    op: Literal["observe"]
    audience: Audience
    text: Text


# 这是允许声明的原语集合，不是执行器注册表；T02才实现对应规则。
Effect = Annotated[
    DiscoverClue | SetDevice | SetFact | EnterScene | RecordVote | Observe,
    Field(discriminator="op"),
]


class ActionDefinition(ContentModel):
    id: Identifier
    kind: Identifier
    roles: Annotated[tuple[Role, ...], Field(min_length=1)]
    scene_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    parameters: tuple[ParameterDefinition, ...] = ()
    preconditions: tuple[Condition, ...] = ()
    effects: Annotated[tuple[Effect, ...], Field(min_length=1)]
    error_codes: Annotated[tuple[ErrorCode, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def reject_duplicates(self) -> Self:
        for name in ("roles", "scene_ids", "error_codes"):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f"actions.{self.id}.{name} contains duplicate values")
        return self


class EndingDefinition(ContentModel):
    id: Identifier
    scene_id: Identifier
    summary_template: Text


class HintDefinition(ContentModel):
    scene_id: Identifier
    # Literal[1,2,3]也会接受True；严格整数防止把布尔值当作提示级别。
    level: Annotated[StrictInt, Field(ge=1, le=3)]
    text: Text


class NpcDefinition(ContentModel):
    name: Text
    public_persona: Text
    allowed_topics: Annotated[tuple[Text, ...], Field(min_length=1)]
    hints: tuple[HintDefinition, ...]


class MediaAsset(ContentModel):
    id: Identifier
    kind: Literal["image", "ambience", "sfx", "narration"]
    content_version: Version
    audience: Audience
    scene_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    conditions: tuple[Condition, ...] = ()
    path: StrictStr
    alt_text: Text
    transcript: Text | None = None
    source: Text
    license: Text

    @field_validator("path")
    @classmethod
    def require_relative_path(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", value) or any(
            part in {"", ".", ".."} or part.endswith(".") for part in value.split("/")
        ):
            raise ValueError("path must be a canonical relative asset path")
        return value

    @model_validator(mode="after")
    def check_media_kind(self) -> Self:
        suffix = self.path.rsplit(".", 1)[-1].lower()
        supported = (
            {"png", "jpg", "jpeg", "webp"}
            if self.kind == "image"
            else {"mp3", "ogg", "wav", "m4a"}
        )
        if suffix not in supported:
            raise ValueError("path extension does not match media kind")
        if self.kind == "narration" and self.transcript is None:
            raise ValueError("narration requires transcript")
        return self


class CueDefinition(ContentModel):
    id: Identifier
    asset_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    conditions: tuple[Condition, ...] = ()
    alt_text: Text


class ScenePresentation(ContentModel):
    scene_id: Identifier
    role: Role
    background_asset_id: Identifier
    cues: tuple[CueDefinition, ...] = ()


class EndingVote(ContentModel):
    role: Role
    ending_id: Identifier


class InitialState(ContentModel):
    scene_id: Identifier
    discovered_clues: tuple[Identifier, ...] = ()
    shared_clues: tuple[Identifier, ...] = ()
    votes: tuple[EndingVote, ...] = ()
    completed: StrictBool = False

    @model_validator(mode="after")
    def require_fresh_start(self) -> Self:
        if self.discovered_clues or self.shared_clues or self.votes or self.completed:
            raise ValueError(
                "initial_state must start undiscovered, unshared, unvoted and incomplete"
            )
        return self


class ScriptVersion(ContentModel):
    metadata: ScriptMetadata
    initial_state: InitialState
    scenes: Annotated[tuple[SceneDefinition, ...], Field(min_length=1)]
    facts: tuple[FactDefinition, ...]
    clues: tuple[ClueDefinition, ...]
    devices: tuple[DeviceDefinition, ...]
    actions: Annotated[tuple[ActionDefinition, ...], Field(min_length=1)]
    endings: Annotated[tuple[EndingDefinition, ...], Field(min_length=1)]
    npc: NpcDefinition
    media: Annotated[tuple[MediaAsset, ...], Field(min_length=1)]
    presentation: Annotated[tuple[ScenePresentation, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def check_references(self) -> Self:
        # 结构与跨表引用分开；该函数只在所有子模型已合法后调用。
        from ._references import validate_references

        validate_references(self)
        return self
