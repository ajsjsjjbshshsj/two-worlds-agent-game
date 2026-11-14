from dataclasses import dataclass, field
from datetime import datetime

from fastapi import Request

from twoworlds.application.identity import IdentityError
from twoworlds.domain.persistence import AccountRecord
from twoworlds.security.credentials import digest_secret


@dataclass(frozen=True)
class Authenticated:
    account: AccountRecord = field(repr=False)
    token: str = field(repr=False)
    expires_at: datetime


def session_token(request: Request) -> str:
    values = request.headers.getlist("authorization")
    if len(values) != 1:
        raise IdentityError("UNAUTHENTICATED")
    parts = values[0].split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise IdentityError("UNAUTHENTICATED")
    return parts[1]


def current_identity(request: Request) -> Authenticated:
    token = session_token(request)
    account = request.app.state.identity_service.authenticate(token)
    digest = digest_secret(token, "session")
    session = next(item for item in account.sessions if item.token_digest == digest)
    return Authenticated(account, token, session.expires_at)
