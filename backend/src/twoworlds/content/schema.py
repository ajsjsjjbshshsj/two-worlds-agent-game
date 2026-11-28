"""服务端剧本声明：只校验数据，不执行动作，也不读取媒体文件。

校验分两层：
1. 本文件管"单条声明自身合法"——字段类型、取值范围、跨字段一致性；
2. 跨表引用（场景指向、线索归属、媒体可见范围）在 _references.py，
   必须等所有子模型各自合法之后才检查。

校验产物是冻结对象：拒绝常规字段赋值，配合tuple防止无意改写剧本定义。
真正读取这些声明执行规则是 T02/T03 的事。
"""

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

# 双人剧本只有两个角色；用 Literal 让非法角色在解析期就被拒，而不是运行期找不到分支
Role = Literal["a", "b"]  # Role只能取这几个
# public=双方可见；a/b=仅该角色可见。线索、事实、媒体都用它表达可见范围
Audience = Literal["public", "a", "b"]  # 同上
# 会出现在 URL、数据库键和引用里；限定小写字符集免去转义与大小写歧义（数据类型和范围检验）
Identifier = Annotated[StrictStr, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
# 三段式版本号，禁止前导零；存档绑定它，内容一改就必须换版本
Version = Annotated[
    StrictStr,
    StringConstraints(
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$", max_length=32
    ),
]
# 去首尾空格后仍必须有内容（挡住全空白文案），上限 2000 防止异常长文本进投影
Text = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
# 事实值/设备值/条件比较值只允许三种原子类型：排除列表、对象和浮点
Scalar = StrictBool | StrictInt | StrictStr
# Strict 系列不接受 True 被当成 1，也不做字符串到数字的静默转换
PositiveInt = Annotated[StrictInt, Field(gt=0)]
# 错误码是给程序分支用的稳定标识，统一大写常量格式
ErrorCode = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]


class ContentModel(BaseModel):
    # 拒绝拼错/偷偷增加的字段；tuple与冻结模型也避免校验后意外改写定义。
    # validate_default：默认值同样要过校验，避免"默认值本身类型就是错的"。
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class RoleDefinition(ContentModel):
    """角色的公开介绍，不定义规则或私密字段；介绍文案仍需作者审核。"""

    id: Role
    name: Text
    description: Text


class ScriptMetadata(ContentModel):
    """唯一可供公开目录使用的模型；不嵌入规则、线索或媒体清单。"""

    id: Identifier
    content_version: Version
    title: Text
    summary: Text
    # 定长两条：只有两个角色，多一条少一条都说明内容写错了
    roles: tuple[RoleDefinition, RoleDefinition]
    difficulty: Literal["easy", "medium", "hard"]
    estimated_minutes: PositiveInt

    @model_validator(mode="after")
    def require_both_roles(self) -> Self:
        # 类型只保证"恰好两条"，这里补上"必须一 a 一 b"，防止两个 b 或重复角色
        if {role.id for role in self.roles} != {"a", "b"}:
            raise ValueError("metadata.roles must contain a and b exactly once")
        return self


class FactCondition(ContentModel):
    """谓词：某事实当前等于某值。"""

    kind: Literal["fact"]
    fact_id: Identifier
    equals: Scalar


class ClueCondition(ContentModel):
    """谓词：某线索是否已被发现。"""

    kind: Literal["clue"]
    clue_id: Identifier
    discovered: StrictBool


class DeviceCondition(ContentModel):
    """谓词：某设备的某个字段等于某值。"""

    kind: Literal["device"]
    device_id: Identifier
    field: Identifier
    equals: Scalar


# 带判别字段的联合类型：JSON 里 kind 决定解析成哪个类。
# 只允许这三种条件声明，不支持任意表达式求值。
Condition = Annotated[
    FactCondition | ClueCondition | DeviceCondition, Field(discriminator="kind")
]


class RoleObservation(ContentModel):
    """某个角色进入该场景时看到的那段文字。"""

    role: Role
    text: Text


class SceneDefinition(ContentModel):
    """一个场景：两条开场观察 + 进出条件 + 场景图出边。"""

    id: Identifier
    title: Text
    # 定长两条：漏掉某个角色，那人进场景就什么都看不到
    observations: tuple[RoleObservation, RoleObservation]
    entry_conditions: tuple[Condition, ...] = ()
    completion_conditions: tuple[Condition, ...] = ()
    next_scene_ids: tuple[Identifier, ...] = ()
    terminal: StrictBool = False

    @model_validator(mode="after")
    def require_both_views(self) -> Self:
        # 集合比较而非顺序比较：a/b 谁在前无所谓，缺一个或重复才是错误
        if {view.role for view in self.observations} != {"a", "b"}:
            raise ValueError("scene.observations must contain a and b exactly once")
        # 重复出边没有额外含义，拒绝它以保持场景图声明清晰。
        if len(set(self.next_scene_ids)) != len(self.next_scene_ids):
            raise ValueError("scene.next_scene_ids contains duplicate references")
        # 终点的定义就是没有下一步，有出边说明内容自相矛盾
        if self.terminal and self.next_scene_ids:
            raise ValueError("terminal scene cannot have next_scene_ids")
        return self


