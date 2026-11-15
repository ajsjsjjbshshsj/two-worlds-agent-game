from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import logging
from threading import Barrier, Event

from fastapi.testclient import TestClient
import pytest

from tests.storage.conftest import sqlite_repository_factory  # noqa: F401
from twoworlds.api.app import create_app


@pytest.fixture(params=["sqlite", "mongo"])
def pair_repository_factory(request):
    return request.getfixturevalue(f"{request.param}_repository_factory")


@pytest.fixture
def apps(pair_repository_factory):
    clock = [datetime(2026, 11, 15, tzinfo=timezone.utc)]
    with ExitStack() as stack:

        def factory(repository=None):
            repo = pair_repository_factory() if repository is None else repository
            app = create_app(
                repository=repo,
                identity_clock=lambda: clock[0],
                rate_limit=100,
                allowed_origins=["http://testserver"],
            )
            return stack.enter_context(TestClient(app)), repo, app

        yield factory, clock


def account(client, name="玩家"):
    response = client.post("/api/accounts", json={"display_name": name})
    assert response.status_code == 200
    return response.json()


def auth(who):
    return {"Authorization": "Bearer " + who["session"]["token"]}


def create(client, who):
    response = client.post("/api/pairs", headers=auth(who))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def join(client, who, token):
    return client.post(
        "/api/pairs/join", headers=auth(who), json={"invite_token": token}
    )


def failure(response, status, code):
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {
        "code",
        "message",
        "retryable",
    }
    assert body["error"]["code"] == code


def test_create_join_lists_and_secret_whitelists(apps, caplog):
    from twoworlds.security.credentials import digest_secret

    caplog.set_level(logging.INFO)
    factory, clock = apps
    client, repo, app = factory()
    a, b, c = [account(client) for _ in range(3)]
    made = create(client, a)
    assert set(made) == {"id", "role", "invite_token", "invite_expires_at"}
    assert made["role"] == "a"
    assert datetime.fromisoformat(made["invite_expires_at"]) == clock[0] + timedelta(
        hours=24
    )
    stored = repo.get_pair(made["id"])
    assert stored.member_a == a["account"]["id"] and stored.member_b is None
    assert stored.invite_digest == digest_secret(made["invite_token"], "invite")
    failure(join(client, a, made["invite_token"]), 404, "INVITE_INVALID")
    joined = join(client, b, made["invite_token"])
    assert joined.status_code == 200 and joined.json() == {
        "id": made["id"],
        "role": "b",
    }
    assert joined.headers["cache-control"] == "no-store"
    version = repo.get_pair(made["id"]).version
    assert join(client, b, made["invite_token"]).json() == joined.json()
    assert repo.get_pair(made["id"]).version == version
    failure(join(client, c, made["invite_token"]), 409, "PAIR_FULL")
    for actor, role in ((a, "a"), (b, "b")):
        response = client.get("/api/pairs", headers=auth(actor))
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == [{"id": made["id"], "role": role, "member_count": 2}]
        for secret in (
            made["invite_token"],
            stored.invite_digest,
            a["recovery_key"],
            a["session"]["token"],
        ):
            assert secret not in response.text
    assert client.get("/api/pairs", headers=auth(c)).json() == []
    assert made["invite_token"] not in stored.model_dump_json() + caplog.text
    assert stored.invite_digest not in caplog.text
    other_client, _, other_app = factory()
    assert app.state.pair_service is not other_app.state.pair_service
    assert other_client.get("/api/pairs", headers=auth(b)).json()[0]["id"] == made["id"]


def test_refresh_permissions_expiry_and_new_invite(apps):
    factory, clock = apps
    client, repo, _ = factory()
    a, b = account(client), account(client)
    made = create(client, a)
    path = f"/api/pairs/{made['id']}/invite"
    failure(client.post(path, headers=auth(b)), 404, "PAIR_NOT_FOUND")
    failure(
        client.post("/api/pairs/missing/invite", headers=auth(a)), 404, "PAIR_NOT_FOUND"
    )
    clock[0] += timedelta(days=1)
    failure(join(client, b, made["invite_token"]), 404, "INVITE_INVALID")
    response = client.post(path, headers=auth(a), json={})
    assert (
        response.status_code == 200 and response.headers["cache-control"] == "no-store"
    )
    fresh = response.json()
    assert set(fresh) == set(made) and fresh["invite_token"] != made["invite_token"]
    assert datetime.fromisoformat(fresh["invite_expires_at"]) == clock[0] + timedelta(
        days=1
    )
    failure(join(client, b, made["invite_token"]), 404, "INVITE_INVALID")
    assert join(client, b, fresh["invite_token"]).status_code == 200
    before = repo.get_pair(made["id"])
    failure(client.post(path, headers=auth(a)), 409, "PAIR_FULL")
    failure(client.post(path, headers=auth(b)), 404, "PAIR_NOT_FOUND")
    clock[0] += timedelta(days=2)
    assert join(client, b, fresh["invite_token"]).status_code == 200
    assert repo.get_pair(made["id"]) == before


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/pairs"),
        ("GET", "/api/pairs"),
        ("POST", "/api/pairs/join"),
        ("POST", "/api/pairs/unknown/invite"),
    ],
)
def test_all_pair_routes_require_bearer(apps, method, path):
    factory, _ = apps
    client, _, _ = factory()
    failure(client.request(method, path), 401, "UNAUTHENTICATED")


