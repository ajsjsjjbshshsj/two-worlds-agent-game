"""Ephemeral command audio, emitted only after the state/receipt CAS succeeds."""

from typing import Annotated

from pydantic import Field, StrictInt

from twoworlds.content.schema import ContentModel, Identifier
from twoworlds.domain.audio import operation_sounds
from twoworlds.domain.models import DomainEvent
from twoworlds.domain.projection import PlayerSnapshot


class OperationAudio(ContentModel):
    # Save identity scopes this monotonically unique receipt version; no raw
    # device values, actor IDs, request contents or hidden event text are sent.
    accepted_version: Annotated[StrictInt, Field(gt=0)]
    cue_id: Identifier
    asset_id: Identifier


def project_operation_audio(
    snapshot: PlayerSnapshot, events: tuple[DomainEvent, ...]
) -> tuple[OperationAudio, ...]:
    devices = {
        event.subject_id
        for event in events
        if event.kind == "device_changed"
        and event.audience == snapshot.role
        and event.version == snapshot.version
    }
    policy = operation_sounds(snapshot.script_id)
    return tuple(
        OperationAudio(
            accepted_version=snapshot.version, cue_id=cue.id, asset_id=asset.asset_id
        )
        for cue in snapshot.presentation.cues
        for asset in cue.assets
        if asset.kind == "sfx"
        and asset.asset_id in snapshot.presentation.operation_sfx
        and policy.get(asset.asset_id) in devices
    )
