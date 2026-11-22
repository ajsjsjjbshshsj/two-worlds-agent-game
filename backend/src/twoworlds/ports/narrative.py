"""NarrativeProvider 端口：AI NPC 文本生成的唯一安全边界。

设计原则
---------
1. NarrativeContext 是 Provider 允许接收的**唯一**数据来源。
   服务端根据当前身份、存档、角色和已授权内容显式构造；
   不得把完整 SaveRecord 序列化后交给 Provider 再依赖 Prompt 过滤。

2. 显式字段白名单：只列出允许进入上下文的字段，
   未列出的字段（搭档秘密、认证令牌、数据库对象等）不得出现。

3. 不可变、可序列化的数据传输对象（frozen Pydantic 模型）。

4. Provider 不能接收数据库连接、仓储对象、规则服务或会话 Cookie；
   不能直接修改游戏状态。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Annotated, Literal

from pydantic import Field, StrictStr, StringConstraints

from twoworlds.content.schema import ContentModel, Identifier, Text, Version

# ------------------------------------------------------------------
# 白名单字段类型
# ------------------------------------------------------------------

#: NPC 人设中的简短描述文本（≤ 500 字）
NpcBio = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]

#: 玩家问题：与 persistence.Question 相同的约束
NarrativeQuestion = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]

# ------------------------------------------------------------------
# 白名单上下文子结构
# ------------------------------------------------------------------


class AllowedClue(ContentModel):
    """当前角色已被授权看到的线索（已发现或已公开分享）。"""

    model_config = {"frozen": True}

    id: Identifier
    text: Text


class AllowedDeviceField(ContentModel):
    """当前角色被允许观察的设备字段值。"""

    model_config = {"frozen": True}

    id: Identifier
    value: object  # Scalar；保持宽松以免引入内部依赖


class AllowedDevice(ContentModel):
    """当前角色被允许观察的设备（仅本人设备）。"""

    model_config = {"frozen": True}

    id: Identifier
    fields: tuple[AllowedDeviceField, ...]


class AllowedMilestone(ContentModel):
    """已公开的剧情里程碑（通过 public_history 派生）。"""

    model_config = {"frozen": True}

    kind: Identifier
    subject_id: Identifier


class AllowedDialogueTurn(ContentModel):
    """当前角色最近的私人 NPC 对话轮次（最多 20 轮）。

    注意：只包含本人的 question/answer，不含 role 字段，
    避免暴露记录的角色归属给 Provider。
    """

    model_config = {"frozen": True}

    question: NarrativeQuestion
    answer: Text
    mode: Literal["demo", "provider", "fallback"]


class NpcPersona(ContentModel):
    """公开 NPC 人设与叙事风格（从剧本元数据中摘取）。"""

    model_config = {"frozen": True}

    name: Identifier
    bio: NpcBio


# ------------------------------------------------------------------
# NarrativeContext：Provider 允许接收的完整上下文
# ------------------------------------------------------------------


class NarrativeContext(ContentModel):
    """AI Provider 唯一允许接收的游戏上下文。

    **只允许包含的字段（白名单）：**
    1. 当前剧本 ID 和版本。
    2. 当前场景 ID。
    3. 当前角色身份（"a" 或 "b"）。
    4. 当前角色已发现的个人线索。
    5. 双方已公开的线索。
    6. 当前角色被允许观察的设备状态（仅本人设备）。
    7. 已公开的剧情里程碑。
    8. 当前角色最近最多 20 轮私人 NPC 对话。
    9. 当前玩家发送的问题。
    10. 必要的公开 NPC 人设和叙事风格。

    **禁止包含：**
    - 搭档尚未公开的私人线索或设备状态。
    - 搭档的 NPC 私聊历史。
    - 其他存档的任何私人信息。
    - 完整谜底或隐藏规则答案。
    - 服务端完整 SaveRecord 或数据库对象。
    - Cookie、Token、密码、邀请令牌。
    - 内部请求回执或其他玩家的 UUID。
    - 未经授权的媒体资源。
    """

    model_config = {"frozen": True}

    # 1. 剧本身份
    script_id: Identifier
    script_version: Version

    # 2. 当前场景
    scene_id: Identifier

    # 3. 当前角色身份
    role: Literal["a", "b"]

    # 4. 当前角色已发现的个人线索
    personal_clues: tuple[AllowedClue, ...]

    # 5. 双方已公开的线索（通过游戏规则正式分享后才进入此列表）
    shared_clues: tuple[AllowedClue, ...]

    # 6. 当前角色被允许观察的设备状态（仅本角色的设备）
    personal_devices: tuple[AllowedDevice, ...]

    # 7. 已公开的剧情里程碑
    public_milestones: tuple[AllowedMilestone, ...]

    # 8. 当前角色最近最多 20 轮私人 NPC 对话
    recent_dialogue: Annotated[tuple[AllowedDialogueTurn, ...], Field(max_length=20)]

    # 9. 当前玩家发送的问题
    question: NarrativeQuestion

    # 10. NPC 人设与叙事风格
    persona: NpcPersona


# ------------------------------------------------------------------
# NarrativeRequest / NarrativeResponse：Provider 的输入输出
# ------------------------------------------------------------------


class NarrativeRequest(ContentModel):
    """Provider 接收的请求；携带上下文和可扩展元数据。

    prompt_version 为未来 Prompt 版本管理预留。
    """

    model_config = {"frozen": True}

    context: NarrativeContext
    prompt_version: StrictStr = "1.0"


class NarrativeResponse(ContentModel):
    """Provider 返回的响应；只含叙事文本和最小元信息。

    **不含：**
    - 游戏状态修改指令。
    - 任何搭档秘密。
    - 完整谜底。

    usage 为未来 token 计量预留，timeout_ms 为超时追踪预留。
    """

    model_config = {"frozen": True}

    text: Text
    mode: Literal["demo", "provider", "fallback"]
    provider_name: Identifier
    prompt_version: StrictStr = "1.0"
    # 预留：未来 usage 计量
    usage: dict[str, int] = {}
    # 预留：未来超时追踪（毫秒）
    timeout_ms: int | None = None
    # 预留：未来错误码（None 表示正常）
    error_code: str | None = None


# ------------------------------------------------------------------
# NarrativeProvider 抽象
# ------------------------------------------------------------------


class NarrativeProvider(ABC):
    """NPC 叙事文本生成 Provider 的抽象接口。

    **约束：**
    - 只接收 NarrativeRequest（携带 NarrativeContext），不接收原始存档或数据库对象。
    - 不能直接修改游戏状态；叙事文本是纯输出。
    - 实现必须声明自己的 provider_name 和 mode。
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider 标识符，用于日志和 NarrativeResponse.provider_name。"""

    @property
    @abstractmethod
    def mode(self) -> Literal["demo", "provider", "fallback"]:
        """当前 Provider 模式。"""

    @abstractmethod
    def generate(self, request: NarrativeRequest) -> NarrativeResponse:
        """根据 NarrativeContext 生成 NPC 叙事文本。

        必须满足：
        - 不调用外部网络（demo 模式）或通过 API Key 调用（provider 模式）。
        - 不访问数据库或仓储。
        - 不修改任何游戏状态。
        - 返回稳定的 NarrativeResponse。
        """
