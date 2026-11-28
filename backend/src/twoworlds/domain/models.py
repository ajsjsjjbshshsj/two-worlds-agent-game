"""运行中的世界值，与不可变ScriptVersion内容定义分离；完整状态仅供服务端。"""

from typing import Annotated, NamedTuple, Self

from pydantic import Field, StrictBool, StrictInt, model_validator

from twoworlds.content.schema import (
    Audience,
    ContentModel,
    EndingVote,
    Identifier,
    Role,
    Scalar,
    Text,
    Version,
)


from .puzzles import LighthousePuzzles, Milestone, Puzzles, StarlinePuzzles


class StateValue(ContentModel):
    """某个事实/设备字段的当前原子值；不重复定义条件、选项或归属。"""

    id: Identifier
    value: Scalar


class DeviceState(ContentModel):
    id: Identifier
    fields: tuple[StateValue, ...]


class Observation(ContentModel):
    """机关根据当前事实计算的个人反馈，不能直接作为公共广播。"""

    audience: Role
    topic: Identifier
    text: Text


class GameState(ContentModel):
    script_id: Identifier
    script_version: Version
    version: Annotated[StrictInt, Field(ge=0)]
    scene_id: Identifier
    facts: tuple[StateValue, ...]
    devices: tuple[DeviceState, ...]
    discovered_clues: tuple[Identifier, ...] = ()
    shared_clues: tuple[Identifier, ...] = ()
    votes: tuple[EndingVote, ...] = ()
    completed: StrictBool = False
    ending_id: Identifier | None = None
    observations: tuple[Observation, ...] = ()

    puzzles: Puzzles | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def check_puzzle_version(self) -> Self:
        puzzles = self.puzzles
        if puzzles is None:
            return self
        if self.script_version == "1.0.0" or self.script_id != puzzles.story:
            raise ValueError("puzzle state does not match this story version")
        if isinstance(puzzles, LighthousePuzzles):
            revisions = (puzzles.l03.optics_rev, puzzles.l05.tide_config_rev)
        else:
            revisions = (
                puzzles.s03.survey_rev,
                puzzles.s05.track_rev,
                puzzles.s05.drive_power_rev,
            )
        if max(revisions) > self.version:
            raise ValueError("configuration revision is newer than the game state")
        if any(
            item.accepted_version > self.version
            for chapter in puzzles.chapters()
            for item in (*chapter.records(), *chapter.history, *chapter.milestones())
        ):
            raise ValueError("puzzle evidence is newer than the game state")
        for chapter in puzzles.chapters():
            chapter.validate_completion_at(self.version)
        facts = {item.id: item.value for item in self.facts}
        if any(facts.get(fact) is not True for fact, _ in self.puzzle_milestones()):
            raise ValueError("puzzle milestone requires its completed world fact")
        if isinstance(puzzles, StarlinePuzzles) and puzzles.s03.published is not None:
            if facts.get("scanned_segment") != puzzles.s03.published.segment:
                raise ValueError(
                    "published rail location does not match the world fact"
                )
        return self

    def puzzle_milestones(self) -> tuple[tuple[str, Milestone], ...]:
        puzzles = self.puzzles
        if puzzles is None:
            return ()
        if isinstance(puzzles, LighthousePuzzles):
            milestones = (
                ("signal_locked", puzzles.l03.locked),
                ("route_confirmed", puzzles.l05.confirmed),
            )
        else:
            milestones = (
                ("track_scanned", puzzles.s03.published),
                ("rail_installed", puzzles.s03.installed),
                ("train_dispatched", puzzles.s05.dispatched),
            )
        return tuple((fact, item) for fact, item in milestones if item is not None)

    def fact(self, identifier: str) -> Scalar:
        return next(item.value for item in self.facts if item.id == identifier)

    def device(self, identifier: str, field: str) -> Scalar:
        item = next(item for item in self.devices if item.id == identifier)
        return next(value.value for value in item.fields if value.id == field)


class DomainEvent(ContentModel):
    """事件是暂算产物；命令成功后才由入口统一绑定接受版本。"""

    kind: Identifier
    audience: Audience
    text: Text
    subject_id: Identifier | None = None
    field: Identifier | None = None
    value: Scalar | None = None
    version: Annotated[StrictInt, Field(ge=0)] = 0


class CommandResult(NamedTuple):
    state: GameState
    events: tuple[DomainEvent, ...]
