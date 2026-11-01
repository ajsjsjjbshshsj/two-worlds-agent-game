"""运行中的世界值，与不可变ScriptVersion内容定义分离；完整状态仅供服务端。"""

from typing import Annotated, NamedTuple

from pydantic import Field, StrictBool, StrictInt

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
