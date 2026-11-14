from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from twoworlds.domain.persistence import DisplayName


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateAccount(StrictModel):
    display_name: DisplayName


class RecoverSession(StrictModel):
    recovery_key: StrictStr = Field(min_length=1, max_length=128, repr=False)


class AccountView(StrictModel):
    id: str
    display_name: str


class SessionView(StrictModel):
    expires_at: datetime


class SessionCredential(SessionView):
    token: str = Field(repr=False)


class CurrentIdentity(StrictModel):
    account: AccountView
    session: SessionView


class RecoveredIdentity(StrictModel):
    account: AccountView
    session: SessionCredential


class CreatedIdentity(RecoveredIdentity):
    recovery_key: str = Field(repr=False)


def account_view(info):
    return AccountView(id=info.id, display_name=info.display_name)
