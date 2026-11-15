from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from tests.api.test_pairs import account, auth, create, failure, join
from tests.storage.conftest import sqlite_repository_factory  # noqa: F401
from twoworlds.api.app import create_app


@pytest.fixture(params=["sqlite", "mongo"])
def save_repository_factory(request):
    return request.getfixturevalue(f"{request.param}_repository_factory")


@pytest.fixture
def save_apps(save_repository_factory, published_story):
    store, publish = published_story
    script = publish()
    clock = datetime(2026, 11, 15, tzinfo=timezone.utc)
    with ExitStack() as stack:

        def factory(repository=None):
            repo = repository if repository is not None else save_repository_factory()
            app = create_app(
                repository=repo,
                publication_store=store,
                identity_clock=lambda: clock,
                rate_limit=100,
            )
            return stack.enter_context(TestClient(app)), repo

        yield factory, store, publish, script


def open_save(client, actor, pair_id, version="1.0.0", **extra):
    return client.post(
        "/api/saves",
        headers=auth(actor),
        json={
            "pair_id": pair_id,
            "script_id": "lighthouse",
            "script_version": version,
            **extra,
        },
    )


def test_catalog_is_metadata_only_stably_sorted_and_drafts_hidden(save_apps):
    factory, _, publish, script = save_apps
    publish(version="1.10.0")
    publish(version="1.2.0")
    publish(identifier="alpha")
    client, _ = factory()
    response = client.get("/api/scripts")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    catalog = response.json()
    assert [(s["id"], s["content_version"]) for s in catalog] == [
        ("alpha", "1.0.0"),
        ("lighthouse", "1.0.0"),
        ("lighthouse", "1.2.0"),
        ("lighthouse", "1.10.0"),
    ]
    assert all(set(s) == set(type(script.metadata).model_fields) for s in catalog)
    for clue in script.clues:
        assert clue.text not in response.text
    assert all(asset.path not in response.text for asset in script.media)
    assert '"facts"' not in response.text and '"actions"' not in response.text
    assert "starline" not in response.text


def test_create_read_list_both_roles_and_unauthorized(save_apps):
    factory, _, _, script = save_apps
    client, repo = factory()
    a, b, c = (account(client, r) for r in ("A", "B", "C"))
    pair = create(client, a)
    response = open_save(client, a, pair["id"])
    assert response.status_code == 200, response.text
    initial = response.json()
    assert initial["role"] == "a" and initial["version"] == 0
    assert initial["scene_id"] == "calibration" and not initial["completed"]
    assert response.headers["cache-control"] == "no-store"
    assert repo.get_save(initial["id"]).state.script_id == script.metadata.id
    assert client.get("/api/saves", headers=auth(b)).json() == []
    assert join(client, b, pair["invite_token"]).status_code == 200
    second = open_save(client, b, pair["id"])
    assert second.status_code == 200 and second.json()["id"] == initial["id"]
    assert second.json()["role"] == "b"
    for actor, role in ((a, "a"), (b, "b")):
        read = client.get(f"/api/saves/{initial['id']}", headers=auth(actor))
        assert read.status_code == 200 and read.json()["role"] == role
        data = read.json()
        assert "state" not in data and "receipts" not in data
        other_devices = {d.id for d in script.devices if d.role != role}
        assert not other_devices.intersection(data["personal"]["devices"])
        for clue in script.clues:
            assert clue.text not in read.text  # initial state has no discoveries
        listing = client.get("/api/saves", headers=auth(actor))
        assert listing.status_code == 200 and len(listing.json()) == 1
        assert "personal" not in listing.text and "invite" not in listing.text
    assert client.get("/api/saves", headers=auth(c)).json() == []
    failure(open_save(client, c, pair["id"]), 404, "SAVE_NOT_FOUND")
    for identifier in (initial["id"], "missing"):
        failure(
            client.get(f"/api/saves/{identifier}", headers=auth(c)),
            404,
            "SAVE_NOT_FOUND",
        )
    failure(
        client.get("/api/saves", params={"pair_id": pair["id"]}, headers=auth(c)),
        404,
        "SAVE_NOT_FOUND",
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"role": "b"},
        {"state": {"completed": True}},
        {"version": 12},
        {"member_a": "forged"},
        {"script_version": None},
    ],
)
def test_strict_creation_input(save_apps, extra):
    factory, _, _, _ = save_apps
    client, repo = factory()
    a = account(client)
    pair = create(client, a)
    failure(open_save(client, a, pair["id"], **extra), 422, "INVALID_INPUT")
    assert repo.get_save_for_pair_script(pair["id"], "lighthouse") is None