class FactDefinition(ContentModel):
    """世界事实的定义：初始值由内容决定，之后只能由动作效果改变。"""

    id: Identifier
    audience: Audience
    initial_value: Scalar


class ClueDefinition(ContentModel):
    """线索：从属于某个角色，shareable 决定发现后能否用 share_clue 公开文本。"""

    id: Identifier
    role: Role
    text: Text
    shareable: StrictBool
    discovery_conditions: tuple[Condition, ...] = ()


class ParameterDefinition(ContentModel):
    """动作参数的声明：值类型 + 允许取值。自由字符串必须给长度上限。"""

    id: Identifier
    value_type: Literal["boolean", "integer", "string"]
    choices: tuple[Scalar, ...] = ()
    max_length: PositiveInt | None = None

    @model_validator(mode="after")
    def check_choices(self) -> Self:
        expected = {"boolean": bool, "integer": int, "string": str}[self.value_type]
        # 用 type(...) is 而不是 isinstance：bool 是 int 的子类，
        # isinstance(True, int) 为真，会把布尔选项混进整数参数
        if any(type(value) is not expected for value in self.choices):
            raise ValueError("choices must match value_type without coercion")
        # 重复选项会让前端出现两个一模一样的按钮
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("choices contains duplicate values")
        if self.max_length is not None and self.value_type != "string":
            raise ValueError("max_length is only valid for strings")
        if self.value_type == "string":
            # 既没有选项也没有长度上限 = 字符串长度不受控
            if not self.choices and self.max_length is None:
                raise ValueError("free string parameter needs max_length")
            if self.max_length is not None and any(
                len(value) > self.max_length for value in self.choices
            ):
                raise ValueError("choices exceeds max_length")
        return self


class DeviceField(ParameterDefinition):
    """装置的一个可调字段；选项至少一个，初始值必须在选项里。"""

    choices: Annotated[tuple[Scalar, ...], Field(min_length=1)]
    initial_value: Scalar

    @model_validator(mode="after")
    def check_initial_value(self) -> Self:
        # 同时比类型和值：0 和 False 的值相等但不是同一回事
        if not any(
            type(self.initial_value) is type(value) and self.initial_value == value
            for value in self.choices
        ):
            raise ValueError("initial_value must be one of choices, with the same type")
        return self


class DeviceDefinition(ContentModel):
    """装置归属于单个角色；谁能操作它由跨表校验（_references）保证。"""

    id: Identifier
    role: Role
    fields: Annotated[tuple[DeviceField, ...], Field(min_length=1)]


class DiscoverClue(ContentModel):
    """效果：让执行者发现一条线索。"""

    op: Literal["discover_clue"]
    clue_id: Identifier


class SetDevice(ContentModel):
    """效果：把动作参数 parameter 的值写到装置字段 field 上。"""

    op: Literal["set_device"]
    device_id: Identifier
    field: Identifier
    parameter: Identifier


class SetFact(ContentModel):
    """效果：把世界事实改成指定值。"""

    op: Literal["set_fact"]
    fact_id: Identifier
    value: Scalar


class EnterScene(ContentModel):
    """效果：切换到另一个场景。"""

    op: Literal["enter_scene"]
    scene_id: Identifier


class RecordVote(ContentModel):
    """效果：把参数 parameter 的值记录为这一票。"""

    op: Literal["record_vote"]
    parameter: Identifier


class Observe(ContentModel):
    """效果：向指定受众追加一段观察文本。"""

    op: Literal["observe"]
    audience: Audience
    text: Text


# 这是允许声明的原语集合，不是执行器注册表；T02才实现对应规则。
# 只接受这六种效果标识，不解释或执行内容中的代码（如eval_python）。
Effect = Annotated[
    DiscoverClue | SetDevice | SetFact | EnterScene | RecordVote | Observe,
    Field(discriminator="op"),
]


