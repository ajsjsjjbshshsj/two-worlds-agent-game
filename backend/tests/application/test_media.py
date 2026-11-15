"""Signature/MIME mapping tests, not decoder or browser playback evidence."""

import pytest
from pydantic import ValidationError

from twoworlds.application.media import MediaContent, media_content
from twoworlds.content.schema import MediaAsset


def asset(kind, suffix):
    return MediaAsset(
        id="test_media",
        kind=kind,
        content_version="1.0.0",
        audience="a",
        scene_ids=("calibration",),
        path="test/asset" + suffix,
        alt_text="Test-only media",
        source="Synthetic test-only header",
        license="Test-only; no production license claim",
    )


@pytest.mark.parametrize(
    "kind,suffix,header,mime",
    [
        ("image", ".png", b"\x89PNG\r\n\x1a\n", "image/png"),
        ("image", ".jpg", b"\xff\xd8\xff", "image/jpeg"),
        ("image", ".jpeg", b"\xff\xd8\xff", "image/jpeg"),
        ("image", ".webp", b"RIFF\x04\x00\x00\x00WEBP", "image/webp"),
        ("ambience", ".wav", b"RIFF\x04\x00\x00\x00WAVE", "audio/wav"),
        ("sfx", ".ogg", b"OggS", "audio/ogg"),
        ("sfx", ".mp3", b"ID3", "audio/mpeg"),
        ("sfx", ".mp3", b"\xff\xfb", "audio/mpeg"),
        ("sfx", ".m4a", b"\x00\x00\x00\x10ftypM4A \x00\x00\x00\x00", "audio/mp4"),
    ],
)
def test_allowlisted_metadata_and_header_mapping(kind, suffix, header, mime):
    assert media_content(asset(kind, suffix), header) == MediaContent(header, mime)
    assert media_content(asset(kind, suffix), b"<html>not media</html>") is None
    assert media_content(asset(kind, suffix), b"") is None


@pytest.mark.parametrize(
    "kind,suffix",
    [
        ("image", ".svg"),
        ("image", ".html"),
        ("sfx", ".exe"),
        ("sfx", ".mp4"),
        ("image", ".wav"),
    ],
)
def test_unsupported_formats_rejected_by_existing_schema(kind, suffix):
    with pytest.raises(ValidationError):
        asset(kind, suffix)


def test_defensive_allowlist_rejects_bypassed_metadata_and_wrong_container():
    image = asset("image", ".png")
    assert (
        media_content(image.model_copy(update={"path": "test/asset.exe"}), b"MZ")
        is None
    )
    assert media_content(image.model_copy(update={"kind": "html"}), b"<html>") is None
    assert media_content(asset("image", ".webp"), b"RIFF\x04\x00\x00\x00WAVE") is None
    assert media_content(asset("sfx", ".wav"), b"RIFF\x04\x00\x00\x00WEBP") is None
    assert media_content(asset("sfx", ".m4a"), b"\x00\x00\x00\xffftypM4A ") is None