def test_exact_version_missing_and_unpublished_do_not_fallback(save_apps):
    factory, store, _, _ = save_apps
    client, repo = factory()
    a = account(client)
    pair = create(client, a)
    failure(open_save(client, a, pair["id"], "9.0.0"), 404, "SCRIPT_NOT_FOUND")
    assert len(store.catalog()) == 1
    assert repo.get_save_for_pair_script(pair["id"], "lighthouse") is None
    response = client.post(
        "/api/saves",
        headers=auth(a),
        json={
            "pair_id": pair["id"],
            "script_id": "unpublished",
            "script_version": "1.0.0",
        },
    )
    failure(response, 404, "SCRIPT_NOT_FOUND")
    missing_version = client.post(
        "/api/saves",
        headers=auth(a),
        json={
            "pair_id": pair["id"],
            "script_id": "lighthouse",
        },
    )
    failure(missing_version, 422, "INVALID_INPUT")


def test_all_save_endpoints_require_identity(save_apps):
    factory, _, _, _ = save_apps
    client, _ = factory()
    for response in (
        client.get("/api/saves"),
        client.get("/api/saves/missing"),
        client.post(
            "/api/saves",
            json={"pair_id": "x", "script_id": "lighthouse", "script_version": "1.0.0"},
        ),
    ):
        failure(response, 401, "UNAUTHENTICATED")


class CreationBarrier:
    """Align real unique inserts; never replace the database result."""

    def __init__(self, repository, barrier):
        self.repository, self.barrier = repository, barrier

    def __getattr__(self, name):
        return getattr(self.repository, name)

    def create_save(self, candidate):
        self.barrier.wait(timeout=10)
        return self.repository.create_save(candidate)


@pytest.mark.parametrize("different_versions", [False, True])
def test_two_independent_apps_create_one_save_atomically(
    save_apps, save_repository_factory, different_versions
):
    factory, _, publish, _ = save_apps
    if different_versions:
        publish(version="2.0.0")
    one, two = (save_repository_factory() for _ in range(2))
    assert one is not two
    barrier = Barrier(2)
    client_a, _ = factory(CreationBarrier(one, barrier))
    client_b, _ = factory(CreationBarrier(two, barrier))
    a, b = account(client_a, "A"), account(client_b, "B")
    pair = create(client_a, a)
    assert join(client_b, b, pair["invite_token"]).status_code == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(open_save, client_a, a, pair["id"], "1.0.0"),
            pool.submit(
                open_save,
                client_b,
                b,
                pair["id"],
                "2.0.0" if different_versions else "1.0.0",
            ),
        ]
        responses = [f.result(timeout=20) for f in futures]
    if different_versions:
        assert sorted(r.status_code for r in responses) == [200, 409]
        failure(
            next(r for r in responses if r.status_code == 409),
            409,
            "SCRIPT_VERSION_CONFLICT",
        )
    else:
        assert [r.status_code for r in responses] == [200, 200]
        assert responses[0].json()["id"] == responses[1].json()["id"]
        assert {r.json()["role"] for r in responses} == {"a", "b"}
    assert len(one.list_saves_for_pair(pair["id"])) == 1
    winner = next(r.json() for r in responses if r.status_code == 200)
    assert one.get_save(winner["id"]).version == 0
    assert one.get_save(winner["id"]).script_version == winner["script_version"]


