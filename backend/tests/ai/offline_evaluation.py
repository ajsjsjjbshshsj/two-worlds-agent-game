"""Run versioned NPC checks against isolated, synthetic saves."""

import argparse
from contextlib import ExitStack, closing, contextmanager
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from threading import Event
from typing import Annotated, Literal
from unittest.mock import patch

from pydantic import (
    Field,
    StringConstraints,
    StrictStr,
    ValidationError,
    model_validator,
)

from tests.ai.evaluation_world import (
    A_CLUES,
    B_CLUES,
    OUTSIDER,
    PLAYERS,
    EvaluationWorld,
    clock,
)
from tests.ai.test_graph import FakeProvider, fake_reply
from twoworlds.ai.graph import NarrativeLimits
from twoworlds.application.commands import CommandError
from twoworlds.application.dialogue import DEMO_ANSWER, DemoNarrativeProvider
from twoworlds.application.saves import SaveError, SaveService
from twoworlds.content.schema import ContentModel, Role, Version
from twoworlds.ports.narrative import PROMPT_VERSION, NarrativeQuestion
from twoworlds.storage.sqlite import SQLiteRepository

DATASET = Path(__file__).with_name("fixtures") / "offline-evaluation-v1.json"
SampleId = Annotated[StrictStr, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,37}$")]
Marker = Annotated[StrictStr, StringConstraints(min_length=1, max_length=240)]
PromptVersion = Annotated[
    StrictStr, StringConstraints(pattern=r"^[0-9]{1,3}\.[0-9]{1,3}$")
]
ScriptId = Literal["lighthouse", "starline"]
Result = Literal["demo", "provider", "fallback", "rejected"]

CONTEXT_FIELDS = {
    "script_id",
    "script_version",
    "scene_id",
    "role",
    "question",
    "persona",
    "personal_clues",
    "shared_clues",
    "personal_devices",
    "public_milestones",
    "recent_dialogue",
}


class Input(ContentModel):
    question: NarrativeQuestion
    provider: Literal["demo", "fixed", "empty", "oversized", "illegal", "wrong_prompt"]
    scenario: Literal[
        "current",
        "other_script",
        "other_save",
        "other_account",
        "outsider",
        "missing_pinned_version",
        "stale_version",
        "shared_clue",
    ] = "current"
    reply: NarrativeQuestion | None = None

    @model_validator(mode="after")
    def validate_reply(self):
        if (self.provider == "fixed") != (self.reply is not None):
            raise ValueError("Only a fixed provider has authored reply text")
        return self


class Expected(ContentModel):
    result: Result
    error: Literal["SAVE_NOT_FOUND", "SCRIPT_NOT_FOUND", "VERSION_CONFLICT"] | None = (
        None
    )
    provider_calls: Literal[0, 1]
    reply_contains: tuple[Marker, ...] = ()

    @model_validator(mode="after")
    def validate_result(self):
        if (self.result == "rejected") != (self.error is not None):
            raise ValueError("A rejected command requires an expected error")
        if self.result == "rejected" and self.reply_contains:
            raise ValueError("Rejected cases cannot require reply markers")
        if self.result != "rejected" and (
            self.provider_calls != 1 or not self.reply_contains
        ):
            raise ValueError("Accepted cases require provider and reply assertions")
        return self


class Sample(ContentModel):
    sample_id: SampleId
    dataset_version: Version
    script_id: ScriptId
    script_version: Version
    player_role: Role
    prompt_version: PromptVersion
    input: Input
    allowed_facts: Annotated[tuple[Marker, ...], Field(min_length=1)]
    forbidden_facts: Annotated[tuple[Marker, ...], Field(min_length=1)]
    expected: Expected

    @model_validator(mode="after")
    def validate_facts(self):
        if set(self.allowed_facts) & set(self.forbidden_facts):
            raise ValueError("Conflicting fact assertions")
        if self.input.scenario == "stale_version" and (
            self.player_role != "a" or self.input.provider == "demo"
        ):
            raise ValueError("Stale cases require role A and a controllable provider")
        if self.input.scenario == "shared_clue" and self.player_role != "b":
            raise ValueError("Shared clue cases use role B to observe role A's clue")
        return self


