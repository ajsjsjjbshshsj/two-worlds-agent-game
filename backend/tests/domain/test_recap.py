"""Public cooperation runs on the real lighthouse rules and role projections."""

from pathlib import Path

import pytest

from twoworlds.content import loader
from twoworlds.content.schema import ScriptVersion
from twoworlds.domain.engine import apply_command, create_initial_state
from twoworlds.domain.errors import DomainError
from twoworlds.domain.models import DomainEvent
from twoworlds.domain.projection import project_save


@pytest.fixture
def script():
    return loader.ScriptLoader(Path(loader.__file__).parent / "scripts").load(
        "lighthouse", "1.0.0"
    )


def history_for(script):
    from twoworlds.domain.recap import PublicHistory

    return PublicHistory(
        script_id=script.metadata.id, script_version=script.metadata.content_version
    )


def append(history, script, version, events):
    from twoworlds.domain.recap import append_public_history

    return append_public_history(history, script, version, tuple(events))


def recap(history, script, ending):
    from twoworlds.domain.recap import build_public_recap

    return build_public_recap(history, script, ending)


def command(state, script, actor_role, kind, **args):
    return apply_command(state, script, actor_role, {"kind": kind, "args": args})


def share(state, script, role, clue):
    return command(state, script, role, "share_clue", clue_id=clue)


def play(script, steps):
    state, history = create_initial_state(script), history_for(script)
    for role, kind, args in steps:
        result = command(state, script, role, kind, **args)
        state = result.state
        history = append(history, script, state.version, result.events)
    return state, history


DISCOVER = [
    ("a", "inspect", {"target": "maintenance_log"}),
    ("b", "inspect", {"target": "sea_chart"}),
]
REACH_DECISION = DISCOVER + [
    ("a", "share_clue", {"clue_id": "a_maintenance_log"}),
    ("a", "set_emitter", {"angle": 90, "pattern": "pulse"}),
    ("b", "set_filter", {"filter": "amber"}),
    ("b", "lock_signal", {}),
    ("b", "route_power", {"target": "tower"}),
    ("a", "inspect", {"target": "clock_gears"}),
    ("a", "repair_clock", {"mode": "steady"}),
    ("b", "confirm_route", {}),
]


@pytest.mark.parametrize(
    "role,clue_id", [("a", "a_maintenance_log"), ("b", "b_sea_chart")]
)
def test_share_has_one_public_event_and_only_the_designated_text(script, role, clue_id):
    state, history = play(script, DISCOVER)
    before = state.model_dump()
    result = share(state, script, role, clue_id)
    clue = next(clue for clue in script.clues if clue.id == clue_id)
    assert state.model_dump() == before
    assert result.state.version == state.version + 1
    assert result.state.shared_clues == (clue_id,)
    assert result.state.discovered_clues == state.discovered_clues
    assert result.events == (
        DomainEvent(
            kind="clue_shared",
            audience="public",
            subject_id=clue_id,
            text=clue.text,
            version=result.state.version,
        ),
    )
    updated = append(history, script, result.state.version, result.events)
    assert updated.milestones[0].kind == "clue_shared"
    a, b = (project_save(result.state, script, r, updated) for r in ("a", "b"))
    assert a.public == b.public
    assert [(item.id, item.text) for item in a.public.clues] == [(clue_id, clue.text)]
    assert [item.id for item in a.personal.clues] == ["a_maintenance_log"]
    assert [item.id for item in b.personal.clues] == ["b_sea_chart"]
    assert all(
        action.kind != "share_clue"
        for action in (a if role == "a" else b).available_actions
    )
    other = next(
        c for c in script.clues if c.role != role and c.id in state.discovered_clues
    )
    assert other.id not in a.public.model_dump_json()
    assert other.text not in a.public.model_dump_json()


@pytest.mark.parametrize(
    "role,clue,discover",
    [
        ("a", "a_maintenance_log", False),
        ("a", "b_sea_chart", True),
        ("b", "a_maintenance_log", True),
        ("a", "unknown_clue", True),
    ],
)
def test_unknown_partner_and_undiscovered_clues_use_same_error(
    script, role, clue, discover
):
    state, history = play(script, DISCOVER if discover else [])
    before = state.model_dump()
    with pytest.raises(DomainError) as error:
        share(state, script, role, clue)
    assert error.value.code == "CLUE_NOT_DISCOVERED"
    assert state.model_dump() == before
    assert not history.events


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"clue_id": []},
        {"clue_id": True},
        {"clue_id": "?"},
        {"clue_id": "a_maintenance_log", "role": "a"},
    ],
)
def test_share_rejects_malformed_arguments(script, args):
    state, _ = play(script, DISCOVER)
    with pytest.raises(DomainError) as error:
        command(state, script, "a", "share_clue", **args)
    assert error.value.code == "INVALID_ARGUMENTS"
    assert state.version == 2 and not state.shared_clues