def test_default_packaged_catalog_is_empty_not_draft(tmp_path):
    from twoworlds.storage.sqlite import SQLiteRepository

    with TestClient(
        create_app(repository=SQLiteRepository(tmp_path / "empty.db"))
    ) as client:
        assert client.get("/api/scripts").json() == []


@pytest.mark.parametrize("shared", [False, True])
def test_progressed_private_shared_projection_survives_closed_app(
    save_repository_factory, published_story, shared
):
    from twoworlds.domain.engine import apply_command, create_initial_state
    from twoworlds.domain.persistence import CommandReceipt, SaveRecord
    from twoworlds.domain.recap import PublicHistory, append_public_history

    store, publish = published_story
    script = publish()
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)

    def app(repo):
        return create_app(
            repository=repo,
            publication_store=store,
            identity_clock=lambda: now,
            rate_limit=100,
        )

    repo = save_repository_factory()
    with TestClient(app(repo)) as client:
        a, b = account(client, "A"), account(client, "B")
        pair = create(client, a)
        assert join(client, b, pair["invite_token"]).status_code == 200
        state = create_initial_state(script)
        history = PublicHistory(script_id="lighthouse", script_version="1.0.0")
        steps = [
            ("a", "inspect", {"target": "maintenance_log"}),
            ("b", "inspect", {"target": "sea_chart"}),
        ]
        if shared:
            steps.append(("a", "share_clue", {"clue_id": "a_maintenance_log"}))
        receipts = []
        for role, kind, args in steps:
            state, events = apply_command(
                state, script, role, {"kind": kind, "args": args}
            )
            history = append_public_history(history, script, state.version, events)
            actor = a if role == "a" else b
            receipts.append(
                CommandReceipt(
                    actor_id=actor["account"]["id"],
                    request_id=uuid4(),
                    fingerprint="a" * 64,
                    accepted_version=state.version,
                    created_at=now,
                )
            )
        # This is a pre-existing persisted fixture, not an HTTP command endpoint.
        repo.create_save(
            SaveRecord(
                id="save_seeded",
                pair_id=pair["id"],
                script_id="lighthouse",
                script_version="1.0.0",
                version=state.version,
                state=state,
                public_history=history,
                receipts=tuple(receipts),
                created_at=now,
                updated_at=now,
            )
        )
        before = [
            client.get("/api/saves/save_seeded", headers=auth(who)).json()
            for who in (a, b)
        ]
    # New client, application and repository after the original DB connection closed.
    with TestClient(app(save_repository_factory())) as client:
        after = [
            client.get("/api/saves/save_seeded", headers=auth(who)) for who in (a, b)
        ]
        assert all(response.status_code == 200 for response in after)
        assert [response.json() for response in after] == before
        assert [c["id"] for c in after[0].json()["personal"]["clues"]] == [
            "a_maintenance_log"
        ]
        assert [c["id"] for c in after[1].json()["personal"]["clues"]] == [
            "b_sea_chart"
        ]
        assert "b_sea_chart" not in after[0].text
        assert ("a_maintenance_log" in after[1].text) is shared
        for response in after:
            public = response.json()["public"]
            assert [c["id"] for c in public["clues"]] == (
                ["a_maintenance_log"] if shared else []
            )
            assert bool(public["events"]) is shared
            assert all(asset.path not in response.text for asset in script.media)
            assert (
                "receipts" not in response.text and "fingerprint" not in response.text
            )


