"""包内草稿/已发布内容的有界生命周期；不提供HTTP、玩家鉴权或发布写接口。"""

from contextlib import contextmanager
from dataclasses import replace
import base64
from importlib import resources
from importlib.metadata import files, PackageNotFoundError

from ._publication_files import canonical_root, safe_path
from .loader import ScriptLoader
from .publication import PublicationStore, audit_media


class PackagedContent:
    def __init__(self, root):
        self._root = canonical_root(root)
        self._published = PublicationStore(safe_path(self._root, "published"))

    def load_draft(self, script_id, version):
        """开发/审核用途；读到草稿绝不表示该版本已发布或可游玩。"""
        return ScriptLoader(safe_path(self._root, "scripts")).load(script_id, version)

    def load_published(self, script_id, version):
        return self._published.load(script_id, version)

    def catalog(self):
        return self._published.catalog()

    def read_published_media(self, script_id, version, asset_id):
        return self._published.read_media(script_id, version, asset_id)

    def audit_draft(self, script_id, version):
        script = self.load_draft(script_id, version)
        try:
            root = safe_path(self._root, "assets")
        except FileNotFoundError:
            root = self._root / "assets"
        checks = audit_media(script, root)
        return self._packaging_status(checks, "assets/")

    def audit_published(self, script_id, version):
        checks = self._published.audit(script_id, version)
        return self._packaging_status(
            checks, f"published/{script_id}/{version}/assets/"
        )

    def _packaging_status(self, checks, prefix):
        try:
            members = {str(item): item for item in files("twoworlds-api") or ()}
        except PackageNotFoundError:
            members = None
        result = []
        for item in checks:
            included = False
            if item.file_present:
                member = (
                    members.get(f"twoworlds/content/{prefix}{item.path}")
                    if members is not None
                    else None
                )
                if members is None:
                    included = None
                elif (
                    member is not None
                    and member.hash is not None
                    and member.hash.mode == "sha256"
                ):
                    recorded = base64.urlsafe_b64decode(member.hash.value + "==").hex()
                    included = recorded == item.sha256
            result.append(replace(item, included_in_package=included))
        return tuple(result)


@contextmanager
def packaged_content():
    # Python3.12支持目录as_file；zip临时提取的路径只在with范围内有效。
    # 不写死开发机路径、不改sys.path、不放宽现有加载器的严格路径解析。
    with resources.as_file(resources.files("twoworlds.content")) as root:
        yield PackagedContent(root)
