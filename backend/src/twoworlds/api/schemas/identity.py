from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from twoworlds.domain.persistence import DisplayName, Email
from twoworlds.security.passwords import Password


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RequestCode(StrictModel):
    email: Email
    purpose: Literal["register", "reset"]


class RegisterAccount(StrictModel):
    email: Email
    code: StrictStr = Field(pattern=r"^[0-9]{6}$")
    password: Password = Field(repr=False)
    display_name: DisplayName


class Login(StrictModel):
    email: Email
    password: StrictStr = Field(min_length=1, max_length=1024, repr=False)


class ResetPassword(StrictModel):
    email: Email
    code: StrictStr = Field(pattern=r"^[0-9]{6}$")
    new_password: Password = Field(repr=False)


class AccountView(StrictModel):
    id: str
    email: str
    display_name: str


class SessionView(StrictModel):
    expires_at: datetime


class IdentityView(StrictModel):
    account: AccountView
    session: SessionView


class CodeAccepted(StrictModel):
    status: Literal["accepted"] = "accepted"


def account_view(info):
    return AccountView(id=info.id, email=info.email, display_name=info.display_name)
