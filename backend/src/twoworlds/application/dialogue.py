"""演示NPC私聊：应用层表达，不进入规则事实，不调用任何外部服务。"""

from twoworlds.content.schema import ContentModel
from twoworlds.domain.persistence import DialogueTurn, Question

# 固定模板回复：不回显提问、不触及谜底或搭档秘密。真实模型/LangGraph、
# 三级提示与降级标识属于后续T14，这里只兑现demo契约。
DEMO_ANSWER = (
    "（演示模式）我是示例NPC，只提供氛围陪伴与通用建议，不掌握谜底，"
    "也不会改动任何游戏事实。请观察当前场景的线索，并与搭档交换你们各自看到的信息。"
)

TURNS_PER_ROLE = 20


class TalkArgs(ContentModel):
    question: Question


def append_demo_turn(
    dialogues: tuple[DialogueTurn, ...], role: str, question: str, now
) -> tuple[DialogueTurn, ...]:
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
