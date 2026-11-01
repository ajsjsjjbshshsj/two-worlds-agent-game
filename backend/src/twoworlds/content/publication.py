"""受信任本地文件库的版本快照发布、完整性检查与纯Metadata目录。"""

from dataclasses import dataclass
import hashlib
import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal

from pydantic import (
    StrictBool,
    StrictStr,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)

from ._publication_files import (
    MAX_MEDIA_BYTES,
    MAX_RECORD_BYTES,
    PublicationError,
    canonical_relative,
    canonical_root,
    parse_document,
    read_bytes,
    safe_path,
    write_new,
)
from .loader import MAX_SCRIPT_BYTES, ScriptLoader
from .schema import (
    ContentModel,
    Identifier,
    ScriptMetadata,
    ScriptVersion,
    Text,
    Version,
)

Digest = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_REFERENCE = TypeAdapter(tuple[Identifier, Version])
_REGISTRY = {"format": "twoworlds-publications-v1"}
MAX_RELEASE_BYTES = 128 * 1024 * 1024


class MediaApproval(ContentModel):
    """审核人对特定字节作出的许可确认；不是自动版权鉴定。"""

    asset_id: Identifier
    path: StrictStr
    sha256: Digest
    license_evidence: Text


class ReleaseApproval(ContentModel):
    """JSON与全部媒体的审核快照；Metadata的自然语言仍需人工审查。"""

    script_sha256: Digest
    reviewed_by: Text
    public_metadata_reviewed: StrictBool
    media: tuple[MediaApproval, ...]


class ReleaseRecord(ReleaseApproval):
    format: Literal["twoworlds-release-v1"]
    script_id: Identifier
    content_version: Version


@dataclass(frozen=True)
class MediaStatus:
    asset_id: str
    path: str
    declared: bool
    file_present: bool
    sha256: str | None
    license_reviewed: bool
    # None=仅检查文件系统输入，无法据此宣称已进入Python包。
    included_in_package: bool | None = None


def _reference(script_id, version):
    try:
        return _REFERENCE.validate_python((script_id, version))
    except ValidationError:
        raise PublicationError("PUBLICATION_INVALID_REFERENCE") from None


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _commit_bundle(source: Path, destination: Path) -> None:
    # Windows目录在刚读写后偶发WinError5/32。仅有限重试同一次原子rename；
    # 不覆盖目标、不转逐文件复制，永久拒绝仍交给上层清理并报告失败。
    for attempt in range(5):
        try:
            os.rename(source, destination)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in {5, 32} or attempt == 4:
                raise
            time.sleep(0.01 * (attempt + 1))


def _check_resource_namespace(script: ScriptVersion) -> None:
    prefix = f"{script.metadata.id}/{script.metadata.content_version}/"
    paths = set()
    for asset in script.media:
        canonical_relative(asset.path)
        if not asset.path.startswith(prefix) or asset.path in paths:
            raise PublicationError("PUBLICATION_RESOURCE_VERSION")
        paths.add(asset.path)


def audit_media(
    script: ScriptVersion,
    asset_root: str | Path,
    approval: ReleaseApproval | None = None,
) -> tuple[MediaStatus, ...]:
    """管理侧检查：分别报告声明、文件和匹配字节的审核，不是公开目录。"""
    _check_resource_namespace(script)
    path = Path(asset_root)
    root = canonical_root(path) if path.exists() else None
    approvals = {item.asset_id: item for item in approval.media} if approval else {}
    result = []
    for asset in script.media:
        raw = None
        if root is not None:
            try:
                raw = read_bytes(root, asset.path, MAX_MEDIA_BYTES)
            except FileNotFoundError:
                pass
        seal = approvals.get(asset.id)
        digest = _hash(raw) if raw is not None else None
        reviewed = bool(
            raw
            and approval
            and approval.reviewed_by
            and seal
            and seal.path == asset.path
            and seal.sha256 == digest
            and seal.license_evidence
        )
        result.append(
            MediaStatus(asset.id, asset.path, True, raw is not None, digest, reviewed)
        )
    return tuple(result)


