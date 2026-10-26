from dataclasses import dataclass
from uuid import uuid4


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def error(response, status, code=None):
    body = ok(response, status)["error"]
    assert isinstance(body["code"], str) and body["code"]
    assert isinstance(body["message"], str) and body["message"]
    assert isinstance(body["retryable"], bool)
    if code is not None:
        assert body["code"] == code
    return body


@dataclass(frozen=True)
class Identity:
    account_id: str
    recovery_key: str
    token: str

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}


class Platform:
    """Small HTTP vocabulary; assertions still exercise the real application."""

    def __init__(self, client, close_app):
        self.http = client
        self.close = close_app

    def account(self, name="旅人"):
        response = self.http.post("/api/accounts", json={"display_name": name})
        body = ok(response)
        assert response.headers["cache-control"] == "no-store"
        assert body["session"]["expires_at"]
        return Identity(
            body["account"]["id"], body["recovery_key"], body["session"]["token"]
        )

    def recover(self, identity):
        response = self.http.post(
            "/api/sessions/recover", json={"recovery_key": identity.recovery_key}
        )
        body = ok(response)
        assert response.headers["cache-control"] == "no-store"
        assert "recovery_key" not in body
        return Identity(
            body["account"]["id"], identity.recovery_key, body["session"]["token"]
        )

    def pair(self, a=None, b=None):
        a, b = a or self.account("A"), b or self.account("B")
        pair = ok(self.http.post("/api/pairs", headers=a.headers))
        joined = ok(
            self.http.post(
                "/api/pairs/join",
                headers=b.headers,
                json={"invite_token": pair["invite_token"]},
            )
        )
        assert pair["id"] == joined["id"]
        assert pair["role"] == "a" and joined["role"] == "b"
        return a, b, pair

    def save(self, actor, pair, script="lighthouse"):
        return ok(
            self.http.post(
                "/api/saves",
                headers=actor.headers,
                json={"pair_id": pair["id"], "script_id": script},
            )
        )

    def read(self, actor, save):
        return ok(self.http.get(f"/api/saves/{save['id']}", headers=actor.headers))

    def post(self, actor, save, payload):
        return self.http.post(
            f"/api/saves/{save['id']}/commands", headers=actor.headers, json=payload
        )

    def accept(self, actor, save, kind, args=None, request_id=None):
        payload = command(save, kind, args, request_id)
        result = ok(self.post(actor, save, payload))
        assert result["receipt"] == {
            "request_id": payload["request_id"],
            "status": "accepted",
            "accepted_version": save["version"] + 1,
            "duplicate": False,
        }
        snapshot = result["save"]
        assert snapshot["id"] == save["id"]
        assert snapshot["script_version"] == save["script_version"]
        assert snapshot["version"] == result["receipt"]["accepted_version"]
        return snapshot

    def receipt(self, actor, save, request_id):
        receipt = ok(
            self.http.get(
                f"/api/saves/{save['id']}/receipts/{request_id}", headers=actor.headers
            )
        )
        assert isinstance(receipt["accepted"], bool)
        if receipt["accepted"]:
            assert receipt["request_id"] == request_id
        return receipt


def command(save, kind, args=None, request_id=None):
    return {
        "request_id": request_id or str(uuid4()),
        "expected_version": save["version"],
        "kind": kind,
        "args": {} if args is None else args,
    }


def lighthouse_to_decision(game, a, b, save):
    steps = [
        (a, "inspect", {"target": "maintenance_log"}),
        (b, "inspect", {"target": "sea_chart"}),
        (a, "set_emitter", {"angle": 0, "pattern": "pulse"}),
        (b, "set_filter", {"filter": "amber"}),
        (a, "set_emitter", {"angle": 90, "pattern": "pulse"}),
        (b, "lock_signal", {}),
        (b, "route_power", {"target": "tower"}),
        (a, "inspect", {"target": "clock_gears"}),
        (a, "repair_clock", {"mode": "steady"}),
        (b, "confirm_route", {}),
    ]
    for actor, kind, args in steps:
        save = game.accept(actor, save, kind, args)
    assert save["scene_id"] == "decision" and not save["completed"]
    return save


def starline_to_decision(game, a, b, save):
    steps = [
        (a, "inspect", {"target": "station_log"}),
        (b, "inspect", {"target": "power_board"}),
        (a, "set_echo_gate", {"position": "east"}),
        (b, "allocate_power", {"engine": False, "sonar": True, "lamp": True}),
        (b, "scan_track", {}),
        (a, "install_rail", {"segment": "bridge_2"}),
        (b, "allocate_power", {"engine": True, "sonar": False, "lamp": True}),
        (b, "confirm_signal", {}),
        (a, "set_platform", {"track": "track_2"}),
        (b, "dispatch_train", {}),
    ]
    for actor, kind, args in steps:
        save = game.accept(actor, save, kind, args)
    assert save["scene_id"] == "decision" and not save["completed"]
    return save
