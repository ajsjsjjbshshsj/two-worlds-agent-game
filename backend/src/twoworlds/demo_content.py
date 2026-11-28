"""Generate an isolated, explicitly test-only local demo publication bundle.

Reads the real authored story definitions but writes only synthetic PNG/WAV
placeholders and a test-only release approval. It never writes the packaged
formal publication registry. The output is intended to be mounted read-only
into the SQLite demo server; it is not production or Playtest content.
"""

import argparse
import binascii
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import wave
import zlib

from twoworlds.content import loader
from twoworlds.content.publication import (
    MediaApproval,
    PublicationStore,
    ReleaseApproval,
)

MANIFEST = "manifest.json"
MARKER = "LOCAL DEMO ONLY - SYNTHETIC TEST-ONLY - NOT FORMAL PUBLICATION"
STORIES = (("lighthouse", "1.0.0"), ("starline", "1.0.0"))


class DemoContentError(ValueError):
    pass


def _png(seed: str) -> bytes:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    width, height = 64, 48

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
        )

    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            shade = (x + y + digest[0]) % 24
            row.extend(
                (
                    min(255, digest[0] + shade),
                    min(255, digest[1] + shade),
                    min(255, digest[2] + shade),
                    255,
                )
            )
        rows.append(bytes(row))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def _wav(seed: str) -> bytes:
    frequency = 330 + hashlib.sha256(seed.encode("utf-8")).digest()[0] % 220
    rate = 8000
    frames = bytearray()
    for index in range(rate // 4):
        sample = int(9000 * math.sin(2 * math.pi * frequency * index / rate))
        frames.extend(struct.pack("<h", sample))
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(frames)
    return output.getvalue()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_demo_content(root: Path, *, force: bool = False) -> dict:
    root = Path(root).absolute()
    if root.exists():
        if not root.is_dir() or root.is_symlink():
            raise DemoContentError("Demo content root must be a real directory")
        if any(root.iterdir()):
            manifest_path = root / MANIFEST
            try:
                existing = json.loads(manifest_path.read_text("utf-8"))
            except (OSError, ValueError):
                raise DemoContentError(
                    "Demo content root is not empty; use --force only for a generated bundle"
                ) from None
            if existing.get("mode") != MARKER or not force:
                raise DemoContentError(
                    "Demo content root is not empty; use --force only for a generated bundle"
                )
            shutil.rmtree(root)

    root.parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=f".{root.name}-", dir=root.parent))
    try:
        releases = workspace / "releases"
        store = PublicationStore.initialize(releases)
        stories = []
        for identifier, version in STORIES:
            document = json.loads(
                (
                    Path(loader.__file__).parent
                    / f"scripts/{identifier}/{version}.json"
                ).read_text(encoding="utf-8")
            )
            assets_root = workspace / "assets"
            scripts_root = workspace / "scripts"
            approvals = []
            for asset in document["media"]:
                extension = "png" if asset["kind"] == "image" else "wav"
                asset["content_version"] = version
                asset["path"] = f"{identifier}/{version}/{asset['id']}.{extension}"
                asset["source"] = (
                    "Synthetic local-demo placeholder; not a formal resource"
                )
                asset["license"] = "Test-only approval; no production license claim"
                path = assets_root / asset["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                raw = _png(asset["id"]) if extension == "png" else _wav(asset["id"])
                path.write_bytes(raw)
                approvals.append(
                    MediaApproval(
                        asset_id=asset["id"],
                        path=asset["path"],
                        sha256=hashlib.sha256(raw).hexdigest(),
                        license_evidence="Synthetic local demo test-only material",
                    )
                )
            script_path = scripts_root / identifier / f"{version}.json"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            raw = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
            script_path.write_bytes(raw)
            store.publish(
                scripts_root,
                assets_root,
                identifier,
                version,
                ReleaseApproval(
                    script_sha256=hashlib.sha256(raw).hexdigest(),
                    reviewed_by="automated test fixture only",
                    public_metadata_reviewed=True,
                    media=tuple(approvals),
                ),
            )
            stories.append(dict(id=identifier, version=version, media=len(approvals)))

        files = {
            str(path.relative_to(workspace)): _sha(path)
            for path in sorted(workspace.rglob("*"))
            if path.is_file()
        }
        manifest = dict(
            mode=MARKER,
            created_at=datetime.now(timezone.utc).isoformat(),
            generator="twoworlds.demo_content",
            stories=stories,
            files=files,
        )
        (workspace / MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Verify before exposing the directory to a read-only container mount.
        verify_demo_content(workspace)
        if root.exists():
            raise DemoContentError("Demo content root appeared during generation")
        workspace.rename(root)
        return manifest
    finally:
        if workspace.exists():
            shutil.rmtree(workspace)


def verify_demo_content(root: Path) -> dict:
    root = Path(root).absolute()
    try:
        manifest = json.loads((root / MANIFEST).read_text("utf-8"))
        if manifest.get("mode") != MARKER:
            raise ValueError
        for relative, expected in manifest["files"].items():
            path = root / relative
            if path.is_symlink() or not path.is_file() or _sha(path) != expected:
                raise ValueError
        store = PublicationStore(root / "releases")
        catalog = store.catalog()
        if {item.id for item in catalog} != {item[0] for item in STORIES}:
            raise ValueError
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        raise DemoContentError(
            "Local demo content failed integrity validation"
        ) from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".local-demo-content")
    parser.add_argument(
        "--force", action="store_true", help="replace a generated bundle"
    )
    args = parser.parse_args(argv)
    try:
        manifest = generate_demo_content(Path(args.root), force=args.force)
    except DemoContentError as error:
        sys.stderr.write(f"Local demo content: {error}\n")
        return 1
    print(f"Local demo content ready: {Path(args.root).absolute()}")
    print(MARKER)
    for story in manifest["stories"]:
        print(f"  {story['id']} {story['version']}: {story['media']} synthetic assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
