"""A fixed media response allowlist, independent of HTTP and filesystem access."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from twoworlds.content.schema import MediaAsset


@dataclass(frozen=True)
class MediaContent:
    body: bytes
    content_type: str


def media_content(asset: MediaAsset, raw: bytes) -> MediaContent | None:
    """Check trusted metadata and a format signature; this is not a media decoder."""
    suffix = PurePosixPath(asset.path).suffix.lower()
    if asset.kind == "image":
        formats = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
    elif asset.kind in {"ambience", "sfx", "narration"}:
        formats = {
            ".mp3": "audio/mpeg",
            ".ogg": "audio/ogg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
        }
    else:
        return None
    mime = formats.get(suffix)
    valid = {
        "image/png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": raw.startswith(b"\xff\xd8\xff"),
        "image/webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP",
        "audio/wav": raw.startswith(b"RIFF") and raw[8:12] == b"WAVE",
        "audio/ogg": raw.startswith(b"OggS"),
        "audio/mpeg": raw.startswith(b"ID3")
        or (len(raw) >= 2 and raw[0] == 0xFF and raw[1] & 0xE0 == 0xE0),
        "audio/mp4": len(raw) >= 16
        and raw[4:8] == b"ftyp"
        and 16 <= int.from_bytes(raw[:4], "big") <= len(raw),
    }
    return MediaContent(raw, mime) if mime and valid[mime] else None
