import hashlib
import json
from uuid import uuid4

from pydantic import ValidationError
import pytest

from twoworlds.application.commands import GameCommand


def test_fingerprint_is_canonical_sha256_and_includes_original_version():
    identifier = str(uuid4())
    body = {
        "request_id": identifier,
        "expected_version": 3,
        "kind": "set_emitter",
        "args": {"pattern": "pulse", "angle": 90},
    }
    value = GameCommand.model_validate(body)
    expected = hashlib.sha256(
        json.dumps(
            {k: v for k, v in body.items() if k != "request_id"},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    assert value.fingerprint() == expected
    reordered = GameCommand.model_validate(
        body | {"args": {"angle": 90, "pattern": "pulse"}}
    )
    assert reordered.fingerprint() == expected
    assert (
        GameCommand.model_validate(body | {"request_id": str(uuid4())}).fingerprint()
        == expected
    )
    assert (
        GameCommand.model_validate(body | {"expected_version": 4}).fingerprint()
        != expected
    )
    assert (
        GameCommand.model_validate(body | {"kind": "other"}).fingerprint() != expected
    )
    assert (
        GameCommand.model_validate(
            body | {"args": {"angle": 180, "pattern": "pulse"}}
        ).fingerprint()
        != expected
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_version": True},
        {"expected_version": -1},
        {"expected_version": 0.0},
        {"request_id": 4},
        {"request_id": "invalid"},
        {"args": []},
        {"args": {"value": float("nan")}},
        {"args": {"value": float("inf")}},
        {"args": {"value": object()}},
        {"role": "b"},
        {"completed": True},
    ],
)
def test_application_envelope_rejects_noncanonical_input(changes):
    with pytest.raises(ValidationError):
        GameCommand.model_validate(
            {
                "request_id": str(uuid4()),
                "expected_version": 0,
                "kind": "inspect",
                "args": {},
            }
            | changes
        )
