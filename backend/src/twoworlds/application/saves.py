"""Authorized save lifecycle; only published, pinned content enters the engine."""

from datetime import datetime, timezone
from functools import wraps
import secrets
from typing import Callable

from pydantic import TypeAdapter, ValidationError

from twoworlds.application.audio import OperationAudio, project_operation_audio
from twoworlds.application.media import MediaContent, media_content
from twoworlds.application.commands import (
    AcceptedReceipt,
    CommandError,
    GameCommand,
    ReceiptFound,
    ReceiptMissing,
)

from twoworlds.content.publication import PublicationError, PublicationStore
from twoworlds.content.schema import (
    ContentModel,
    Identifier,
    Role,
    ScriptMetadata,
    Version,
)
from twoworlds.domain.engine import apply_command, create_initial_state
from twoworlds.domain.errors import DomainError
from twoworlds.domain.persistence import CommandReceipt, SaveRecord, UTCDateTime
from twoworlds.domain.projection import PlayerSnapshot, project_save
from twoworlds.domain.recap import PublicHistory, append_public_history
from twoworlds.ports.repository import (
    DuplicateRecord,
    ReceiptLimitReached,
    Repository,
    RepositoryError,
)


class SaveError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(
            {
                "SAVE_NOT_FOUND": "存档不存在或无法访问。",
                "MEDIA_NOT_FOUND": "媒体不存在或当前无法访问。",
                "SCRIPT_NOT_FOUND": "指定的已发布剧本版本不存在。",
                "SCRIPT_VERSION_CONFLICT": "已有存档绑定另一内容版本。",
                "SCRIPT_UNSUPPORTED": "该剧本暂不支持游戏初始化。",
                "CONTENT_UNAVAILABLE": "已发布内容暂不可用。",
                "INVALID_SAVE": "存档暂时无法读取。",
                "DEPENDENCY_UNAVAILABLE": "存档存储暂不可用。",
                "GENERATION_FAILED": "无法生成存档标识。",
                "CLOCK_ERROR": "存档服务时间无效。",
            }[code]
        )


class SaveSnapshot(PlayerSnapshot):
    """Only safe PlayerSnapshot fields plus the authorized resource identity."""

    id: Identifier
    pair_id: Identifier


class SaveSummary(ContentModel):
    id: Identifier
    pair_id: Identifier
    script_id: Identifier
    script_version: Version
    version: int
    scene_id: Identifier
    completed: bool
    role: Role
    created_at: UTCDateTime
    updated_at: UTCDateTime


class CommandResponse(ContentModel):
    audio_events: tuple[OperationAudio, ...] = ()
    receipt: AcceptedReceipt
    save: SaveSnapshot