def test_share_choices_are_role_scoped_and_respect_nonshareable_clues(script):
    raw = script.model_dump(mode="python")
    raw["clues"][0]["shareable"] = False
    script = ScriptVersion.model_validate(raw)
    state, history = play(script, DISCOVER)
    a, b = (project_save(state, script, role, history) for role in ("a", "b"))
    assert all(action.kind != "share_clue" for action in a.available_actions)
    action = next(
        action for action in b.available_actions if action.kind == "share_clue"
    )
    assert action.parameters[0].choices == ("b_sea_chart",)
    with pytest.raises(DomainError) as error:
        share(state, script, "a", "a_maintenance_log")
    assert error.value.code == "CLUE_NOT_SHAREABLE"


def test_duplicate_share_and_completed_share_leave_previous_state_intact(script):
    state, _ = play(script, REACH_DECISION)
    for choice in (
        state,
        play(
            script,
            REACH_DECISION
            + [
                ("a", "vote_ending", {"choice": "guide_now"}),
                ("b", "vote_ending", {"choice": "guide_now"}),
            ],
        )[0],
    ):
        before = choice.model_dump()
        with pytest.raises(DomainError) as error:
            share(choice, script, "a", "a_maintenance_log")
        assert error.value.code == (
            "SAVE_COMPLETED" if choice.completed else "NO_STATE_CHANGE"
        )
        assert choice.model_dump() == before


def test_shares_have_stable_order_even_when_b_shares_first(script):
    state, history = play(
        script,
        DISCOVER
        + [
            ("b", "share_clue", {"clue_id": "b_sea_chart"}),
            ("a", "share_clue", {"clue_id": "a_maintenance_log"}),
        ],
    )
    assert state.shared_clues == ("a_maintenance_log", "b_sea_chart")
    assert [step.subject_id for step in history.milestones] == [
        "b_sea_chart",
        "a_maintenance_log",
    ]
    assert [
        clue.id for clue in project_save(state, script, "a", history).public.clues
    ] == list(state.shared_clues)


def test_script_actions_cannot_publish_share_choices(script):
    raw = script.model_dump(mode="python")
    raw["actions"][0]["kind"] = "share_clue"
    script = ScriptVersion.model_validate(raw)
    with pytest.raises(DomainError) as error:
        create_initial_state(script)
    assert error.value.code == "INVALID_SCRIPT"


def test_full_snapshots_hide_partner_markers_and_private_batches_keep_public_slots(
    script,
):
    raw = script.model_dump(mode="python")
    for clue in raw["clues"]:
        clue["text"] = f"PRIVATE_MARKER_{clue['id']}"
    script = ScriptVersion.model_validate(raw)
    state, history = play(
        script,
        [
            DISCOVER[0],
            ("a", "share_clue", {"clue_id": "a_maintenance_log"}),
        ],
    )
    result = command(state, script, *DISCOVER[1][:2], **DISCOVER[1][2])
    private = tuple(
        DomainEvent(
            kind="dialogue",
            audience="b",
            text=f"PRIVATE_MARKER_dialogue_{i}",
            version=result.state.version,
        )
        for i in range(35)
    )
    updated = append(history, script, result.state.version, (*result.events, *private))
    assert updated.events == history.events and updated.event_count == 1
    assert updated.through_version == result.state.version
    a, b = (project_save(result.state, script, role, updated) for role in ("a", "b"))
    assert a.public == b.public
    assert "PRIVATE_MARKER_b_sea_chart" in b.model_dump_json()
    assert "PRIVATE_MARKER_b_sea_chart" not in a.model_dump_json()
    assert "PRIVATE_MARKER_dialogue" not in a.model_dump_json() + b.model_dump_json()
    assert not any(clue.id == "a_maintenance_log" for clue in b.personal.clues)


def test_history_progresses_on_private_and_empty_batches_without_using_slots(script):
    history = history_for(script)
    private = tuple(
        DomainEvent(
            kind=kind, audience=role, text=f"PRIVATE_MARKER_{role}_{kind}", version=1
        )
        for role in ("a", "b")
        for kind in (
            "clue_discovered",
            "device_changed",
            "observation_changed",
            "dialogue",
        )
    )
    history = append(history, script, 1, private)
    history = append(history, script, 2, ())
    assert history.through_version == 2
    assert not history.events and not history.milestones
    assert "PRIVATE_MARKER" not in history.model_dump_json()


