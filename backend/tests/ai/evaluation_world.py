"""Synthetic saves for the offline evaluation, driven through real commands."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

from tests.save_support import make_publications
from twoworlds.application.commands import GameCommand
from twoworlds.application.saves import SaveService
from twoworlds.domain.persistence import AccountRecord, PairRecord

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
PLAYERS = {"a": "account_eval_a", "b": "account_eval_b"}
OUTSIDER = "account_eval_outside"
TARGETS = {
    "lighthouse": ("maintenance_log", "sea_chart"),
    "starline": ("station_log", "power_board"),
}
A_CLUES = {"lighthouse": "a_maintenance_log", "starline": "a_station_log"}
B_CLUES = {"lighthouse": "b_sea_chart", "starline": "b_power_board"}


def clock():
    return NOW


class EvaluationWorld:
    def __init__(self, repository, root):
        self.repo = repository
        self.store, publish = make_publications(root)
        for script in TARGETS:
            publish(identifier=script)
        self.demo = SaveService(repository, self.store, clock=clock)

        # Test-only, unusable password hashes. These accounts never issue sessions.
        for actor in (*PLAYERS.values(), OUTSIDER):
            self.repo.create_account(
                AccountRecord(
                    id=actor,
                    email=f"{actor}@evaluation.invalid",
                    email_verified_at=NOW,
                    password_hash="synthetic_offline_fixture_only",
                    display_name="Offline fixture",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )

    def new_save(self, label, script_id, version, *, actor=PLAYERS["a"]):
        pair_id = "pair_" + label
        invitation = sha256(pair_id.encode()).hexdigest()
        self.repo.create_pair(
            PairRecord(
                id=pair_id,
                member_a=actor,
                invite_digest=invitation,
                invite_expires_at=NOW + timedelta(hours=1),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        if self.repo.join_pair(pair_id, PLAYERS["b"], invitation, NOW) is None:
            raise RuntimeError("Fixture pair did not join")
        return self.demo.create_save(actor, pair_id, script_id, version).id

    def command(self, save_id, kind, **args):
        save = self.repo.get_save(save_id)
        return GameCommand(
            request_id=uuid4(),
            expected_version=save.version,
            kind=kind,
            args=args,
        )

    def seed(self, sample):
        save_id = self.new_save(
            sample.sample_id, sample.script_id, sample.script_version
        )
        for (role, actor), target in zip(
            PLAYERS.items(), TARGETS[sample.script_id], strict=True
        ):
            self.demo.submit_command(
                actor, save_id, self.command(save_id, "inspect", target=target)
            )
            self.demo.submit_command(
                actor,
                save_id,
                self.command(
                    save_id, "talk", question=f"EVAL_ROLE_{role.upper()}_HISTORY"
                ),
            )
        if sample.input.scenario == "shared_clue":
            self.demo.submit_command(
                PLAYERS["a"],
                save_id,
                self.command(save_id, "share_clue", clue_id=A_CLUES[sample.script_id]),
            )
        if sample.input.scenario in {
            "other_save",
            "other_script",
            "other_account",
            "outsider",
        }:
            actor = (
                OUTSIDER
                if sample.input.scenario in {"other_account", "outsider"}
                else PLAYERS["a"]
            )
            other_script = (
                next(key for key in TARGETS if key != sample.script_id)
                if sample.input.scenario == "other_script"
                else sample.script_id
            )
            other_id = self.new_save(
                sample.sample_id + "_other", other_script, "1.0.0", actor=actor
            )
            self.demo.submit_command(
                actor,
                other_id,
                self.command(other_id, "inspect", target=TARGETS[other_script][0]),
            )
            marker = f"EVAL_{sample.input.scenario.upper()}_HISTORY"
            self.demo.submit_command(
                actor,
                other_id,
                self.command(other_id, "talk", question=marker),
            )
            if self.repo.get_save(other_id).dialogues[-1].question != marker:
                raise RuntimeError("Other save marker was not persisted")
        return save_id

    def publication_for(self, sample, root):
        if sample.input.scenario != "missing_pinned_version":
            return self.store
        # The save remains pinned to the original version; the server has a
        # newer release available but must never substitute it automatically.
        store, publish = make_publications(root / sample.sample_id)
        publish(identifier=sample.script_id, version="1.1.0")
        return store
