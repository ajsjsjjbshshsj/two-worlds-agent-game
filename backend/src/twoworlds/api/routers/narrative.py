"""Authenticated sharing choice, bound to the current provider disclosure."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import StrictBool

from twoworlds.api.auth import Authenticated, current_identity
from twoworlds.content.schema import ContentModel
from twoworlds.domain.persistence import Digest

router = APIRouter()


class ConsentChoice(ContentModel):
    allow: StrictBool
    disclosure: Digest | None = None


class ConsentView(ContentModel):
    available: bool
    allowed: bool
    has_consent: bool
    destination: str | None = None
    model: str | None = None
    disclosure: Digest | None = None


def _view(gateway, account):
    config = gateway.config if gateway else None
    return ConsentView(
        available=config is not None,
        allowed=bool(gateway and gateway.has_consent(account)),
        has_consent=account.narrative_consent is not None,
        destination=config.destination if config else None,
        model=config.model if config else None,
        disclosure=config.disclosure if config else None,
    )


@router.get("/api/narrative_consent", response_model=ConsentView)
def read_consent(request: Request, identity: Authenticated = Depends(current_identity)):
    return _view(request.app.state.narrative_gateway, identity.account)


@router.post("/api/narrative_consent", response_model=ConsentView)
def change_consent(
    body: ConsentChoice,
    request: Request,
    identity: Authenticated = Depends(current_identity),
):
    gateway = request.app.state.narrative_gateway
    if body.allow and (gateway is None or body.disclosure != gateway.config.disclosure):
        raise HTTPException(status_code=409)
    account = request.app.state.identity_service.set_narrative_consent(
        identity.token, gateway.config.disclosure if body.allow else None
    )
    return _view(gateway, account)
