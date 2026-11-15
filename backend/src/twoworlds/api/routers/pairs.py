from fastapi import APIRouter, Body, Depends, Request

from twoworlds.api.auth import Authenticated, current_identity
from twoworlds.api.schemas.pairs import (
    EmptyPairRequest,
    InvitationView,
    JoinedPairView,
    JoinPair,
    PairSummary,
)

router = APIRouter()


def _invitation(result):
    return InvitationView(
        id=result.id,
        invite_token=result.invite_token,
        invite_expires_at=result.invite_expires_at,
    )


@router.post("/api/pairs", response_model=InvitationView)
def create_pair(
    request: Request,
    body: EmptyPairRequest | None = Body(default=None),
    identity: Authenticated = Depends(current_identity),
):
    return _invitation(request.app.state.pair_service.create_pair(identity.account.id))


@router.post("/api/pairs/{pair_id}/invite", response_model=InvitationView)
def refresh_invite(
    pair_id: str,
    request: Request,
    body: EmptyPairRequest | None = Body(default=None),
    identity: Authenticated = Depends(current_identity),
):
    return _invitation(
        request.app.state.pair_service.refresh_invite(identity.account.id, pair_id)
    )


@router.post("/api/pairs/join", response_model=JoinedPairView)
def join_pair(
    body: JoinPair,
    request: Request,
    identity: Authenticated = Depends(current_identity),
):
    result = request.app.state.pair_service.join_pair(
        identity.account.id, body.invite_token
    )
    return JoinedPairView(id=result.id)


@router.get("/api/pairs", response_model=list[PairSummary])
def list_pairs(request: Request, identity: Authenticated = Depends(current_identity)):
    return [
        PairSummary(id=pair.id, role=pair.role, member_count=pair.member_count)
        for pair in request.app.state.pair_service.list_pairs(identity.account.id)
    ]