def _fail_safely(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except RepositoryError:
            raise SaveError("DEPENDENCY_UNAVAILABLE") from None
        except PublicationError as error:
            code = (
                "SCRIPT_NOT_FOUND"
                if error.code == "PUBLICATION_NOT_FOUND"
                else "CONTENT_UNAVAILABLE"
            )
            raise SaveError(code) from None
        except DomainError as error:
            code = (
                "SCRIPT_UNSUPPORTED"
                if error.code == "SCRIPT_UNSUPPORTED"
                else "INVALID_SAVE"
            )
            raise SaveError(code) from None

    return wrapped


class SaveService:
    def __init__(
        self,
        repository: Repository,
        publication_store: PublicationStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._repository = repository
        self._publications = publication_store
        self._clock = clock

    def _role(self, actor_id, pair_id):
        pair = self._repository.get_pair(pair_id)
        if pair is None or actor_id not in (pair.member_a, pair.member_b):
            raise SaveError("SAVE_NOT_FOUND")
        return pair, "a" if pair.member_a == actor_id else "b"

    def _snapshot(self, save, role):
        # Never look up 'latest': an old save must use its exact sealed version.
        script = self._publications.load(save.script_id, save.script_version)
        snapshot = project_save(save.state, script, role, save.public_history)
        return SaveSnapshot(id=save.id, pair_id=save.pair_id, **snapshot.model_dump())

    @_fail_safely
    def catalog(self) -> tuple[ScriptMetadata, ...]:
        return self._publications.catalog()

    @_fail_safely
    def create_save(self, actor_id, pair_id, script_id, script_version) -> SaveSnapshot:
        pair, role = self._role(actor_id, pair_id)
        script = self._publications.load(script_id, script_version)
        state = create_initial_state(script)
        try:
            now = TypeAdapter(UTCDateTime).validate_python(self._clock())
        except Exception:
            raise SaveError("CLOCK_ERROR") from None
        if now < pair.updated_at:
            raise SaveError("CLOCK_ERROR")
        for _ in range(8):
            candidate = SaveRecord(
                id="save_" + secrets.token_hex(16),
                pair_id=pair_id,
                script_id=script_id,
                script_version=script_version,
                version=0,
                state=state,
                public_history=PublicHistory(
                    script_id=script_id,
                    script_version=script_version,
                ),
                created_at=now,
                updated_at=now,
            )
            try:
                # The repository, not a check-then-insert in this service, decides
                # which concurrent creator owns the unique pair/story record.
                saved = self._repository.create_save(candidate)
            except DuplicateRecord:
                continue
            if saved.script_version != script_version:
                raise SaveError("SCRIPT_VERSION_CONFLICT")
            return self._snapshot(saved, role)
        raise SaveError("GENERATION_FAILED")

    @_fail_safely
    def read_save(self, actor_id, save_id) -> SaveSnapshot:
        save = self._repository.get_save(save_id)
        if save is None:
            raise SaveError("SAVE_NOT_FOUND")
        _, role = self._role(actor_id, save.pair_id)
        return self._snapshot(save, role)

    @_fail_safely
    def read_media(self, actor_id, save_id, asset_id) -> MediaContent:
        save, _, role = self._authorized_save(actor_id, save_id)
        script = self._publications.load(save.script_id, save.script_version)
        snapshot = project_save(save.state, script, role, save.public_history)
        presentation = snapshot.presentation
        visible = {asset.asset_id for cue in presentation.cues for asset in cue.assets}
        if presentation.background is not None:
            visible.add(presentation.background.asset_id)
        # Projection is the single authorization policy, including cue conditions.
        # Unknown and hidden IDs fail identically before any asset lookup/read.
        if asset_id not in visible:
            raise SaveError("MEDIA_NOT_FOUND")
        asset = next(asset for asset in script.media if asset.id == asset_id)
        raw = self._publications.read_media(
            save.script_id, save.script_version, asset_id
        )
        content = media_content(asset, raw)
        if content is None:
            raise SaveError("CONTENT_UNAVAILABLE")
        return content

    @_fail_safely
    def list_saves(self, actor_id, pair_id=None) -> tuple[SaveSummary, ...]:
        if pair_id is not None:
            pairs = (self._role(actor_id, pair_id)[0],)
        else:
            pairs = self._repository.list_pairs_for_member(actor_id)
        result = []
        for pair in pairs:
            _, role = self._role(actor_id, pair.id)
            for save in self._repository.list_saves_for_pair(pair.id):
                # A repository bug must not turn a mismatched row into a disclosure.
                if save.pair_id != pair.id:
                    raise SaveError("INVALID_SAVE")
                result.append(
                    SaveSummary(
                        id=save.id,
                        pair_id=save.pair_id,
                        script_id=save.script_id,
                        script_version=save.script_version,
                        version=save.version,
                        scene_id=save.state.scene_id,
                        completed=save.state.completed,
                        role=role,
                        created_at=save.created_at,
                        updated_at=save.updated_at,
                    )
                )
        return tuple(sorted(result, key=lambda save: save.id))

    def _authorized_save(self, actor_id, save_id):
        save = self._repository.get_save(save_id)
        if save is None:
            raise SaveError("SAVE_NOT_FOUND")
        pair, role = self._role(actor_id, save.pair_id)
        return save, pair, role

    @staticmethod
    def _receipt(save, actor_id, request_id):
        # The save is the namespace: the same actor/UUID in another save is
        # independent. There is no account-wide or global receipt registry.
        # State and receipts come from one aggregate read, avoiding a receipt
        # from a later version being paired with an earlier snapshot.
        return next(
            (
                r
                for r in save.receipts
                if r.actor_id == actor_id and r.request_id == request_id
            ),
            None,
        )

    def _duplicate(self, save, role, actor_id, command, fingerprint):
        receipt = self._receipt(save, actor_id, command.request_id)
        if receipt is None:
            return None
        if receipt.fingerprint != fingerprint:
            raise CommandError("REQUEST_ID_REUSED")
        return CommandResponse(
            receipt=AcceptedReceipt(
                request_id=receipt.request_id,
                accepted_version=receipt.accepted_version,
                duplicate=True,
            ),
            save=self._snapshot(save, role),
        )

    @_fail_safely
    def submit_command(
        self, actor_id, save_id, command: GameCommand
    ) -> CommandResponse:
        if not isinstance(command, GameCommand):
            raise CommandError("INVALID_COMMAND")
        try:
            command = GameCommand.model_validate(command.model_dump(warnings=False))
        except (ValidationError, TypeError, ValueError):
            raise CommandError("INVALID_COMMAND") from None
        current, pair, role = self._authorized_save(actor_id, save_id)
        fingerprint = command.fingerprint()
        duplicate = self._duplicate(current, role, actor_id, command, fingerprint)
        if duplicate is not None:
            return duplicate
        if command.expected_version != current.version:
            raise CommandError("VERSION_CONFLICT")
        if current.version == 512:
            raise CommandError("SAVE_COMMAND_LIMIT")
        if pair.member_b is None:
            raise CommandError("PAIR_NOT_READY")
        try:
            now = TypeAdapter(UTCDateTime).validate_python(self._clock())
        except Exception:
            raise SaveError("CLOCK_ERROR") from None
        if now < max(current.updated_at, pair.updated_at):
            raise SaveError("CLOCK_ERROR")
        script = self._publications.load(current.script_id, current.script_version)
        try:
            state, events = apply_command(
                current.state,
                script,
                role,
                {
                    "kind": command.kind,
                    "args": command.args,
                },
            )
        except DomainError as error:
            if error.code in {
                "INVALID_STATE",
                "INVALID_SCRIPT",
                "SCRIPT_MISMATCH",
                "SCRIPT_UNSUPPORTED",
            }:
                raise
            raise CommandError(error.code) from None
        history = append_public_history(
            current.public_history, script, state.version, events
        )
        receipt = CommandReceipt(
            actor_id=actor_id,
            request_id=command.request_id,
            fingerprint=fingerprint,
            accepted_version=state.version,
            created_at=now,
        )
        candidate = SaveRecord.model_validate(
            current.model_dump()
            | {
                "state": state,
                "public_history": history,
                "version": state.version,
                "receipts": (*current.receipts, receipt),
                "updated_at": now,
            }
        )
        # Validate the outgoing projection before any commit. No raw rule events
        # or hidden state are placed in the response, including on CAS failure.
        snapshot = self._snapshot(candidate, role)
        try:
            accepted = self._repository.compare_and_swap_save(
                save_id, current.version, candidate
            )
        except ReceiptLimitReached:
            raise CommandError("SAVE_COMMAND_LIMIT") from None
        if accepted:
            return CommandResponse(
                audio_events=project_operation_audio(snapshot, events),
                receipt=AcceptedReceipt(
                    request_id=receipt.request_id,
                    accepted_version=receipt.accepted_version,
                    duplicate=False,
                ),
                save=snapshot,
            )
        latest, _, role = self._authorized_save(actor_id, save_id)
        duplicate = self._duplicate(latest, role, actor_id, command, fingerprint)
        if duplicate is not None:
            return duplicate
        # Never re-execute an action against a new version automatically.
        raise CommandError("VERSION_CONFLICT")

    @_fail_safely
    def get_receipt(
        self, actor_id, save_id, request_id
    ) -> ReceiptFound | ReceiptMissing:
        save, _, _ = self._authorized_save(actor_id, save_id)
        receipt = self._receipt(save, actor_id, request_id)
        if receipt is None:
            return ReceiptMissing()
        return ReceiptFound(
            request_id=receipt.request_id, accepted_version=receipt.accepted_version
        )
