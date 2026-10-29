"""按明确的ID和版本读取受信任内容目录；不发布、不缓存、不执行规则。"""

import json
from pathlib import Path
import stat

from pydantic import TypeAdapter, ValidationError

from .schema import Identifier, ScriptVersion, Version

MAX_SCRIPT_BYTES = 1024 * 1024
_REFERENCE = TypeAdapter(tuple[Identifier, Version])
_MESSAGES = {
    "CONTENT_INVALID_ROOT": "剧本根目录必须是现有目录。",
    "CONTENT_INVALID_REFERENCE": "剧本ID或版本格式无效。",
    "CONTENT_NOT_FOUND": "找不到指定的剧本版本。",
    "CONTENT_PATH_FORBIDDEN": "剧本路径无法安全解析或超出内容根目录。",
    "CONTENT_READ_FAILED": "剧本版本不是普通文件或无法读取。",
    "CONTENT_TOO_LARGE": "剧本文件超过允许的大小。",
    "CONTENT_INVALID_JSON": "剧本必须是无重复键的有效UTF-8 JSON。",
    "CONTENT_INVALID_SCHEMA": "剧本未通过内容结构或引用校验。",
    "CONTENT_IDENTITY_MISMATCH": "文件内的剧本ID或版本与请求不匹配。",
}


class ScriptLoadError(ValueError):
    """稳定code用于程序判断；默认消息不包含内容正文或本机路径。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(_MESSAGES[code])


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    # json默认保留最后一个同名键；内容加载不允许这种隐式覆盖，包括嵌套对象。
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    # Python的JSON解析器默认接受NaN/Infinity，但它们不是标准JSON常量。
    raise ValueError("non-finite JSON constant")


class ScriptLoader:
    """root由服务端配置指定；目录与文件只读，缺版不猜测替代版本。"""

    def __init__(self, root: str | Path):
        try:
            resolved = Path(root).resolve(strict=True)
            if not resolved.is_dir():
                raise ScriptLoadError("CONTENT_INVALID_ROOT")
        except (OSError, RuntimeError, TypeError):
            raise ScriptLoadError("CONTENT_INVALID_ROOT") from None
        self._root = resolved

    def load(self, script_id: str, content_version: str) -> ScriptVersion:
        """读取root/id/version.json，依次校验路径、JSON、Schema和标识。"""
        try:
            script_id, content_version = _REFERENCE.validate_python(
                (script_id, content_version)
            )
        except ValidationError:
            raise ScriptLoadError("CONTENT_INVALID_REFERENCE") from None

        try:
            # strict=True保证解析失败时不退回未展开联接/链接的路径字符串。
            candidate = (self._root / script_id / f"{content_version}.json").resolve(
                strict=True
            )
        except FileNotFoundError:
            raise ScriptLoadError("CONTENT_NOT_FOUND") from None
        except (OSError, RuntimeError):
            raise ScriptLoadError("CONTENT_PATH_FORBIDDEN") from None
        if not candidate.is_relative_to(self._root):
            raise ScriptLoadError("CONTENT_PATH_FORBIDDEN")

        try:
            if not stat.S_ISREG(candidate.stat().st_mode):
                raise ScriptLoadError("CONTENT_READ_FAILED")
            with candidate.open("rb") as source:
                # 多读一个字节识别越界，不把超大文件整体读入内存。
                raw = source.read(MAX_SCRIPT_BYTES + 1)
        except FileNotFoundError:
            raise ScriptLoadError("CONTENT_NOT_FOUND") from None
        except OSError:
            raise ScriptLoadError("CONTENT_READ_FAILED") from None
        if len(raw) > MAX_SCRIPT_BYTES:
            raise ScriptLoadError("CONTENT_TOO_LARGE")

        try:
            data = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (UnicodeError, ValueError, RecursionError):
            raise ScriptLoadError("CONTENT_INVALID_JSON") from None
        try:
            script = ScriptVersion.model_validate(data)
        except ValidationError:
            # 不把Pydantic的原始input/错误上下文带入默认异常和普通日志。
            raise ScriptLoadError("CONTENT_INVALID_SCHEMA") from None
        if (
            script.metadata.id != script_id
            or script.metadata.content_version != content_version
        ):
            raise ScriptLoadError("CONTENT_IDENTITY_MISMATCH")
        return script
