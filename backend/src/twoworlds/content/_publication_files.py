"""发布层的有限文件操作；配置根受信任，拒绝链接、越界和无限读取。"""

import json
import os
from pathlib import Path
import re
import stat

from .loader import _reject_constant, _unique_object

MAX_MEDIA_BYTES = 32 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024


class PublicationError(ValueError):
    """只暴露稳定分类，不在默认错误中附加正文、私有路径或底层异常。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical_root(root: str | Path) -> Path:
    try:
        path = Path(root).resolve(strict=True)
        if path.is_dir():
            return path
    except (OSError, RuntimeError, TypeError):
        pass
    raise PublicationError("PUBLICATION_INVALID_ROOT")


def canonical_relative(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 1024
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", value)
        or any(
            part in {"", ".", ".."} or part.endswith(".") for part in value.split("/")
        )
    ):
        raise PublicationError("PUBLICATION_PATH_FORBIDDEN")
    return value


def safe_path(root: Path, relative: str) -> Path:
    """root已是规范绝对目录；即便链接仍指向根内，也不作为发布输入接受。"""
    canonical_relative(relative)
    candidate = root / relative
    try:
        current = root
        for part in relative.split("/"):
            current = current / part
            if current.is_symlink() or current.is_junction():
                raise PublicationError("PUBLICATION_PATH_FORBIDDEN")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise PublicationError("PUBLICATION_PATH_FORBIDDEN")
        return resolved
    except FileNotFoundError:
        raise
    except (OSError, RuntimeError):
        raise PublicationError("PUBLICATION_PATH_FORBIDDEN") from None


def read_bytes(root: Path, relative: str, limit: int) -> bytes:
    try:
        path = safe_path(root, relative)
        if not stat.S_ISREG(path.stat().st_mode):
            raise PublicationError("PUBLICATION_READ_FAILED")
        with path.open("rb") as source:
            raw = source.read(limit + 1)
        if len(raw) > limit:
            raise PublicationError("PUBLICATION_RESOURCE_TOO_LARGE")
        return raw
    except FileNotFoundError:
        raise
    except OSError:
        raise PublicationError("PUBLICATION_READ_FAILED") from None


def parse_document(raw: bytes):
    # 沿用加载器的严格JSON策略，不接受重复键/非有限数；保留原加载器不改。
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, RecursionError):
        raise PublicationError("PUBLICATION_INVALID_REGISTRY") from None


def write_new(path: Path, raw: bytes) -> None:
    # 只用于本次新建的目录；xb避免已有文件被覆盖，fsync在登记前刷出文件内容。
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())
