"""公共历史只接收已接受命令的事件，回顾只读取结构化里程碑和剧本。"""

from collections import deque
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import Field, StrictInt, ValidationError, model_validator

from twoworlds.content.schema import (
    ContentModel,
    Identifier,
    PositiveInt,
    ScriptVersion,
    Text,
    Version,
)

from .engine import _require_script
from .errors import DomainError
from .models import DomainEvent

EVENT_LIMIT = 30
MILESTONE_LIMIT = 64
PublicKind = Literal[
    "clue_shared",
    "scene_changed",
    "fact_changed",
    "vote_changed",
    "observation",
    "game_completed",
]
MilestoneKind = Literal[
    "clue_shared",
    "scene_entered",
    "signal_locked",
    "clock_repaired",
    "route_confirmed",
    "game_completed",
]
_FACT_STEPS = {
    "signal_locked": "跨时信号已锁定。",
    "clock_repaired": "灯塔时钟已修复。",
    "route_confirmed": "航道已共同验证。",
}
PUBLIC_PROGRESS_FACTS = tuple(_FACT_STEPS)
_FACT_TEXT = "世界事实已更新。"
_VOTE_TEXT = "共同选择已更新；一致前仍可修改本人选择。"


class PublicEvent(ContentModel):
    version: PositiveInt
    ordinal: PositiveInt
    kind: PublicKind
    text: Text


class PublicMilestone(ContentModel):
    version: PositiveInt
    ordinal: PositiveInt
    kind: MilestoneKind
    subject_id: Identifier


class PublicHistory(ContentModel):
    script_id: Identifier
    script_version: Version
    through_version: Annotated[StrictInt, Field(ge=0)] = 0
    event_count: Annotated[StrictInt, Field(ge=0)] = 0
    events: Annotated[tuple[PublicEvent, ...], Field(max_length=EVENT_LIMIT)] = ()
    milestones: Annotated[
        tuple[PublicMilestone, ...], Field(max_length=MILESTONE_LIMIT)
    ] = ()

    @model_validator(mode="after")
    def check_structure(self):
        """Check the persisted window independently of the pinned script."""
        first = max(1, self.event_count - EVENT_LIMIT + 1)
        if tuple(event.ordinal for event in self.events) != tuple(
            range(first, self.event_count + 1)
        ):
            raise ValueError("public event window is incomplete")
        for items in (self.events, self.milestones):
            previous_version, previous_ordinal = 0, 0
            for item in items:
                if not (
                    previous_version <= item.version <= self.through_version
                    and previous_ordinal < item.ordinal <= self.event_count
                ):
                    raise ValueError("public history versions or ordinals are invalid")
                previous_version, previous_ordinal = item.version, item.ordinal
        versions = {event.ordinal: event.version for event in self.events}
        for step in self.milestones:
            if self.events and step.ordinal < first:
                if step.version > self.events[0].version:
                    raise ValueError("older milestone follows the event window")
            elif versions.get(step.ordinal) != step.version:
                raise ValueError("milestone and retained event versions differ")
        return self


class RecapStep(PublicMilestone):
    text: Text


class PublicRecap(ContentModel):
    milestones: tuple[RecapStep, ...] = ()
    ending_id: Identifier | None = None
    summary: Text | None = None


def _public_observations(script: ScriptVersion) -> set[str]:
    return {
        effect.text
        for action in script.actions
        for effect in action.effects
        if effect.op == "observe" and effect.audience == "public"
    }


def _timeline(history: PublicHistory, script: ScriptVersion) -> tuple[RecapStep, ...]:
    scenes = {item.id: item for item in script.scenes}
    clues = {item.id: item for item in script.clues if item.shareable}
    endings = {item.id: item for item in script.endings}
    public_facts = {item.id for item in script.facts if item.audience == "public"}
    scene = scenes[script.initial_state.scene_id]
    seen = set()
    steps = []
    for item in history.milestones:
        key = (item.kind, item.subject_id)
        if key in seen or (steps and steps[-1].kind == "game_completed"):
            raise DomainError("INVALID_PUBLIC_HISTORY")
        if (
            item.kind == "clue_shared"
            and item.subject_id in clues
            and not scene.terminal
        ):
            text = clues[item.subject_id].text
        elif (
            item.kind in _FACT_STEPS
            and item.subject_id == item.kind
            and item.kind in public_facts
            and not scene.terminal
        ):
            text = _FACT_STEPS[item.kind]
        elif item.kind == "scene_entered" and item.subject_id in scene.next_scene_ids:
            target = scenes[item.subject_id]
            for condition in (*scene.completion_conditions, *target.entry_conditions):
                if (
                    condition.kind == "fact"
                    and condition.fact_id in _FACT_STEPS
                    and condition.fact_id in public_facts
                    and condition.equals is True
                    and (condition.fact_id, condition.fact_id) not in seen
                ):
                    raise DomainError("INVALID_PUBLIC_HISTORY")
            scene = target
            text = scene.title
        elif (
            item.kind == "game_completed"
            and scene.terminal
            and item.subject_id in endings
            and endings[item.subject_id].scene_id == scene.id
            and steps
            and steps[-1].kind == "scene_entered"
            and steps[-1].version == item.version == history.through_version
            and item.ordinal == history.event_count
        ):
            text = endings[item.subject_id].summary_template
        else:
            raise DomainError("INVALID_PUBLIC_HISTORY")
        seen.add(key)
        steps.append(RecapStep(**item.model_dump(), text=text))
    if scene.terminal and (not steps or steps[-1].kind != "game_completed"):
        raise DomainError("INVALID_PUBLIC_HISTORY")
    return tuple(steps)


