"""Shared puzzle invariants without introducing any new player actions."""

from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError
import pytest

from twoworlds.content import loader
from twoworlds.content.schema import ScriptVersion
from twoworlds.domain.engine import apply_command, create_initial_state
from twoworlds.domain.errors import DomainError
from twoworlds.domain.models import GameState
from twoworlds.domain.projection import project_save
from twoworlds.domain.puzzles import (
    ApproachPermit,
    ApproachState,
    Challenge,
    Clearance,
    EchoState,
    EchoVerification,
    EvidenceContext,
    EvidenceKind,
    FarSample,
    LighthousePuzzles,
    Milestone,
    NearSample,
    PlatformLock,
    Reply,
    StarlinePuzzles,
    SurveyBatch,
    SurveyState,
    TideRange,
    TideReading,
    TideRescan,
    TideScan,
    TideState,
    TideVerification,
    TrackPublication,
    TrackReference,
    TrackVerification,
    require_current_evidence,
)


@pytest.fixture
def expanded_script():
    def load(story):
        source = loader.ScriptLoader(Path(loader.__file__).parent / "scripts").load(
            story, "1.0.0"
        )
        contents = source.model_dump()
        contents["metadata"]["content_version"] = "1.1.0"
        contents["puzzle_rules"] = "p0_v1"
        contents["media"] = [
            media | {"content_version": "1.1.0"} for media in contents["media"]
        ]
        return ScriptVersion.model_validate(contents)

    return load


def evidence(record_type, version, *, story="lighthouse", **fields):
    context = EvidenceContext(
        save_id="save_a",
        script_id=story,
        script_version="1.1.0",
        accepted_version=version,
    )
    return record_type(
        id=context.id_for(record_type.kind), accepted_version=version, **fields
    )


def perform(state, script, role, kind, **args):
    return apply_command(state, script, role, {"kind": kind, "args": args}).state


def echo():
    challenge = evidence(Challenge, 1, optics_rev=0, beats=("short", "long"))
    reply = evidence(
        Reply, 2, optics_rev=0, challenge_id=challenge.id, beats=("long", "short")
    )
    proof = evidence(
        EchoVerification, 3, optics_rev=0, challenge_id=challenge.id, reply_id=reply.id
    )
    return EchoState(challenge=challenge, reply=reply, verification=proof)


def tide():
    reading = evidence(
        TideReading, 1, record_key="private_archive", windows=("early", "middle")
    )
    tide_range = evidence(TideRange, 2, reading_id=reading.id)
    scan = evidence(
        TideScan, 3, tide_config_rev=0, mode="coastal", windows=("middle", "late")
    )
    rescan = evidence(
        TideRescan,
        4,
        tide_config_rev=0,
        scan_id=scan.id,
        range_id=tide_range.id,
        window="middle",
    )
    proof = evidence(
        TideVerification,
        4,
        tide_config_rev=0,
        scan_id=scan.id,
        range_id=tide_range.id,
        rescan_id=rescan.id,
    )
    return TideState(
        reading=reading,
        submitted_reading=reading,
        tide_range=tide_range,
        scan=scan,
        rescan=rescan,
        verification=proof,
    )


def survey():
    batch = evidence(SurveyBatch, 1, story="starline", survey_rev=0)
    near = evidence(
        NearSample,
        2,
        story="starline",
        survey_rev=0,
        batch_id=batch.id,
        aim="near_anchor",
        segments=("bridge_1", "bridge_2"),
    )
    ref = evidence(
        TrackReference, 3, story="starline", survey_rev=0, marker_key="bridge_marker"
    )
    far = evidence(
        FarSample,
        4,
        story="starline",
        survey_rev=0,
        batch_id=batch.id,
        reference_id=ref.id,
        aim="bridge_anchor",
        segments=("bridge_2", "bridge_3"),
    )
    proof = evidence(
        TrackVerification,
        5,
        story="starline",
        survey_rev=0,
        batch_id=batch.id,
        reference_id=ref.id,
        near_id=near.id,
        far_id=far.id,
        segment="bridge_2",
    )
    return SurveyState(
        batch=batch.model_copy(update={"reference_id": ref.id}),
        reference=ref,
        near=near,
        far=far,
        verification=proof,
    )