class Dataset(ContentModel):
    dataset_version: Version
    samples: Annotated[tuple[Sample, ...], Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def validate_samples(self):
        if any(s.dataset_version != self.dataset_version for s in self.samples):
            raise ValueError("Sample version differs from dataset")
        if len({s.sample_id for s in self.samples}) != len(self.samples):
            raise ValueError("Duplicate case identifier")
        return self


class RecordedDemo(DemoNarrativeProvider):
    def __init__(self):
        self.calls = []

    def generate(self, request):
        self.calls.append(request)
        return super().generate(request)


def provider_for(sample, entered, release):
    if sample.input.provider == "demo":
        return RecordedDemo()

    def respond(request):
        if sample.input.scenario == "stale_version":
            entered.set()
            if not release.wait(8):
                raise TimeoutError("Evaluation did not complete the competing command")
        if sample.input.provider == "wrong_prompt":
            return fake_reply(request, prompt_version="0.9")
        if sample.input.provider == "illegal":
            return fake_reply(
                request, text="EVAL_INVALID_OUTPUT", grant_item="EVAL_FAKE_ITEM"
            )
        text = {"fixed": sample.input.reply, "empty": "", "oversized": "超" * 2001}
        return fake_reply(request, text=text[sample.input.provider])

    return FakeProvider(respond)


def run_command(world, service, sample, save_id, actor, talk, before, entered, release):
    def submit():
        try:
            return service.submit_command(actor, save_id, talk), None
        except (SaveError, CommandError) as exc:
            return None, exc.code

    if sample.input.scenario != "stale_version":
        response, error = submit()
        return response, error, before

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(submit)
        try:
            winner = before
            if entered.wait(5):
                # A real command from the other role wins while the provider waits.
                world.demo.submit_command(
                    PLAYERS["b"],
                    save_id,
                    world.command(
                        save_id, "share_clue", clue_id=B_CLUES[sample.script_id]
                    ),
                )
                winner = world.repo.get_save(save_id)
        finally:
            release.set()
        response, error = pending.result(timeout=10)
    return response, error, winner


def evaluate_sample(world, sample, root):
    save_id = world.seed(sample)
    before = world.repo.get_save(save_id)
    publications = world.publication_for(sample, root)
    actor = (
        OUTSIDER if sample.input.scenario == "outsider" else PLAYERS[sample.player_role]
    )
    partner = PLAYERS["b" if sample.player_role == "a" else "a"]
    partner_before = world.demo.read_save(partner, save_id).personal.dialogue
    entered, release = Event(), Event()
    provider = provider_for(sample, entered, release)
    service = SaveService(
        world.repo,
        publications,
        clock=clock,
        narrative_provider=provider,
        narrative_limits=NarrativeLimits(timeout_seconds=10),
    )
    talk = world.command(save_id, "talk", question=sample.input.question)
    response, error, expected_base = run_command(
        world, service, sample, save_id, actor, talk, before, entered, release
    )
    after = world.repo.get_save(save_id)
    receipts = tuple(r for r in after.receipts if r.request_id == talk.request_id)
    turn = (
        after.dialogues[-1]
        if response and len(after.dialogues) > len(before.dialogues)
        else None
    )
    result = (
        turn.mode if turn else "rejected" if response is None else "missing_dialogue"
    )
    checks = {
        "pinned_metadata": (before.script_id, before.script_version, PROMPT_VERSION)
        == (sample.script_id, sample.script_version, sample.prompt_version),
        "expected_result": result == sample.expected.result
        and error == sample.expected.error,
        "provider_call_count": len(provider.calls) == sample.expected.provider_calls,
        "legal_save_versions": after.version
        == after.state.version
        == after.public_history.through_version,
    }

    if sample.expected.provider_calls:
        # Evaluate authoritative fields separately from the deliberately untrusted question.
        request = provider.calls[0] if provider.calls else None
        context = request.context.model_dump(mode="json") if request else {}
        facts = json.dumps(
            {k: v for k, v in context.items() if k != "question"}, ensure_ascii=False
        )
        checks.update(
            context_whitelist=set(context) == CONTEXT_FIELDS,
            context_scope=(
                context.get("script_id"),
                context.get("script_version"),
                context.get("role"),
            )
            == (sample.script_id, sample.script_version, sample.player_role),
            input_stays_untrusted=context.get("question") == sample.input.question,
            prompt_version=bool(
                request and request.prompt_version == sample.prompt_version
            ),
            allowed_facts_present=all(
                marker in facts for marker in sample.allowed_facts
            ),
            forbidden_facts_absent=all(
                marker not in facts for marker in sample.forbidden_facts
            ),
        )
        if sample.input.scenario == "shared_clue":
            a_clue = A_CLUES[sample.script_id]
            checks["shared_clue_scope"] = any(
                clue["id"] == a_clue for clue in context.get("shared_clues", [])
            ) and all(
                clue["id"] != a_clue for clue in context.get("personal_clues", [])
            )

    if sample.expected.result == "rejected":
        checks["no_talk_write"] = (
            response is None and after == expected_base and not receipts
        )
        if sample.input.scenario == "stale_version":
            checks["competing_write_persisted"] = (
                after.version == before.version + 1
                and len(after.receipts) == len(before.receipts) + 1
                and after.receipts[-1].actor_id == partner
                and after.dialogues == before.dialogues
                and B_CLUES[sample.script_id] in after.state.shared_clues
            )
    else:
        checks.update(
            rules_unchanged=after.state.model_dump(exclude={"version"})
            == before.state.model_dump(exclude={"version"})
            and after.public_history.model_dump(exclude={"through_version"})
            == before.public_history.model_dump(exclude={"through_version"}),
            one_private_write=bool(
                turn
                and response
                and after.dialogues[:-1] == before.dialogues
                and turn.role == sample.player_role
                and turn.question == sample.input.question
                and after.version == before.version + 1
                and len(receipts) == 1
                and receipts[0].actor_id == actor
                and after.receipts[:-1] == before.receipts
                and response.receipt.accepted_version == after.version
                and response.receipt.request_id == talk.request_id
                and response.save.personal.dialogue
                and response.save.personal.dialogue[-1].answer == turn.answer
            ),
            partner_dialogue_unchanged=(
                service.read_save(partner, save_id).personal.dialogue == partner_before
            ),
            reply_markers=bool(
                turn
                and all(
                    marker in turn.answer for marker in sample.expected.reply_contains
                )
                and all(marker not in turn.answer for marker in sample.forbidden_facts)
            ),
        )
        if sample.expected.result == "fallback":
            checks["fixed_fallback_only"] = bool(turn and turn.answer == DEMO_ANSWER)

    return sample_result(sample, result, error, len(provider.calls), checks)


def sample_result(sample, result, error, provider_calls, checks):
    return {
        "sample_id": sample.sample_id,
        "dataset_version": sample.dataset_version,
        "script_id": sample.script_id,
        "script_version": sample.script_version,
        "player_role": sample.player_role,
        "prompt_version": sample.prompt_version,
        "scenario": sample.input.scenario,
        "observed_result": result,
        "observed_error": error,
        "provider_calls": provider_calls,
        "passed": all(checks.values()),
        "checks": checks,
    }


@contextmanager
def block_network():
    attempts = []

    def deny(*_args, **_kwargs):
        attempts.append(True)
        raise OSError("Network is disabled for offline evaluation")

    with ExitStack() as stack:
        for attr in ("connect", "connect_ex", "sendto", "sendmsg"):
            if hasattr(socket.socket, attr):
                stack.enter_context(patch.object(socket.socket, attr, deny))
        for attr in (
            "getaddrinfo",
            "gethostbyname",
            "gethostbyname_ex",
            "gethostbyaddr",
            "getnameinfo",
        ):
            stack.enter_context(patch.object(socket, attr, deny))
        yield attempts


def evaluate(dataset, repository, root):
    """Shared case runner. The CLI strictly supplies a fresh local SQLite file."""
    world = EvaluationWorld(repository, root)
    results = []
    for sample in dataset.samples:
        try:
            result = evaluate_sample(world, sample, root)
        except (SaveError, CommandError) as exc:
            result = sample_result(
                sample,
                "evaluation_error",
                exc.code,
                None,
                {"evaluation_completed": False},
            )
        results.append(result)
    return results


def run_offline(path=DATASET):
    raw = path.read_bytes()
    dataset = Dataset.model_validate_json(raw)
    with (
        block_network() as attempts,
        TemporaryDirectory(prefix="tw-offline-eval-") as directory,
    ):
        root = Path(directory)
        with closing(SQLiteRepository(root / "evaluation.db")) as repository:
            results = evaluate(dataset, repository, root)
    passed = sum(item["passed"] for item in results)
    failed = len(results) - passed
    return {
        "report_version": 1,
        "dataset_version": dataset.dataset_version,
        "dataset_sha256": sha256(raw).hexdigest(),
        "runtime_prompt_version": PROMPT_VERSION,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "network_attempts_blocked": len(attempts),
        "external_model_cost_usd": 0,
        "ok": failed == 0 and not attempts,
        "manual_review": "not_performed",
        "samples": results,
    }


def markdown(report):
    lines = [
        "# TwoWorlds NPC 离线评估",
        "",
        f"- 样本版本 `{report['dataset_version']}`，SHA-256 `{report['dataset_sha256']}`。",
        f"- 当前 Prompt 版本 `{report['runtime_prompt_version']}`。",
        f"- 样本 {report['total']} 条，通过 {report['passed']} 条，失败 {report['failed']} 条。",
        f"- 阻止的网络尝试 {report['network_attempts_blocked']} 次，外部模型费用 USD 0。",
        "- 人工叙事评分待评。",
        "",
        "| 样本 | 剧本版本 | 角色 | Prompt | 观察到的结果 | 自动结果 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for sample in report["samples"]:
        status = "通过" if sample["passed"] else "失败"
        result = sample["observed_error"] or sample["observed_result"]
        lines.append(
            f"| `{sample['sample_id']}` | `{sample['script_id']}@{sample['script_version']}`"
            f" | {sample['player_role']} | {sample['prompt_version']} | `{result}` | {status} |"
        )
    failures = [
        f"- `{sample['sample_id']}` 的失败项为 "
        + "、".join(
            f"`{check}`" for check, passed in sample["checks"].items() if not passed
        )
        + "。"
        for sample in report["samples"]
        if not sample["passed"]
    ]
    if failures:
        lines.extend(["", "## 失败项", "", *failures])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run fixed NPC evaluation samples offline"
    )
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run_offline(args.dataset)
    except (OSError, ValidationError):
        parser.exit(2, "无法读取或校验离线评估样本。\n")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output / "summary.md").write_text(markdown(report), encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
