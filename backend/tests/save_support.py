"""Real publication snapshots of lighthouse with explicitly test-only PNG/WAV assets."""

import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import wave

import pytest

from twoworlds.content import loader
from twoworlds.content.publication import (
    MediaApproval,
    PublicationStore,
    ReleaseApproval,
)


@pytest.fixture
def published_story(tmp_path):
    store = PublicationStore.initialize(tmp_path / "releases")

    def publish(identifier="lighthouse", version="1.0.0"):
        document = json.loads(
            (Path(loader.__file__).parent / "scripts/lighthouse/1.0.0.json").read_text(
                encoding="utf-8"
            )
        )
        document["metadata"].update(id=identifier, content_version=version)
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aM1cAAAAASUVORK5CYII="
        )
        audio = BytesIO()
        with wave.open(audio, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\x00\x00" * 80)
        source = tmp_path / "drafts" / identifier / version
        assets, scripts = source / "assets", source / "scripts"
        approvals = []
        for asset in document["media"]:
            asset["content_version"] = version
            asset["path"] = (
                f"{identifier}/{version}/{asset['id']}.{'png' if asset['kind'] == 'image' else 'wav'}"
            )
            asset["source"] = "Synthetic test fixture; not a formal game resource"
            asset["license"] = "Test-only approval; no production license claim"
            path = assets / asset["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = png if asset["kind"] == "image" else audio.getvalue()
            path.write_bytes(raw)
            approvals.append(
                MediaApproval(
                    asset_id=asset["id"],
                    path=asset["path"],
                    sha256=hashlib.sha256(raw).hexdigest(),
                    license_evidence="Synthetic test-only material",
                )
            )
        path = scripts / identifier / f"{version}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(document, ensure_ascii=False).encode("utf-8")
        path.write_bytes(raw)
        store.publish(
            scripts,
            assets,
            identifier,
            version,
            ReleaseApproval(
                script_sha256=hashlib.sha256(raw).hexdigest(),
                reviewed_by="automated test fixture only",
                public_metadata_reviewed=True,
                media=tuple(approvals),
            ),
        )
        return store.load(identifier, version)

    return store, publish