def approach():
    clearance = evidence(Clearance, 1, story="starline", track_rev=0, track="track_2")
    lock = evidence(
        PlatformLock, 2, story="starline", track_rev=0, clearance_id=clearance.id
    )
    permit = evidence(
        ApproachPermit,
        3,
        story="starline",
        track_rev=0,
        drive_power_rev=0,
        lock_id=lock.id,
    )
    return ApproachState(clearance=clearance, lock=lock, permit=permit)


@pytest.mark.parametrize(
    "make,count", [(echo, 3), (tide, 5), (survey, 5), (approach, 3)]
)
def test_typed_chains_round_trip_and_invalid_fields_are_rejected(make, count):
    chapter = make()
    assert type(chapter).model_validate_json(chapter.model_dump_json()) == chapter
    assert len(chapter.active_evidence()) == count
    for record in chapter.active_evidence():
        data = record.model_dump()
        for malformed in (
            {"accepted_version": "1"},
            {"ordinal": True},
            {"id": uuid4()},
            {"role": "b" if record.role == "a" else "a"},
            {"raw_payload": {}},
        ):
            with pytest.raises(ValidationError):
                type(record).model_validate(data | malformed)


@pytest.mark.parametrize(
    "make,updated",
    [
        (echo, {"challenge": None}),
        (echo, {"optics_rev": 1}),
        (echo, {"locked": {"accepted_version": 4}}),
        (tide, {"submitted_reading": None}),
        (tide, {"rescan": None}),
        (tide, {"tide_config_rev": 1}),
        (survey, {"reference": None}),
        (survey, {"near": None}),
        (survey, {"batch": None}),
        (survey, {"published": {"segment": "bridge_2", "accepted_version": 6}}),
        (approach, {"lock": None}),
        (approach, {"drive_power_rev": 1}),
    ],
)
def test_invalid_associations_or_terminal_combinations_are_rejected(make, updated):
    chapter = make()
    with pytest.raises(ValidationError):
        type(chapter).model_validate(chapter.model_dump() | updated)


def test_associations_verify_exact_parents_and_unique_candidates():
    tide_state, survey_state = tide(), survey()
    with pytest.raises(ValidationError):
        TideState.model_validate(
            tide_state.model_dump()
            | {
                "scan": tide_state.scan.model_copy(
                    update={"windows": ("early", "middle", "late")}
                )
            }
        )
    with pytest.raises(ValidationError):
        SurveyState.model_validate(
            survey_state.model_dump()
            | {
                "far": survey_state.far.model_copy(
                    update={"batch_id": survey_state.reference.id}
                )
            }
        )
    with pytest.raises(ValidationError):
        SurveyState.model_validate(
            survey_state.model_dump()
            | {
                "verification": survey_state.verification.model_copy(
                    update={"far_id": survey_state.near.id}
                )
            }
        )


def test_ids_depend_on_save_story_version_kind_version_and_ordinal():
    context = EvidenceContext(
        save_id="save_a",
        script_id="lighthouse",
        script_version="1.1.0",
        accepted_version=1,
    )
    key = EvidenceKind.CHALLENGE
    original = context.id_for(key)
    assert context.id_for(key) == original
    assert len({context.id_for(kind) for kind in EvidenceKind}) == len(EvidenceKind)
    for change in (
        {"save_id": "save_b"},
        {"script_id": "starline"},
        {"script_version": "1.2.0"},
        {"accepted_version": 2},
    ):
        assert context.model_copy(update=change).id_for(key) != original
    assert context.id_for(key, ordinal=1) != original


