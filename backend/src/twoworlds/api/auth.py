from dataclasses import dataclass, field
from datetime import datetime

from fastapi import Request

from twoworlds.application.identity import IdentityError
from twoworlds.domain.persistence import AccountRecord
from twoworlds.security.credentials import digest_secret

from .cookies import SESSION_COOKIE


@dataclass(frozen=True)
class Authenticated:
    account: AccountRecord = field(repr=False)
    token: str = field(repr=False)
    expires_at: datetime


def session_token(request: Request) -> str:
    # Cookie-only authentication; Authorization headers are deliberately ignored.
    values = []
    for header in request.headers.getlist("cookie"):
        for part in header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE:
                values.append(value)
    if len(values) != 1 or not values[0]:
        raise IdentityError("UNAUTHENTICATED")
    return values[0]


def current_identity(request: Request) -> Authenticated:
    token = session_token(request)
    account = request.app.state.identity_service.authenticate(token)
    digest = digest_secret(token, "session")
    session = next(item for item in account.sessions if item.token_digest == digest)
    return Authenticated(account, token, session.expires_at)