@pytest.mark.parametrize(
    "version, event_version, kind, audience, subject, value, text",
    [
        (0, 0, "vote_changed", "public", "a", "guide_now", "vote"),
        (2, 2, "vote_changed", "public", "a", "guide_now", "vote"),
        (1, 2, "observation_changed", "a", None, None, "private"),
        (1, 1, "dialogue", "public", None, None, "PRIVATE_MARKER"),
        (1, 1, "clue_discovered", "public", "b_sea_chart", None, "PRIVATE_MARKER"),
        (1, 1, "fact_changed", "public", "repair_tools_ready", True, "PRIVATE_MARKER"),
        (1, 1, "observation", "public", None, None, "PRIVATE_MARKER"),
        (1, 1, "clue_shared", "public", "a_maintenance_log", None, "PRIVATE_MARKER"),
    ],
)
def test_invalid_batches_are_rejected_atomically(
    script, version, event_version, kind, audience, subject, value, text
):
    history = history_for(script)
    event = DomainEvent(
        kind=kind,
        audience=audience,
        subject_id=subject,
        value=value,
        text=text,
        version=event_version,
    )
    with pytest.raises(DomainError):
        append(history, script, version, (event,))
    assert (
        history.through_version == 0 and not history.events and not history.milestones
    )


@pytest.mark.parametrize("ending", ["guide_now", "wait_tide"])
def test_real_recap_survives_truncation_and_both_roles_see_same_public_view(
    script, ending
):
    # A can revise a real vote repeatedly while B has yet to vote.
    other = "wait_tide" if ending == "guide_now" else "guide_now"
    revisions = [
        ("a", "vote_ending", {"choice": choice}) for choice in [other, ending] * 19
    ]
    state, history = play(
        script, REACH_DECISION + revisions + [("b", "vote_ending", {"choice": ending})]
    )
    assert state.completed and history.through_version == state.version
    assert len(history.events) == 30
    assert [event.ordinal for event in history.events] == list(
        range(history.event_count - 29, history.event_count + 1)
    )
    assert history.events[0].version > 10
    assert history.events[-1].version == history.events[-2].version == state.version
    result = recap(history, script, ending)
    assert result.summary == next(
        item.summary_template for item in script.endings if item.id == ending
    )
    assert result.ending_id == ending
    assert [step.kind for step in result.milestones] == [
        "clue_shared",
        "signal_locked",
        "scene_entered",
        "clock_repaired",
        "route_confirmed",
        "scene_entered",
        "scene_entered",
        "game_completed",
    ]
    assert result.milestones[0].text == script.clues[0].text
    assert all(
        set(item.model_dump()) == {"version", "ordinal", "kind", "subject_id"}
        for item in history.milestones
    )
    before = state.model_dump()
    a, b = (project_save(state, script, role, history) for role in ("a", "b"))
    assert (
        a.public == b.public and a.public.recap == result and a.public.ending == ending
    )
    assert a.personal != b.personal and state.model_dump() == before
    assert "b_sea_chart" not in a.model_dump_json()
    assert script.clues[1].text not in a.model_dump_json()
    assert not project_save(state, script, "a").public.events
    assert not project_save(state, script, "a").public.recap.milestones
    assert project_save(state, script, "a").public.recap.summary is None
    for invalid in (other, "fake_ending", None):
        with pytest.raises(DomainError):
            recap(history, script, invalid)


def test_incomplete_future_or_corrupt_history_is_rejected(script):
    state, history = play(script, REACH_DECISION)
    for invalid in (
        history_for(script),
        history.model_copy(update={"through_version": state.version + 1}),
        history.model_copy(update={"events": history.events[1:]}),
        history.model_copy(update={"milestones": ()}),
        history.model_copy(update={"script_version": "2.0.0"}),
        history.model_copy(
            update={
                "events": (
                    history.events[0].model_copy(update={"text": "PRIVATE_MARKER"}),
                    *history.events[1:],
                )
            }
        ),
    ):
        with pytest.raises(DomainError):
            project_save(state, script, "a", invalid)
    with pytest.raises(DomainError):
        append(history, script, history.through_version, ())
    with pytest.raises(DomainError):
        recap(history, script, "guide_now")
    assert recap(history, script, None).summary is None


def test_milestone_capacity_rejects_append_without_dropping_early_progress(script):
    raw = script.model_dump(mode="python")
    raw["clues"] += tuple(
        {
            "id": f"test_clue_{index}",
            "role": "a",
            "shareable": True,
            "text": f"Shared {index}",
        }
        for index in range(65)
    )
    script = ScriptVersion.model_validate(raw)
    history = history_for(script)
    for index in range(64):
        event = DomainEvent(
            kind="clue_shared",
            audience="public",
            subject_id=f"test_clue_{index}",
            text=f"Shared {index}",
            version=index + 1,
        )
        history = append(history, script, index + 1, (event,))
    assert len(history.milestones) == 64 and len(history.events) == 30
    with pytest.raises(DomainError) as error:
        append(
            history,
            script,
            65,
            (
                DomainEvent(
                    kind="clue_shared",
                    audience="public",
                    subject_id="test_clue_64",
                    text="Shared 64",
                    version=65,
                ),
            ),
        )
    assert error.value.code == "PUBLIC_MILESTONE_LIMIT"
    assert (
        history.milestones[0].subject_id == "test_clue_0"
        and history.through_version == 64
    )