def test_current_reference_rejects_wrong_role_kind_scope_parent_and_history():
    chapter = echo()
    puzzles = LighthousePuzzles(l03=chapter)
    context = EvidenceContext(
        save_id="save_a",
        script_id="lighthouse",
        script_version="1.1.0",
        accepted_version=4,
    )
    assert (
        require_current_evidence(
            context,
            puzzles,
            chapter.reply.id,
            EvidenceKind.REPLY,
            issuer="a",
            parents=(chapter.challenge.id,),
        )
        == chapter.reply
    )
    bad_references = (
        (context, puzzles, chapter.reply.id, EvidenceKind.REPLY, "b", None),
        (context, puzzles, chapter.reply.id, EvidenceKind.CHALLENGE, "a", None),
        (
            context.model_copy(update={"save_id": "save_b"}),
            puzzles,
            chapter.reply.id,
            EvidenceKind.REPLY,
            "a",
            None,
        ),
        (context, puzzles, uuid4(), EvidenceKind.REPLY, "a", None),
        (
            context,
            puzzles,
            chapter.reply.id,
            EvidenceKind.REPLY,
            "a",
            (chapter.reply.id,),
        ),
        (
            context,
            LighthousePuzzles(l03=chapter.change_optics()),
            chapter.reply.id,
            EvidenceKind.REPLY,
            "a",
            None,
        ),
        (
            context,
            puzzles.model_copy(
                update={"l03": chapter.model_copy(update={"optics_rev": 1})}
            ),
            chapter.reply.id,
            EvidenceKind.REPLY,
            "a",
            None,
        ),
    )
    for scope, state, identifier, kind, actor, parents in bad_references:
        with pytest.raises(DomainError, match="当前证据不可用") as denied:
            require_current_evidence(
                scope, state, identifier, kind, issuer=actor, parents=parents
            )
        assert denied.value.code == "EVIDENCE_STALE"


def test_optics_command_once_per_change_and_old_challenge_never_returns(
    expanded_script,
):
    script = expanded_script("lighthouse")
    state = create_initial_state(script)
    assert state.puzzles == LighthousePuzzles()
    state = perform(state, script, "a", "inspect", target="maintenance_log")
    state = perform(state, script, "b", "inspect", target="sea_chart")
    chapter = echo()
    state = GameState.model_validate(
        state.model_dump()
        | {"puzzles": LighthousePuzzles(l03=EchoState(challenge=chapter.challenge))}
    )
    state = perform(state, script, "a", "set_emitter", angle=90, pattern="pulse")
    assert state.puzzles.l03.optics_rev == 1 and state.puzzles.l03.challenge is None
    assert state.puzzles.l03.history[0].id == chapter.challenge.id
    assert state.puzzles.l05.tide_config_rev == 0
    for role, angle, pattern, code in (
        ("a", 90, "pulse", "NO_STATE_CHANGE"),
        ("a", 45, "pulse", "INVALID_ARGUMENTS"),
        ("b", 0, "steady", "ROLE_FORBIDDEN"),
    ):
        before = state.model_dump()
        with pytest.raises(DomainError) as exc:
            perform(state, script, role, "set_emitter", angle=angle, pattern=pattern)
        assert exc.value.code == code and state.model_dump() == before
    state = perform(state, script, "a", "set_emitter", angle=0, pattern="steady")
    assert state.puzzles.l03.optics_rev == 2 and state.puzzles.l03.challenge is None


def test_starline_configuration_generations_follow_phases(expanded_script):
    script = expanded_script("starline")
    state = create_initial_state(script)
    assert state.puzzles == StarlinePuzzles()
    state = perform(state, script, "a", "inspect", target="station_log")
    state = perform(state, script, "b", "inspect", target="power_board")
    state = perform(state, script, "a", "set_echo_gate", position="east")
    state = perform(
        state, script, "b", "allocate_power", engine=False, sonar=True, lamp=True
    )
    assert state.puzzles.s03.survey_rev == 2
    assert state.puzzles.s05 == ApproachState()
    with pytest.raises(DomainError) as rejected:
        perform(
            state, script, "b", "allocate_power", engine=True, sonar=True, lamp=True
        )
    assert rejected.value.code == "POWER_BUDGET_EXCEEDED"
    for role, action, args in (
        ("b", "scan_track", {}),
        ("a", "install_rail", {"segment": "bridge_2"}),
        ("b", "allocate_power", {"engine": True, "sonar": False, "lamp": True}),
        ("b", "confirm_signal", {}),
        ("a", "set_platform", {"track": "track_2"}),
        ("a", "set_platform", {"track": "track_1"}),
        ("a", "set_platform", {"track": "track_2"}),
    ):
        state = perform(state, script, role, action, **args)
    assert state.puzzles.s03.survey_rev == 2
    assert (state.puzzles.s05.track_rev, state.puzzles.s05.drive_power_rev) == (3, 1)


