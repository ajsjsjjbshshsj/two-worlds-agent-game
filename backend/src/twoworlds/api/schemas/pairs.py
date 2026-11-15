from datetime import datetime
from typing import Literal

from pydantic import Field, StrictStr

from .identity import StrictModel


class EmptyPairRequest(StrictModel):
    pass


class JoinPair(StrictModel):
    invite_token: StrictStr = Field(min_length=1, max_length=128, repr=False)


class InvitationView(StrictModel):
    id: str
    role: Literal["a"] = "a"
    invite_token: str = Field(repr=False)
    invite_expires_at: datetime


class JoinedPairView(StrictModel):
    id: str
    role: Literal["b"] = "b"


class PairSummary(StrictModel):
    id: str
    role: Literal["a", "b"]
    member_count: Literal[1, 2]
