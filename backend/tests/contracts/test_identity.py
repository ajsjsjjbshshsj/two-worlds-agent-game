import pytest

from .support import error, ok


def test_recovery_proves_ownership_and_issues_a_distinct_session(client_factory):
    game = client_factory()
    a = game.account()
    assert a.recovery_key != a.token
    restored = game.recover(a)
    assert restored.account_id == a.account_id and restored.token != a.token
    me = ok(game.http.get("/api/me", headers=restored.headers))
    assert me["account"]["id"] == a.account_id
    assert me["session"]["expires_at"]
    assert "recovery_key" not in me
    for token in (a.recovery_key, "forged"):
        error(
            game.http.get("/api/me", headers={"Authorization": f"Bearer {token}"}),
            401,
        )


@pytest.mark.parametrize("field", ["account_id", "player_id", "role"])
def test_client_cannot_claim_identity_or_role(client_factory, field):
    game = client_factory()
    a = game.account()
    error(
        game.http.post(
            "/api/accounts", json={"display_name": "旅人", field: a.account_id}
        ),
        422,
    )
    error(game.http.post("/api/sessions/recover", json={field: a.account_id}), 422)


def test_display_name_does_not_restore_another_account(client_factory):
    game = client_factory()
    first, second = game.account("同名"), game.account("同名")
    assert first.account_id != second.account_id
    error(game.http.post("/api/sessions/recover", json={"display_name": "同名"}), 422)


def test_logout_revokes_only_the_current_session(client_factory):
    game = client_factory()
    a = game.account()
    restored = game.recover(a)
    response = game.http.delete("/api/sessions/current", headers=a.headers)
    assert response.status_code == 204, response.text
    error(game.http.get("/api/me", headers=a.headers), 401)
    assert game.http.get("/api/me", headers=restored.headers).status_code == 200