def test_invalidations_preserve_independent_records_and_permanent_outcomes():
    tides = tide()
    restored = tides.change_tide_config().change_tide_config()
    assert restored.tide_config_rev == 2
    assert (
        restored.tide_range == tides.tide_range
        and restored.submitted_reading == tides.reading
    )
    assert restored.scan is restored.rescan is restored.verification is None
    assert len(restored.history) == 3
    proposed = survey()
    assert (
        proposed.change_survey_config().change_survey_config().active_evidence() == ()
    )
    published = SurveyState(
        published=TrackPublication(accepted_version=6, segment="bridge_2")
    )
    assert published.change_survey_config().published == published.published
    locked = approach()
    repowered = locked.change_drive_power().change_drive_power()
    assert repowered.lock == locked.lock and repowered.permit is None
    assert repowered.drive_power_rev == 2
    changed = repowered.change_alignment(power_changed=False).change_alignment(
        power_changed=True
    )
    assert changed.lock is None and changed.clearance is None
    assert (changed.track_rev, changed.drive_power_rev) == (2, 3)
    finished = ApproachState(dispatched=Milestone(accepted_version=4))
    assert finished.change_drive_power().dispatched == finished.dispatched


def test_role_projection_exposes_only_own_active_whitelist(expanded_script):
    script = expanded_script("lighthouse")
    initial = create_initial_state(script)
    state = GameState.model_validate(
        initial.model_dump()
        | {"version": 4, "puzzles": LighthousePuzzles(l03=echo(), l05=tide())}
    )
    projected = {
        role: project_save(state, script, role).model_dump(mode="json")
        for role in ("a", "b")
    }
    assert projected["a"]["public"] == projected["b"]["public"]
    assert projected["a"]["public"]["puzzle_milestones"] == []
    for role, partner in (("a", "b"), ("b", "a")):
        view = projected[role]
        opposite = projected[partner]
        by_id = {
            str(item.id): item
            for chapter in state.puzzles.chapters()
            for item in chapter.active_evidence()
        }
        assert {entry["id"] for entry in view["personal"]["puzzle_evidence"]} == {
            key for key, item in by_id.items() if item.role == role
        }
        serialized = project_save(state, script, partner).model_dump_json()
        for entry in view["personal"]["puzzle_evidence"]:
            assert entry["id"] not in serialized
        assert "private_archive" not in serialized
        assert "optics_rev" not in serialized and "history" not in opposite["public"]
        assert "puzzles" not in view


@pytest.mark.parametrize("story", ["lighthouse", "starline"])
def test_legacy_shapes_omit_puzzles_and_cannot_opt_in(story):
    script = loader.ScriptLoader(Path(loader.__file__).parent / "scripts").load(
        story, "1.0.0"
    )
    with pytest.raises(ValidationError):
        ScriptVersion.model_validate(script.model_dump() | {"puzzle_rules": "p0_v1"})
    state = create_initial_state(script)
    assert state.puzzles is None and "puzzles" not in state.model_dump()
    projected = project_save(state, script, "a").model_dump()
    assert (
        "puzzle_evidence" not in projected["personal"]
        and "puzzle_milestones" not in projected["public"]
    )


def test_tide_generation_tracks_power_without_invalidating_other_chapters(
    expanded_script,
):
    script = expanded_script("lighthouse")
    state = create_initial_state(script)
    for role, action, args in (
        ("a", "inspect", {"target": "maintenance_log"}),
        ("b", "inspect", {"target": "sea_chart"}),
        ("a", "set_emitter", {"angle": 90, "pattern": "pulse"}),
        ("b", "set_filter", {"filter": "amber"}),
        ("b", "lock_signal", {}),
        ("b", "route_power", {"target": "tower"}),
        ("a", "inspect", {"target": "clock_gears"}),
        ("a", "repair_clock", {"mode": "steady"}),
    ):
        state = perform(state, script, role, action, **args)
    old = state.puzzles
    assert old.l03.optics_rev == old.l05.tide_config_rev == 2
    state = perform(state, script, "b", "route_power", target="shore")
    state = perform(state, script, "b", "route_power", target="tower")
    assert state.puzzles.l05.tide_config_rev == 4
    assert state.puzzles.l03 == old.l03
    assert state.fact("clock_repaired") is True