def test_lists_filter_multiple_pairs_and_versions_stay_pinned(save_apps):
    factory, _, publish, _ = save_apps
    client, repo = factory()
    a, b, c = (account(client, r) for r in ("A", "B", "C"))
    pair_a, pair_b = create(client, a), create(client, b)
    first = open_save(client, a, pair_a["id"]).json()
    second = open_save(client, b, pair_b["id"]).json()
    assert join(client, c, pair_b["invite_token"]).status_code == 200
    assert [s["id"] for s in client.get("/api/saves", headers=auth(a)).json()] == [
        first["id"]
    ]
    assert [s["id"] for s in client.get("/api/saves", headers=auth(c)).json()] == [
        second["id"]
    ]
    assert join(client, a, pair_b["invite_token"]).status_code == 409
    publish(version="2.0.0")
    failure(open_save(client, a, pair_a["id"], "2.0.0"), 409, "SCRIPT_VERSION_CONFLICT")
    assert client.get(f"/api/saves/{first['id']}", headers=auth(a)).json() == first
    assert repo.get_save(first["id"]).script_version == "1.0.0"
    selected = client.get(
        "/api/saves", params={"pair_id": pair_b["id"]}, headers=auth(c)
    )
    assert [s["id"] for s in selected.json()] == [second["id"]]


def test_content_corruption_fails_closed_and_hides_paths(save_apps, tmp_path):
    factory, _, _, _ = save_apps
    client, _ = factory()
    a = account(client)
    pair = create(client, a)
    initial = open_save(client, a, pair["id"]).json()
    path = tmp_path / "releases/lighthouse/1.0.0/scripts/lighthouse/1.0.0.json"
    path.write_bytes(path.read_bytes() + b" ")
    for response in (
        client.get("/api/scripts"),
        open_save(client, a, pair["id"]),
        client.get(f"/api/saves/{initial['id']}", headers=auth(a)),
    ):
        failure(response, 503, "CONTENT_UNAVAILABLE")
        assert response.json()["error"]["retryable"]
        assert str(tmp_path) not in response.text and "sha256" not in response.text


def test_removed_pinned_version_never_uses_new_release(save_apps, tmp_path):
    factory, _, publish, _ = save_apps
    client, _ = factory()
    a = account(client)
    pair = create(client, a)
    initial = open_save(client, a, pair["id"]).json()
    publish(version="2.0.0")
    # Hide this test's release as a staging folder without deleting any content.
    path = tmp_path / "releases/lighthouse/1.0.0"
    destination = tmp_path / "releases/lighthouse/.removed-1.0.0"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    assert destination.resolve().is_relative_to(tmp_path.resolve())
    path.rename(destination)
    failure(
        client.get(f"/api/saves/{initial['id']}", headers=auth(a)),
        404,
        "SCRIPT_NOT_FOUND",
    )


def test_published_unsupported_story_refused_without_creating_save(save_apps):
    factory, _, publish, _ = save_apps
    publish(identifier="unsupported_story")
    client, repo = factory()
    a = account(client)
    pair = create(client, a)
    response = client.post(
        "/api/saves",
        headers=auth(a),
        json={
            "pair_id": pair["id"],
            "script_id": "unsupported_story",
            "script_version": "1.0.0",
        },
    )
    failure(response, 409, "SCRIPT_UNSUPPORTED")
    assert repo.list_saves_for_pair(pair["id"]) == ()


def test_dependency_failure_is_safe_and_not_a_false_success(save_apps):
    from twoworlds.ports.repository import RepositoryError

    factory, _, _, _ = save_apps
    client, repo = factory()
    a = account(client)
    pair = create(client, a)

    class FailedWrite:
        def __getattr__(self, name):
            return getattr(repo, name)

        def create_save(self, candidate):
            raise RepositoryError("SECRET_DRIVER_DETAIL")

    failing_client, _ = factory(FailedWrite())
    response = open_save(failing_client, a, pair["id"])
    failure(response, 503, "DEPENDENCY_UNAVAILABLE")
    assert "SECRET_DRIVER_DETAIL" not in response.text
    assert repo.get_save_for_pair_script(pair["id"], "lighthouse") is None
