"""演示NPC私聊：应用层表达，不进入规则事实，不调用任何外部服务。

模块职责
---------
1. DemoNarrativeProvider：无网络依赖的固定模板 Provider，
   用于演示模式。结果稳定、可重复测试，清楚标记为 "demo"。

2. build_narrative_context：根据已经过投影的个人快照和当前问题，
   构造 NarrativeContext（白名单字段，不含搭档秘密或完整存档）。

3. append_demo_turn / DEMO_ANSWER：保留现有契约，不改变 HTTP 响应、
   私人对话结构及持久化格式。
"""

from datetime import datetime

from twoworlds.content.schema import ContentModel
from twoworlds.domain.persistence import DialogueTurn, Question
from twoworlds.ports.narrative import (
    AllowedClue,
    AllowedDevice,
    AllowedDeviceField,
    AllowedDialogueTurn,
    AllowedMilestone,
    NarrativeContext,
    NarrativeProvider,
    NarrativeRequest,
    NarrativeResponse,
    NpcPersona,
)

# 固定模板回复：不回显提问内容、不触及谜底或搭档秘密。
# 真实模型/LangGraph、三级提示与降级标识属于后续 T14.2/T14.3，
# 这里只兑现 demo 契约，并阻断提示注入的权限扩大效果。
DEMO_ANSWER = (
    "（演示模式）我是示例NPC，只提供氛围陪伴与通用建议，不掌握谜底，"
    "也不会改动任何游戏事实。请观察当前场景的线索，并与搭档交换你们各自看到的信息。"
)

TURNS_PER_ROLE = 20


class TalkArgs(ContentModel):
    question: Question


# ------------------------------------------------------------------
# DemoNarrativeProvider
# ------------------------------------------------------------------


class DemoNarrativeProvider(NarrativeProvider):
    """无网络、无 API Key 的固定模板 Provider（演示模式）。

    安全属性：
    - 只返回 DEMO_ANSWER 固定文本，不解析 NarrativeContext 中的游戏事实。
    - 不透露搭档私人信息（上下文本身已由 build_narrative_context 过滤）。
    - 不根据玩家要求修改游戏事实（Provider 无游戏状态写入权限）。
    - 不照搬恶意输入作为权威内容（固定模板，不回显 question）。
    - 在没有真实模型服务时仍然可以完整游玩。
    """

    @property
    def provider_name(self) -> str:
        return "demo"

    @property
    def mode(self):
        return "demo"

    def generate(self, request: NarrativeRequest) -> NarrativeResponse:
        # 显式忽略 request.context.question 的内容，不将其回显或作为授权依据。
        # 固定回复：稳定、可重复测试、不泄露任何游戏秘密。
        return NarrativeResponse(
            text=DEMO_ANSWER,
            mode="demo",
            provider_name="demo",
            prompt_version=request.prompt_version,
        )


# ------------------------------------------------------------------
# 安全上下文构造
# ------------------------------------------------------------------


def build_narrative_context(
    *,
    script_id: str,
    script_version: str,
    scene_id: str,
    role: str,
    personal_clues: list[dict],
    shared_clues: list[dict],
    personal_devices: list[dict],
    public_milestones: list[dict],
    recent_dialogue: list[DialogueTurn],
    question: str,
    persona_name: str,
    persona_bio: str,
) -> NarrativeContext:
    """根据服务端已授权的投影字段构造 NarrativeContext。

    参数全部来自服务端的角色投影（project_save 结果），
    不接受原始 SaveRecord 或数据库对象。

    隐私边界
    ---------
    - personal_clues：只含本角色已发现的线索（由 project_save 过滤）。
    - shared_clues：只含双方已正式公开的线索。
    - personal_devices：只含本角色的设备（由 project_save 过滤）。
    - recent_dialogue：只含本角色最近的对话轮次（由调用方过滤）。
    - 搭档的私人线索、设备、私聊历史均不出现。
    """
    return NarrativeContext(
        script_id=script_id,
        script_version=script_version,
        scene_id=scene_id,
        role=role,  # type: ignore[arg-type]
        personal_clues=tuple(
            AllowedClue(id=c["id"], text=c["text"]) for c in personal_clues
        ),
        shared_clues=tuple(
            AllowedClue(id=c["id"], text=c["text"]) for c in shared_clues
        ),
        personal_devices=tuple(
            AllowedDevice(
                id=d["id"],
                fields=tuple(
                    AllowedDeviceField(id=f["id"], value=f["value"])
                    for f in d.get("fields", [])
                ),
            )
            for d in personal_devices
        ),
        public_milestones=tuple(
            AllowedMilestone(kind=m["kind"], subject_id=m["subject_id"])
            for m in public_milestones
        ),
        recent_dialogue=tuple(
            AllowedDialogueTurn(
                question=turn.question,
                answer=turn.answer,
                mode=turn.mode,
            )
            for turn in recent_dialogue
            if turn.role == role
        )[-TURNS_PER_ROLE:],
        question=question,
        persona=NpcPersona(name=persona_name, bio=persona_bio),
    )


# ------------------------------------------------------------------
# 现有私人对话持久化（保留契约，不改变 HTTP 响应格式）
# ------------------------------------------------------------------


def append_demo_turn(
    dialogues: tuple[DialogueTurn, ...], role: str, question: str, now: datetime
) -> tuple[DialogueTurn, ...]:
    """将演示 NPC 对话追加到私人对话列表（保留现有格式契约）。

    - 结果以 DialogueTurn 存储，mode="demo"。
    - 每角色保留最近 20 轮；裁剪不影响搭档的对话。
    - 不产生公共事件，不修改游戏规则事实。
    """
    turn = DialogueTurn(
        role=role,
        question=question,
        answer=DEMO_ANSWER,
        mode="demo",
        created_at=now,
    )
    turns = (*dialogues, turn)
    # 每角色保留最近20轮；只裁剪本角色最旧轮次，伙伴的对话不受影响。
    mine = [index for index, item in enumerate(turns) if item.role == role]
    excess = len(mine) - TURNS_PER_ROLE
    if excess > 0:
        dropped = set(mine[:excess])
        turns = tuple(item for index, item in enumerate(turns) if index not in dropped)
    return turns


def append_provider_turn(
    dialogues: tuple[DialogueTurn, ...],
    role: str,
    question: str,
    response: NarrativeResponse,
    now: datetime,
) -> tuple[DialogueTurn, ...]:
    """将 Provider 生成的 NPC 对话追加到私人对话列表。

    与 append_demo_turn 共用 20 轮裁剪逻辑；
    将 response.mode 写入 DialogueTurn.mode，以便投影区分。
    """
    turn = DialogueTurn(
        role=role,
        question=question,
        answer=response.text,
        mode=response.mode,
        created_at=now,
    )
    turns = (*dialogues, turn)
    mine = [index for index, item in enumerate(turns) if item.role == role]
    excess = len(mine) - TURNS_PER_ROLE
    if excess > 0:
        dropped = set(mine[:excess])
        turns = tuple(item for index, item in enumerate(turns) if index not in dropped)
    return turns