class ActionDefinition(ContentModel):
    """一个动作：谁、在哪个场景、带什么参数、满足什么前置、产生什么效果。"""

    id: Identifier
    kind: Identifier
    # 至少一个角色、至少一个场景；空列表等于"谁都做不了"或"哪都不能做"
    roles: Annotated[tuple[Role, ...], Field(min_length=1)]
    scene_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    parameters: tuple[ParameterDefinition, ...] = ()
    preconditions: tuple[Condition, ...] = ()
    # 效果和错误码都至少一条：没有效果的动作没有意义，没有错误码则失败时无从解释
    effects: Annotated[tuple[Effect, ...], Field(min_length=1)]
    error_codes: Annotated[tuple[ErrorCode, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def reject_duplicates(self) -> Self:
        # 三个"集合语义"的字段不允许重复：重复角色/场景/错误码没有意义
        for name in ("roles", "scene_ids", "error_codes"):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f"actions.{self.id}.{name} contains duplicate values")
        return self


class EndingDefinition(ContentModel):
    """结局：id 是投票选项，scene_id 是结算后展示的场景，summary 是公开回顾文案。"""

    id: Identifier
    scene_id: Identifier
    summary_template: Text


class HintDefinition(ContentModel):
    """NPC 的一条分级提示，绑定到具体场景。"""

    scene_id: Identifier
    # Literal[1,2,3]也会接受True；严格整数防止把布尔值当作提示级别。
    level: Annotated[StrictInt, Field(ge=1, le=3)]
    text: Text


class NpcDefinition(ContentModel):
    """NPC 只有表达职责：公开人设、允许话题、分级提示；没有修改事实的通道。"""

    name: Text
    public_persona: Text
    allowed_topics: Annotated[tuple[Text, ...], Field(min_length=1)]
    hints: tuple[HintDefinition, ...]


class MediaAsset(ContentModel):
    """媒体声明：只校验元数据与路径字符串，不读文件、不检查文件是否存在。"""

    id: Identifier
    kind: Literal["image", "ambience", "sfx", "narration"]
    # 资源也带版本：换文件不换版本会让缓存和存档对不上
    content_version: Version
    audience: Audience
    scene_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    conditions: tuple[Condition, ...] = ()
    path: StrictStr
    alt_text: Text
    # 旁白的文字稿：既作字幕，也是无障碍内容；audience 为 b 时它同样是私密文本
    transcript: Text | None = None
    source: Text
    license: Text

    @field_validator("path")
    @classmethod
    def require_relative_path(cls, value: str) -> str:
        # 只放行相对路径：挡掉绝对路径、盘符、反斜杠、URL 和 .. 穿越
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", value) or any(
            part in {"", ".", ".."} or part.endswith(".") for part in value.split("/")
        ):
            raise ValueError("path must be a canonical relative asset path")
        return value

    @model_validator(mode="after")
    def check_media_kind(self) -> Self:
        # 扩展名必须和 kind 对应：图片配图、音频配声，防止播放器拿到错格式
        suffix = self.path.rsplit(".", 1)[-1].lower()
        supported = (
            {"png", "jpg", "jpeg", "webp"}
            if self.kind == "image"
            else {"mp3", "ogg", "wav", "m4a"}
        )
        if suffix not in supported:
            raise ValueError("path extension does not match media kind")
        # 旁白没有文字稿就无法做字幕和无障碍
        if self.kind == "narration" and self.transcript is None:
            raise ValueError("narration requires transcript")
        return self


class CueDefinition(ContentModel):
    """场景内的一条演出提示：满足 conditions 时播放这些资源。"""

    id: Identifier
    asset_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    conditions: tuple[Condition, ...] = ()
    alt_text: Text


class ScenePresentation(ContentModel):
    """某个场景给某个角色的一份演示配置；每个场景每角色都必须有一条。"""

    scene_id: Identifier
    role: Role
    background_asset_id: Identifier
    cues: tuple[CueDefinition, ...] = ()


class EndingVote(ContentModel):
    """一票：谁投了哪个结局。"""

    role: Role
    ending_id: Identifier


class InitialState(ContentModel):
    """新档开局的初始状态，必须是干净起点。"""

    scene_id: Identifier
    discovered_clues: tuple[Identifier, ...] = ()
    shared_clues: tuple[Identifier, ...] = ()
    votes: tuple[EndingVote, ...] = ()
    completed: StrictBool = False

    @model_validator(mode="after")
    def require_fresh_start(self) -> Self:
        # 开局就带线索/投票/完成标记，等于把别人的进度塞进新档
        if self.discovered_clues or self.shared_clues or self.votes or self.completed:
            raise ValueError(
                "initial_state must start undiscovered, unshared, unvoted and incomplete"
            )
        return self


class ScriptVersion(ContentModel):
    """一个不可变的剧本版本：所有声明在此汇总，引用完整性最后统一校验。"""

    metadata: ScriptMetadata
    puzzle_rules: Literal["p0_v1"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
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

        if self.puzzle_rules is not None and (
            self.metadata.content_version == "1.0.0"
            or self.metadata.id not in {"lighthouse", "starline"}
        ):
            raise ValueError(
                "P0 puzzle rules require a new Lighthouse or Starline version"
            )
        validate_references(self)
        return self