@pytest.mark.parametrize("operation", ["create", "refresh", "join"])
@pytest.mark.parametrize("field", ["member_a", "member_b", "role", "account_id"])
def test_client_cannot_choose_members_or_role(apps, operation, field):
    factory, _ = apps
    client, _, _ = factory()
    a, b = account(client), account(client)
    made = create(client, a)
    paths = {
        "create": "/api/pairs",
        "refresh": f"/api/pairs/{made['id']}/invite",
        "join": "/api/pairs/join",
    }
    body = {field: "forged"}
    if operation == "join":
        body["invite_token"] = made["invite_token"]
    failure(
        client.post(
            paths[operation], headers=auth(b if operation == "join" else a), json=body
        ),
        422,
        "INVALID_INPUT",
    )


def test_wrong_credential_namespaces_and_restarted_app(apps):
    factory, _ = apps
    client, repo, _ = factory()
    a, b = account(client), account(client)
    made = create(client, a)
    for value in (a["recovery_key"], a["session"]["token"], "wrong"):
        failure(join(client, b, value), 404, "INVITE_INVALID")
    failure(
        client.get(
            "/api/pairs", headers={"Authorization": "Bearer " + made["invite_token"]}
        ),
        401,
        "UNAUTHENTICATED",
    )
    repo.close()
    second, _, _ = factory()
    recovered = second.post(
        "/api/sessions/recover", json={"recovery_key": a["recovery_key"]}
    )
    assert recovered.status_code == 200
    response = second.get("/api/pairs", headers=auth(recovered.json()))
    assert response.json() == [{"id": made["id"], "role": "a", "member_count": 1}]
    assert join(second, b, made["invite_token"]).status_code == 200


class WriteBarrier:
    """Align real DB writes; never synthesize CAS/join success or share a DB object."""

    def __init__(self, repository, barrier, done, action, winner=None):
        self.repository, self.barrier, self.done = repository, barrier, done
        self.action, self.winner, self.fired = action, winner, False

    def __getattr__(self, name):
        return getattr(self.repository, name)

    def _write(self, method, *args):
        first = not self.fired
        if first:
            self.fired = True
            self.barrier.wait(timeout=15)
            if self.winner and self.action != self.winner:
                assert self.done.wait(timeout=15)
        try:
            return method(*args)
        finally:
            if first and self.action == self.winner:
                self.done.set()

    def join_pair(self, *args):
        return self._write(self.repository.join_pair, *args)

    def compare_and_swap_pair(self, *args):
        return self._write(self.repository.compare_and_swap_pair, *args)


@pytest.mark.parametrize("same_actor", [False, True])
def test_two_independent_apps_compete_for_b(apps, pair_repository_factory, same_actor):
    factory, _ = apps
    barrier, done = Barrier(2), Event()
    repositories = [pair_repository_factory(), pair_repository_factory()]
    assert repositories[0] is not repositories[1]
    first, _, _ = factory(WriteBarrier(repositories[0], barrier, done, "join"))
    second, _, _ = factory(WriteBarrier(repositories[1], barrier, done, "join"))
    a, b, c = account(first), account(first), account(first)
    if same_actor:
        c = b
    made = create(first, a)
    with ThreadPoolExecutor(2) as pool:
        futures = [
            pool.submit(join, client, who, made["invite_token"])
            for client, who in ((first, b), (second, c))
        ]
        responses = [f.result(timeout=25) for f in futures]
    assert sorted(r.status_code for r in responses) == (
        [200, 200] if same_actor else [200, 409]
    )
    winner = b if responses[0].status_code == 200 else c
    assert join(second, winner, made["invite_token"]).status_code == 200
    stored = repositories[0].get_pair(made["id"])
    assert stored.member_b == winner["account"]["id"] and stored.version == 1


@pytest.mark.parametrize("winner", ["join", "refresh", None])
def test_invite_refresh_and_join_compete_atomically(
    apps, pair_repository_factory, winner
):
    factory, _ = apps
    barrier, done = Barrier(2), Event()
    repositories = [pair_repository_factory(), pair_repository_factory()]
    assert repositories[0] is not repositories[1]
    first, _, _ = factory(
        WriteBarrier(repositories[0], barrier, done, "refresh", winner)
    )
    second, _, _ = factory(WriteBarrier(repositories[1], barrier, done, "join", winner))
    a, b = account(first), account(first)
    made = create(first, a)
    with ThreadPoolExecutor(2) as pool:
        refreshing = pool.submit(
            first.post, f"/api/pairs/{made['id']}/invite", headers=auth(a)
        )
        joining = pool.submit(join, second, b, made["invite_token"])
        refreshed, joined = refreshing.result(timeout=25), joining.result(timeout=25)
    stored = repositories[0].get_pair(made["id"])
    assert stored.version == 1
    if joined.status_code == 200:
        assert refreshed.status_code == 409 and stored.member_b == b["account"]["id"]
        assert winner != "refresh"
    else:
        assert refreshed.status_code == 200 and joined.status_code == 404
        assert stored.member_b is None and winner != "join"
        failure(join(second, b, made["invite_token"]), 404, "INVITE_INVALID")
        assert join(second, b, refreshed.json()["invite_token"]).status_code == 200


@pytest.mark.parametrize(
    "code,status,retryable",
    [
        ("INVITE_INVALID", 404, False),
        ("PAIR_NOT_FOUND", 404, False),
        ("PAIR_FULL", 409, False),
        ("CONCURRENT_UPDATE", 409, True),
        ("DEPENDENCY_UNAVAILABLE", 503, True),
        ("GENERATION_FAILED", 503, True),
        ("CLOCK_ERROR", 503, True),
    ],
)
def test_pair_error_http_mapping(clients, code, status, retryable):
    from twoworlds.application.pairs import PairError

    client, app, _ = clients()

    @app.get("/test-pair-error")
    def route():
        raise PairError(code)

    response = client.get("/test-pair-error")
    failure(response, status, code)
    assert response.json()["error"]["retryable"] is retryable