def _validate_history(history: PublicHistory, script: ScriptVersion):
    if not isinstance(history, PublicHistory):
        raise DomainError("INVALID_PUBLIC_HISTORY")
    try:
        history = PublicHistory.model_validate(history.model_dump(warnings=False))
    except (ValidationError, TypeError, AttributeError):
        raise DomainError("INVALID_PUBLIC_HISTORY") from None
    if (history.script_id, history.script_version) != (
        script.metadata.id,
        script.metadata.content_version,
    ):
        raise DomainError("INVALID_PUBLIC_HISTORY")
    steps = _timeline(history, script)
    by_ordinal = {item.ordinal: item for item in steps}
    observations = _public_observations(script)
    for event in history.events:
        step = by_ordinal.get(event.ordinal)
        if step:
            kind = "scene_changed" if step.kind == "scene_entered" else step.kind
            kind = "fact_changed" if kind in _FACT_STEPS else kind
            valid = (event.version, event.kind, event.text) == (
                step.version,
                kind,
                step.text,
            )
        else:
            valid = (
                (event.kind == "fact_changed" and event.text == _FACT_TEXT)
                or (event.kind == "vote_changed" and event.text == _VOTE_TEXT)
                or (event.kind == "observation" and event.text in observations)
            )
        if not valid:
            raise DomainError("INVALID_PUBLIC_HISTORY")
    return history, steps


def _public_record(event: DomainEvent, script: ScriptVersion):
    """重建可展示文字，避免把事件的任意字段或原始私密文字送入历史。"""
    subject = event.subject_id
    kind = event.kind
    if kind == "clue_shared":
        for clue in script.clues:
            if clue.id == subject and clue.shareable and event.text == clue.text:
                return clue.text, kind
    elif kind == "scene_changed":
        for scene in script.scenes:
            if scene.id == subject:
                return scene.title, "scene_entered"
    elif kind == "fact_changed":
        for fact in script.facts:
            if (
                fact.id == subject
                and fact.audience == "public"
                and type(event.value) is type(fact.initial_value)
            ):
                if subject in _FACT_STEPS:
                    if event.value is True:
                        return _FACT_STEPS[subject], subject
                    break
                if subject == "completed" and event.value is not True:
                    break
                if subject == "ending_id" and event.value not in {
                    ending.id for ending in script.endings
                }:
                    break
                return _FACT_TEXT, None
    elif kind == "vote_changed" and subject in {"a", "b"}:
        if event.value in {ending.id for ending in script.endings}:
            return _VOTE_TEXT, None
    elif kind == "observation" and event.text in _public_observations(script):
        return event.text, None
    elif kind == "game_completed":
        for ending in script.endings:
            if ending.id == subject:
                return ending.summary_template, kind
    raise DomainError("INVALID_PUBLIC_EVENT")


def append_public_history(
    history: PublicHistory,
    script: ScriptVersion,
    accepted_version: int,
    events: Sequence[DomainEvent],
) -> PublicHistory:
    """每次接受命令调用一次，连同新状态一起交给未来的存档层。"""
    script = _require_script(script)
    history, steps = _validate_history(history, script)
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        raise DomainError("INVALID_PUBLIC_EVENT")
    if (
        type(accepted_version) is not int
        or accepted_version != history.through_version + 1
        or (steps and steps[-1].kind == "game_completed")
    ):
        raise DomainError("PUBLIC_HISTORY_VERSION")
    retained = deque(history.events, maxlen=EVENT_LIMIT)
    milestones = list(history.milestones)
    ordinal = history.event_count
    for event in events:
        if not isinstance(event, DomainEvent):
            raise DomainError("INVALID_PUBLIC_EVENT")
        try:
            event = DomainEvent.model_validate(event.model_dump(warnings=False))
        except (ValidationError, TypeError, AttributeError):
            raise DomainError("INVALID_PUBLIC_EVENT") from None
        if event.version != accepted_version:
            raise DomainError("PUBLIC_HISTORY_VERSION")
        if event.audience != "public":
            continue
        text, milestone_kind = _public_record(event, script)
        ordinal += 1
        retained.append(
            PublicEvent(
                version=accepted_version, ordinal=ordinal, kind=event.kind, text=text
            )
        )
        if milestone_kind:
            if len(milestones) == MILESTONE_LIMIT:
                raise DomainError("PUBLIC_MILESTONE_LIMIT")
            milestones.append(
                PublicMilestone(
                    version=accepted_version,
                    ordinal=ordinal,
                    kind=milestone_kind,
                    subject_id=event.subject_id,
                )
            )
    candidate = history.model_copy(
        update={
            "through_version": accepted_version,
            "event_count": ordinal,
            "events": tuple(retained),
            "milestones": tuple(milestones),
        }
    )
    validated, _ = _validate_history(candidate, script)
    return validated


def read_public_history(
    history: PublicHistory,
    script: ScriptVersion,
    ending_id: str | None,
) -> tuple[PublicHistory, PublicRecap]:
    script = _require_script(script)
    history, steps = _validate_history(history, script)
    finished = steps[-1] if steps and steps[-1].kind == "game_completed" else None
    if ending_id != (finished.subject_id if finished else None):
        raise DomainError("INVALID_PUBLIC_HISTORY")
    return history, PublicRecap(
        milestones=steps,
        ending_id=ending_id,
        summary=finished.text if finished else None,
    )


def build_public_recap(
    history: PublicHistory,
    script: ScriptVersion,
    ending_id: str | None,
) -> PublicRecap:
    """根据公共里程碑重建回顾，窗口内事件只用于校验历史完整性。"""
    _, recap = read_public_history(history, script, ending_id)
    return recap
