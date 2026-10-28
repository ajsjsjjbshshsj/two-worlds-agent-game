"""命令通道的并发与幂等契约。

一个写操作要同时满足三件事，本文件逐一验证：
同一请求重发确认同一次成功并返回当前投影（幂等）；不同请求竞争同一版本只有唯一赢家（CAS）；
非法请求必须"什么都没改"（原子拒绝）。
"""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from .support import command, error, ok


def test_old_version_retry_confirms_receipt_and_returns_current_snapshot(
    client_factory,
):
    """断线重发的契约：同一 request_id 重发绝不重复执行。

    客户端拿着 v0 的 expected_version 重发旧请求，服务端应认出幂等键，
    回第一次的回执（duplicate=True）加当前最新快照——而不是回执与
    快照各说各话，也不是把 inspect 执行第二遍。
    """
    game = client_factory()
    a, b, pair = game.pair()
    initial = game.save(a, pair)
    payload = command(initial, "inspect", {"target": "maintenance_log"})
    first = ok(game.post(a, initial, payload))
    # B 在中间又推进一步，世界已经从 v1 走到 v2
    current = game.accept(b, first["save"], "inspect", {"target": "sea_chart"})
    retry = ok(game.post(a, initial, payload))  # 用 v0 的旧载荷原样重发
    assert retry["receipt"] == {**first["receipt"], "duplicate": True}
    # 返回的是最新世界，不是第一版的旧快照
    assert retry["save"] == game.read(a, current)
    assert retry["save"]["version"] > retry["receipt"]["accepted_version"]
    receipt = game.receipt(a, initial, payload["request_id"])
    assert receipt["accepted"] is True
    assert receipt["accepted_version"] == first["receipt"]["accepted_version"]
    # 回执按 actor 隔离：B 查 A 的 request_id 看到的只是"没接受过"
    assert game.receipt(b, initial, payload["request_id"]) == {"accepted": False}


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "set_emitter", "args": {"angle": 90, "pattern": "pulse"}},
        {"args": {"target": "clock_gears"}},
        {"expected_version": 1},
    ],
    ids=["kind", "args", "original-version"],
)
def test_same_actor_cannot_reuse_id_with_changed_payload(client_factory, changes):
    """幂等键钉死整个载荷：换任何内容都按重用拒绝。

    否则重放保护形同虚设——攻击者（或出错的客户端）可以拿一个已成功的
    request_id 夹带新命令。kind、args、expected_version 任何一处不一致
    都必须 409 REQUEST_ID_REUSED，且世界纹丝不动。
    """
    game = client_factory()
    a, b, pair = game.pair()
    save = game.save(a, pair)
    payload = command(save, "inspect", {"target": "maintenance_log"})
    ok(game.post(a, save, payload))
    before = (game.read(a, save), game.read(b, save))
    error(game.post(a, save, {**payload, **changes}), 409, "REQUEST_ID_REUSED")
    assert (game.read(a, save), game.read(b, save)) == before


def test_same_request_id_is_independent_for_other_actor(client_factory):
    """幂等按 actor+request_id 联合区分，不是全局唯一。

    A 和 B 用同一个 request_id 是两条独立命令：各自被接受、各自计版本，
    谁也查不到谁的回执。全局去重会把 B 的合法命令误判成重复。
    """
    game = client_factory()
    a, b, pair = game.pair()
    save = game.save(a, pair)
    request_id = str(uuid4())
    save = game.accept(a, save, "inspect", {"target": "maintenance_log"}, request_id)
    save = game.accept(b, save, "inspect", {"target": "sea_chart"}, request_id)
    # B 的回执版本恰好比 A 的大 1，证明两次都被当成新命令接受
    assert (
        game.receipt(a, save, request_id)["accepted_version"] + 1
        == (game.receipt(b, save, request_id)["accepted_version"])
    )


@pytest.mark.parametrize("same_request", [False, True], ids=["different", "identical"])
def test_two_application_instances_compete_on_one_database(
    client_factory, tmp_path, same_request
):
    """跨设备并发的契约：两个独立应用实例写同一个数据库文件。

    different：两个不同请求同时抢 v0，只能有一个成功，败方收到
    409 VERSION_CONFLICT——CAS 保证不出现双写。
    identical：同一请求并发重发两次，必须都成功且 duplicate 恰好一真一假，
    不允许两边都当成新命令执行。
    """
    path = tmp_path / "shared.db"
    first, second = client_factory(path), client_factory(path)
    a, b, pair = first.pair()
    save = first.save(a, pair)
    payload_a = command(save, "inspect", {"target": "maintenance_log"})
    actor_b = a if same_request else b
    payload_b = (
        payload_a if same_request else command(save, "inspect", {"target": "sea_chart"})
    )
    with ThreadPoolExecutor(2) as pool:
        pending = [
            pool.submit(first.post, a, save, payload_a),
            pool.submit(second.post, actor_b, save, payload_b),
        ]
        responses = [future.result(timeout=10) for future in pending]
    # 只关心结果集合，不假定哪个实例赢
    assert sorted(r.status_code for r in responses) == (
        [200, 200] if same_request else [200, 409]
    )
    assert first.read(a, save)["version"] == save["version"] + 1
    if same_request:
        assert sorted(r.json()["receipt"]["duplicate"] for r in responses) == [
            False,
            True,
        ]
    else:
        loser = next(r for r in responses if r.status_code == 409)
        error(loser, 409, "VERSION_CONFLICT")
        winner_id = next(r for r in responses if r.status_code == 200).json()[
            "receipt"
        ]["request_id"]
        # 只有赢家的 request_id 有 accepted 回执
        for actor, payload in ((a, payload_a), (b, payload_b)):
            assert first.receipt(actor, save, payload["request_id"])["accepted"] == (
                payload["request_id"] == winner_id
            )


@pytest.mark.parametrize(
    "changes",
    [
        {"value": "legacy"},
        {"role": "b"},
        {"expected_version": -1},
        {"expected_version": True},
        {"request_id": "not-a-uuid"},
        {"args": {"target": "maintenance_log", "completed": True}},
    ],
    ids=["legacy-value", "client-role", "negative", "boolean", "bad-id", "extra-arg"],
)
def test_invalid_command_does_not_change_save_or_create_receipt(
    client_factory, changes
):
    """非法命令必须"三无"：不改存档、不建回执、留下 accepted=False 的痕迹。

    六种畸形载荷：旧草稿的字段名、客户端伪造角色、负版本号、
    布尔版本号（Python 里 True == 1，必须显式拒绝而不是当成 1）、
    非法幂等键、以及在 args 里夹带结果字段（不能靠客户端宣布"已完成"）。
    """
    game = client_factory()
    a, b, pair = game.pair()
    save = game.save(a, pair)
    before = (game.read(a, save), game.read(b, save))
    payload = {**command(save, "inspect", {"target": "maintenance_log"}), **changes}
    error(game.post(a, save, payload), 422)
    assert (game.read(a, save), game.read(b, save)) == before
    # request_id 本身不合法时无法登记回执，所以跳过这条断言
    if changes.get("request_id") != "not-a-uuid":
        assert game.receipt(a, save, payload["request_id"]) == {"accepted": False}
