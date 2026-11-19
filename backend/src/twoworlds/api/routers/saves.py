from fastapi import APIRouter, Depends, Request, Response

from twoworlds.api.auth import Authenticated, current_identity
from twoworlds.api.schemas.saves import CreateSave
from twoworlds.api.schemas.commands import SubmitCommand
from twoworlds.application.commands import RequestId, ReceiptFound, ReceiptMissing
from twoworlds.application.saves import (
    CommandResponse,
    SaveSnapshot,
    SaveSummary,
    VoiceStatus,
)
from twoworlds.content.schema import ScriptMetadata

router = APIRouter()


@router.get("/api/scripts", response_model=list[ScriptMetadata])
def scripts(request: Request):
    return request.app.state.save_service.catalog()


@router.post("/api/saves", response_model=SaveSnapshot)
def create_save(
    body: CreateSave,
    request: Request,
    identity: Authenticated = Depends(current_identity),
):
    return request.app.state.save_service.create_save(
        identity.account.id,
        body.pair_id,
        body.script_id,
        body.script_version,
    )


@router.get("/api/saves", response_model=list[SaveSummary])
def list_saves(
    request: Request,
    pair_id: str | None = None,
    identity: Authenticated = Depends(current_identity),
):
    return request.app.state.save_service.list_saves(identity.account.id, pair_id)


@router.get("/api/saves/{save_id}", response_model=SaveSnapshot)
def read_save(
    save_id: str, request: Request, identity: Authenticated = Depends(current_identity)
):
    return request.app.state.save_service.read_save(identity.account.id, save_id)


@router.get("/api/saves/{save_id}/media/{asset_id}")
def read_media(
    save_id: str,
    asset_id: str,
    request: Request,
    identity: Authenticated = Depends(current_identity),
):
    content = request.app.state.save_service.read_media(
        identity.account.id, save_id, asset_id
    )
    # Range/conditional headers do not bypass authorization or create cached 304s.
    return Response(
        content.body,
        media_type=content.content_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/api/saves/{save_id}/commands", response_model=CommandResponse)
def submit_command(
    save_id: str,
    body: SubmitCommand,
    request: Request,
    identity: Authenticated = Depends(current_identity),
):
    return request.app.state.save_service.submit_command(
        identity.account.id, save_id, body
    )


@router.get("/api/saves/{save_id}/voice", response_model=VoiceStatus)
def voice_status(
    save_id: str, request: Request, identity: Authenticated = Depends(current_identity)
):
    return request.app.state.save_service.voice_status(identity.account.id, save_id)


@router.get(
    "/api/saves/{save_id}/receipts/{request_id}",
    response_model=ReceiptFound | ReceiptMissing,
)
def get_receipt(
    save_id: str,
    request_id: RequestId,
    request: Request,
    identity: Authenticated = Depends(current_identity),
):
    return request.app.state.save_service.get_receipt(
        identity.account.id, save_id, request_id
    )
