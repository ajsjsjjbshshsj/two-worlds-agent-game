import pytest

from .support import error, ok

ORIGIN = {"Origin": "http://testserver"}


def test_login_proves_ownership_and_issues_a_distinct_session(client_factory):
    game = client_factory()
    a = game.account()
    restored = game.login(a)
    assert restored.account_id == a.account_id and restored.token != a.token
    me = ok(game.http.get("/api/me", headers=restored.headers))
    assert me["account"]["id"] == a.account_id
    assert me["account"]["email"] == a.email
    assert me["session"]["expires_at"]
    assert "password" not in me and "token" not in me["session"]
    # 旧会话仍然有效；Bearer 头不再被接受，伪造 Cookie 一律 401。
    assert game.http.get("/api/me", headers=a.headers).status_code == 200
    for headers in (
        {"Cookie": "other=none"},
        {"Cookie": "tw_session=forged"},
        {"Cookie": "other=none", "Authorization": f"Bearer {a.token}"},
    ):
        error(game.http.get("/api/me", headers=headers), 401)


@pytest.mark.parametrize("field", ["account_id", "player_id", "role"])
def test_client_cannot_claim_identity_or_role(client_factory, field):
    game = client_factory()
    a = game.account()
    error(
        game.http.post(
            "/api/accounts",
            json={"display_name": "旅人", field: a.account_id},
            headers=ORIGIN,
        ),
        422,
    )
    error(
        game.http.post(
            "/api/sessions",
            json={"email": a.email, "password": a.password, field: a.account_id},
            headers=ORIGIN,
        ),
        422,
    )


def test_display_name_does_not_restore_another_account(client_factory):
    game = client_factory()
    first, second = game.account("同名"), game.account("同名")
    assert first.account_id != second.account_id
    assert first.email != second.email
    error(
        game.http.post("/api/sessions", json={"display_name": "同名"}, headers=ORIGIN),
        422,
    )
    # 同名不等于同账号：拿别人的密码登自己的邮箱必须失败。
    error(
        game.http.post(
            "/api/sessions",
            json={"email": first.email, "password": second.password + "!"},
            headers=ORIGIN,
        ),
        401,
    )


def test_logout_revokes_only_the_current_session(client_factory):
    game = client_factory()
    a = game.account()
    restored = game.login(a)
    response = game.http.delete("/api/sessions/current", headers=a.headers)
    assert response.status_code == 204, response.text
    error(game.http.get("/api/me", headers=a.headers), 401)
    assert game.http.get("/api/me", headers=restored.headers).status_code == 200


def test_password_reset_revokes_every_session(client_factory):
    game = client_factory()
    a = game.account()
    other = game.login(a)
    sender = game.http.app.state.email_sender
    assert (
        game.http.post(
            "/api/verification-codes",
            json={"email": a.email, "purpose": "reset"},
            headers=ORIGIN,
        ).status_code
        == 202
    )
    response = game.http.post(
        "/api/password-resets",
        json={
            "email": a.email,
            "code": sender.code_for(a.email, "reset"),
            "new_password": "reset password 42",
        },
        headers=ORIGIN,
    )
    assert response.status_code == 204, response.text
    for identity in (a, other):
        error(game.http.get("/api/me", headers=identity.headers), 401)
    error(
        game.http.post(
            "/api/sessions",
            json={"email": a.email, "password": a.password},
            headers=ORIGIN,
        ),
        401,
    )
    fresh = ok(
        game.http.post(
            "/api/sessions",
            json={"email": a.email, "password": "reset password 42"},
            headers=ORIGIN,
        )
    )
    assert fresh["account"]["id"] == a.account_id
