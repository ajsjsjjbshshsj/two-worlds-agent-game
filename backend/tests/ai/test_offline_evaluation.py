"""Exercise the evaluator's success, failure and offline behavior."""

import json
import socket

import pytest

from tests.ai.offline_evaluation import DATASET, Dataset, block_network, evaluate, main
from tests.api import test_saves as lifecycle
from tests.storage.conftest import (  # noqa: F401
    mongo_database,
    mongo_repository_factory,
    sqlite_repository_factory,
)

save_repository_factory = lifecycle.save_repository_factory


def test_fixed_dataset_on_real_repository(save_repository_factory, tmp_path):
    dataset = Dataset.model_validate_json(DATASET.read_bytes())
    results = evaluate(dataset, save_repository_factory(), tmp_path)
    assert len(results) == 18
    failures = {
        result["sample_id"]: result["checks"]
        for result in results
        if not result["passed"]
    }
    assert not failures
    by_id = {result["sample_id"]: result for result in results}
    assert by_id["public_clue"]["checks"]["shared_clue_scope"]
    assert by_id["prompt_injection"]["checks"]["input_stays_untrusted"]
    assert by_id["prompt_injection"]["checks"]["forbidden_facts_absent"]
    assert by_id["outsider"]["observed_error"] == "SAVE_NOT_FOUND"
    assert by_id["outsider"]["provider_calls"] == 0
    assert by_id["missing_content_version"]["observed_error"] == "SCRIPT_NOT_FOUND"
    assert by_id["wrong_prompt_version"]["checks"]["fixed_fallback_only"]
    assert by_id["stale_generation"]["checks"]["competing_write_persisted"]
    assert by_id["stale_generation"]["checks"]["no_talk_write"]


def test_cli_is_reproducible_and_reports_no_raw_text(tmp_path, monkeypatch):
    monkeypatch.setenv("TWOWORLDS_AI_MODE", "provider")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    first, second = tmp_path / "first", tmp_path / "second"
    assert main(["--output", str(first)]) == 0
    assert main(["--output", str(second)]) == 0
    for name in ("results.json", "summary.md"):
        first_data = (first / name).read_bytes()
        assert first_data == (second / name).read_bytes()
        for private_text in ("EVAL_ROLE_A_HISTORY", "北极星钥匙", "维护日志"):
            assert private_text.encode() not in first_data
    result = json.loads((first / "results.json").read_bytes())
    assert result["passed"] == result["total"] == 18
    assert result["failed"] == result["network_attempts_blocked"] == 0
    assert result["external_model_cost_usd"] == 0
    assert result["manual_review"] == "not_performed"


def test_guard_denies_socket_connection_and_dns():
    with block_network() as attempts, socket.socket() as client:
        with pytest.raises(OSError, match="Network is disabled"):
            client.connect(("192.0.2.1", 443))
        with pytest.raises(OSError, match="Network is disabled"):
            socket.getaddrinfo("provider.invalid", 443)
    assert len(attempts) == 2


def test_cli_flags_a_well_formed_reply_containing_a_forbidden_fact(tmp_path):
    dataset = json.loads(DATASET.read_bytes())
    sample = next(s for s in dataset["samples"] if s["sample_id"] == "fabricated_fact")
    sample["input"]["reply"] += "北极星钥匙。"
    dataset["samples"] = [sample]
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")
    output = tmp_path / "output"
    assert main(["--dataset", str(path), "--output", str(output)]) == 1
    result = json.loads((output / "results.json").read_bytes())
    assert (result["passed"], result["failed"]) == (0, 1)
    assert result["samples"][0]["checks"]["reply_markers"] is False
    assert result["samples"][0]["checks"]["rules_unchanged"] is True
    summary = (output / "summary.md").read_text(encoding="utf-8")
    assert "reply_markers" in summary
    assert "北极星钥匙" not in summary


@pytest.mark.parametrize("invalid", ["unknown_field", "duplicate_id", "mixed_versions"])
def test_cli_rejects_invalid_datasets_without_reports(tmp_path, invalid):
    dataset = json.loads(DATASET.read_bytes())
    first = dataset["samples"][0]
    if invalid == "unknown_field":
        first["input"]["unexpected"] = True
    elif invalid == "duplicate_id":
        dataset["samples"].append(first)
    else:
        first["dataset_version"] = "2.0.0"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")
    output = tmp_path / "output"
    with pytest.raises(SystemExit) as exc:
        main(["--dataset", str(path), "--output", str(output)])
    assert exc.value.code == 2
    assert not output.exists()