def _approved(
    script: ScriptVersion,
    raw: bytes,
    checks: tuple[MediaStatus, ...],
    approval: ReleaseApproval | None,
) -> ReleaseApproval:
    if any(not item.file_present for item in checks):
        raise PublicationError("PUBLICATION_MEDIA_MISSING")
    if any(item.sha256 == _hash(b"") for item in checks):
        raise PublicationError("PUBLICATION_MEDIA_EMPTY")
    if approval is None:
        raise PublicationError("PUBLICATION_APPROVAL_REQUIRED")
    try:
        # model_copy/construct可绕过Pydantic校验，发布入口重新验证外部审核对象。
        approval = ReleaseApproval.model_validate(
            approval.model_dump(mode="json", include=set(ReleaseApproval.model_fields))
        )
    except (AttributeError, ValidationError):
        raise PublicationError("PUBLICATION_APPROVAL_INVALID") from None
    if (
        not approval.public_metadata_reviewed
        or approval.script_sha256 != _hash(raw)
        or len(approval.media) != len(script.media)
        or {item.asset_id for item in approval.media}
        != {asset.id for asset in script.media}
        or not all(item.license_reviewed for item in checks)
    ):
        raise PublicationError("PUBLICATION_APPROVAL_INVALID")
    return approval


class PublicationStore:
    """构造只读打开已初始化的库；publish显式写入，load永远不回退草稿。"""

    def __init__(self, root: str | Path):
        self._root = canonical_root(root)
        self._verify_registry()

    def _verify_registry(self):
        try:
            if (
                parse_document(
                    read_bytes(self._root, "registry.json", MAX_RECORD_BYTES)
                )
                != _REGISTRY
            ):
                raise PublicationError("PUBLICATION_INVALID_REGISTRY")
        except FileNotFoundError:
            raise PublicationError("PUBLICATION_INVALID_REGISTRY") from None

    @classmethod
    def initialize(cls, root: str | Path):
        """只初始化新目录，不修补或覆盖已有库；只由内容管理工具显式调用。"""
        path = Path(root)
        try:
            path.mkdir(parents=True, exist_ok=False)
        except OSError:
            raise PublicationError("PUBLICATION_INVALID_ROOT") from None
        root = canonical_root(path)
        try:
            write_new(root / "registry.json", json.dumps(_REGISTRY).encode("utf-8"))
        except OSError:
            # 仅清理刚刚独占新建的目录/已知文件，不递归触碰调用方的其他内容。
            (root / "registry.json").unlink(missing_ok=True)
            root.rmdir()
            raise PublicationError("PUBLICATION_WRITE_FAILED") from None
        return cls(root)

    def _record(self, script_id: str, version: str):
        self._verify_registry()
        script_id, version = _reference(script_id, version)
        try:
            release = safe_path(self._root, f"{script_id}/{version}")
        except FileNotFoundError:
            raise PublicationError("PUBLICATION_NOT_FOUND") from None
        return self._validate(release, script_id, version)

    def _validate(self, release: Path, script_id: str, version: str):
        try:
            record = ReleaseRecord.model_validate(
                parse_document(read_bytes(release, "release.json", MAX_RECORD_BYTES))
            )
            if (record.script_id, record.content_version) != (script_id, version):
                raise PublicationError("PUBLICATION_INTEGRITY_MISMATCH")
            raw = read_bytes(
                release, f"scripts/{script_id}/{version}.json", MAX_SCRIPT_BYTES
            )
            if _hash(raw) != record.script_sha256:
                raise PublicationError("PUBLICATION_INTEGRITY_MISMATCH")
            # 仅解析刚刚核验的同一份字节，不在验哈希后重新打开JSON引入读写间隙。
            script = ScriptVersion.model_validate(parse_document(raw))
            if (script.metadata.id, script.metadata.content_version) != (
                script_id,
                version,
            ):
                raise PublicationError("PUBLICATION_INTEGRITY_MISMATCH")
            # 发布库的assets是快照内部目录，不能像外部配置根一样跟随链接。
            assets = safe_path(release, "assets")
            checks = audit_media(script, assets, record)
            _approved(script, raw, checks, record)
            return record, script, release
        except (FileNotFoundError, ValidationError):
            raise PublicationError("PUBLICATION_INTEGRITY_MISMATCH") from None
        except PublicationError as error:
            if error.code.startswith("PUBLICATION_APPROVAL") or error.code in {
                "PUBLICATION_MEDIA_MISSING",
                "PUBLICATION_MEDIA_EMPTY",
            }:
                raise PublicationError("PUBLICATION_INTEGRITY_MISMATCH") from None
            raise

    def load(self, script_id: str, version: str) -> ScriptVersion:
        return self._record(script_id, version)[1]

    def read_media(self, script_id: str, version: str, asset_id: str) -> bytes:
        """内部内容读取；玩家权限由后续T03/T08另行检查，不是公开媒体路由。"""
        record, _, release = self._record(script_id, version)
        seal = next((item for item in record.media if item.asset_id == asset_id), None)
        if seal is None:
            raise PublicationError("PUBLICATION_NOT_FOUND")
        raw = read_bytes(release, f"assets/{seal.path}", MAX_MEDIA_BYTES)
        if _hash(raw) != seal.sha256:
            raise PublicationError("PUBLICATION_INTEGRITY_MISMATCH")
        return raw

    def catalog(self) -> tuple[ScriptMetadata, ...]:
        self._verify_registry()
        entries = []
        for folder in self._root.iterdir():
            if folder.name.startswith(".") or folder.name == "registry.json":
                continue
            parent = safe_path(self._root, folder.name)
            if not parent.is_dir():
                raise PublicationError("PUBLICATION_INVALID_REGISTRY")
            for version in parent.iterdir():
                if version.name.startswith("."):
                    continue
                identifier, number = _reference(parent.name, version.name)
                entries.append(self.load(identifier, number).metadata)
        return tuple(
            sorted(
                entries,
                key=lambda item: (
                    item.id,
                    tuple(map(int, item.content_version.split("."))),
                ),
            )
        )

    def audit(self, script_id: str, version: str) -> tuple[MediaStatus, ...]:
        record, script, release = self._record(script_id, version)
        return audit_media(script, release / "assets", record)

    def publish(
        self,
        scripts_root: str | Path,
        assets_root: str | Path,
        script_id: str,
        version: str,
        approval: ReleaseApproval | None,
    ) -> ReleaseRecord:
        script_id, version = _reference(script_id, version)
        # 发现库中已有损坏时先拒绝继续发布；隐藏暂存和锁不是登记条目。
        self.catalog()
        lock_parent = self._root / ".locks" / script_id
        (self._root / ".locks").mkdir(exist_ok=True)
        safe_path(self._root, ".locks")
        lock_parent.mkdir(exist_ok=True)
        safe_path(self._root, f".locks/{script_id}")
        lock = lock_parent / version
        try:
            lock.mkdir()
        except FileExistsError:
            raise PublicationError("PUBLICATION_BUSY") from None
        try:
            destination = self._root / script_id / version
            if (
                destination.exists()
                or destination.is_symlink()
                or destination.is_junction()
            ):
                self.load(script_id, version)
                raise PublicationError("PUBLICATION_VERSION_EXISTS")
            scripts = canonical_root(scripts_root)
            script = ScriptLoader(scripts).load(script_id, version)
            raw = read_bytes(scripts, f"{script_id}/{version}.json", MAX_SCRIPT_BYTES)
            checks = audit_media(script, assets_root, approval)
            approval = _approved(script, raw, checks, approval)
            record = ReleaseRecord(
                **approval.model_dump(),
                format="twoworlds-release-v1",
                script_id=script_id,
                content_version=version,
            )
            # TemporaryDirectory只管理本库中新建的唯一目录；从不清理已有版本。
            with TemporaryDirectory(prefix=".stage-", dir=self._root) as temporary:
                staging = canonical_root(temporary)
                bundle = staging / "bundle"
                bundle.mkdir()
                write_new(bundle / f"scripts/{script_id}/{version}.json", raw)
                assets = canonical_root(assets_root)
                total = len(raw)
                for seal in record.media:
                    data = read_bytes(assets, seal.path, MAX_MEDIA_BYTES)
                    if _hash(data) != seal.sha256:
                        raise PublicationError("PUBLICATION_APPROVAL_INVALID")
                    total += len(data)
                    if total > MAX_RELEASE_BYTES:
                        raise PublicationError("PUBLICATION_RESOURCE_TOO_LARGE")
                    write_new(bundle / "assets" / seal.path, data)
                write_new(
                    bundle / "release.json",
                    record.model_dump_json(indent=2).encode("utf-8"),
                )
                self._validate(bundle, script_id, version)
                destination.parent.mkdir(exist_ok=True)
                # 所有发布进程遵守同一目录锁；配置根不允许不受信任的并发文件写入。
                # 同文件系统rename是唯一可见性提交点；不使用覆盖/逐个搬运回退。
                _commit_bundle(bundle, destination)
            return record
        except OSError:
            raise PublicationError("PUBLICATION_WRITE_FAILED") from None
        finally:
            lock.rmdir()
