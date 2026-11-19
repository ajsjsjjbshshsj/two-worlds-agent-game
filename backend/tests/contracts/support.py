"""契约测试的 HTTP 词汇表。

这里的方法驱动真实 FastAPI 应用（TestClient），不 mock：身份隔离、角色投影、
版本 CAS 与幂等回执这些契约，只有打到真应用上验证才有意义。
"""

from dataclasses import dataclass
from uuid import uuid4


def ok(response, status=200):
    """断言状态码符合预期，并返回解析后的 JSON。

    失败时把服务端原始正文带进报错，才能直接看到具体错误码，
    而不是只知道"状态码不对"。
    """
    assert response.status_code == status, response.text
    return response.json()


def error(response, status, code=None):
    """断言请求被拒绝，且错误符合 {error:{code,message,retryable}} 契约（docs/03）。

    code 可选：不传只验信封形状，传了再做精确匹配。返回内层错误体。
    """
    body = ok(response, status)["error"]  # 顺带排除 FastAPI 默认的 {"detail": ...}
    # code 给程序分支用、message 给人读；空串也满足 isinstance，所以还要判真值
    assert isinstance(body["code"], str) and body["code"]
    assert isinstance(body["message"], str) and body["message"]
    # retryable=False 是合法值，不能写成真值判断
    assert isinstance(body["retryable"], bool)
    if code is not None:
        assert body["code"] == code
    return body


@dataclass(frozen=True)
class Identity:
    """一个账号的凭证组。frozen 防止测试中途改写，否则"旧会话是否仍有效"类断言不可信。"""

    account_id: str  # 服务端分配的稳定标识，不是凭证
    email: str  # 规范化后的登录邮箱
    password: str  # 测试用明文密码，只存在于测试进程
    token: str  # 会话 Cookie 值，放进 Cookie 头

    @property
    def headers(self):
        # 显式 Cookie 头覆盖 TestClient cookie jar，一个客户端可扮演多个身份。
        # Origin 满足状态变更请求的 CSRF 白名单校验。
        return {"Cookie": f"tw_session={self.token}", "Origin": "http://testserver"}


class Platform:
    """按接口类别封装的一组动作；每个封装里顺手守住契约不变量。"""

    def __init__(self, client, close_app):
        self.http = client  # fastapi.testclient.TestClient，背后是真实应用
        self.close = close_app  # 关闭当前应用实例，用于测试"重启后恢复"

    def account(self, name="旅人"):
        """邮箱验证码注册即登录：拿到账号概要和会话 Cookie。"""
        from uuid import uuid4

        email = f"contract-{uuid4().hex[:12]}@example.com"
        sender = self.http.app.state.email_sender
        codes = self.http.post(
            "/api/verification-codes",
            json={"email": email, "purpose": "register"},
            headers={"Origin": "http://testserver"},
        )
        assert codes.status_code == 202, codes.text
        assert self.http.app.state.verification_service.wait_for_delivery(10)
        code = sender.code_for(email, "register")
        response = self.http.post(
            "/api/accounts",
            json={
                "email": email,
                "code": code,
                "password": "correct horse 9",
                "display_name": name,
            },
            headers={"Origin": "http://testserver"},
        )
        body = ok(response)
        # 含凭证的响应不许被浏览器或中间缓存保存
        assert response.headers["cache-control"] == "no-store"
        assert body["session"]["expires_at"]  # 会话必须有期限
        # 明文 token 只经 HttpOnly Cookie 下发，绝不进入 JSON 正文
        assert "token" not in body["session"]
        token = response.cookies.get("tw_session")
        assert token
        return Identity(body["account"]["id"], email, "correct horse 9", token)

    def login(self, identity):
        """邮箱密码登录，换取新会话 Cookie。"""
        response = self.http.post(
            "/api/sessions",
            json={"email": identity.email, "password": identity.password},
            headers={"Origin": "http://testserver"},
        )
        body = ok(response)
        assert response.headers["cache-control"] == "no-store"
        assert "token" not in body["session"]
        token = response.cookies.get("tw_session")
        assert token and token != identity.token
        return Identity(identity.account_id, identity.email, identity.password, token)

    def pair(self, a=None, b=None):
        """A 建房、B 持邀请令牌加入。"""
        # 写成函数调用而非默认参数值：默认参数只在定义时求值一次，
        # 那样所有测试会共用同一对账号
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
        # 角色由服务端分配，不信任客户端自报：先建者是 a，加入者是 b
        assert pair["role"] == "a" and joined["role"] == "b"
        return a, b, pair

    def save(self, actor, pair, script="lighthouse", version="1.0.0"):
        """开档。同一房间同一剧本只有一份存档，重复开档返回同一份。"""
        return ok(
            self.http.post(
                "/api/saves",
                headers=actor.headers,
                # The fixture seals 1.0.0; never ask the server to guess latest.
                json={
                    "pair_id": pair["id"],
                    "script_id": script,
                    "script_version": version,
                },
            )
        )

    def read(self, actor, save):
        """读取存档。返回的是该角色视角的投影：对方的私密线索不会出现在这里。"""
        return ok(self.http.get(f"/api/saves/{save['id']}", headers=actor.headers))

    def post(self, actor, save, payload):
        """提交命令，原样返回 Response 不断言——留给"期望失败"的测试配合 error() 使用。"""
        return self.http.post(
            f"/api/saves/{save['id']}/commands", headers=actor.headers, json=payload
        )

    def accept(self, actor, save, kind, args=None, request_id=None):
        """提交命令并断言这一步被接受，返回推进后的新快照。

        调用方必须写 save = game.accept(...)：新快照的 version 是下一步
        expected_version 的来源，漏掉赋值会让下一步因版本过旧而被 409 拒绝。
        """
        payload = command(save, kind, args, request_id)
        result = ok(self.post(actor, save, payload))
        # 用整字典精确相等：服务端多返回字段、版本跳号或误判重复都会让测试红
        assert result["receipt"] == {
            "request_id": payload["request_id"],
            "status": "accepted",
            "accepted_version": save["version"] + 1,  # 每次成功只允许 +1
            "duplicate": False,
        }
        snapshot = result["save"]
        assert snapshot["id"] == save["id"]
        assert snapshot["script_version"] == save["script_version"]  # 存档锁定剧本版本
        assert snapshot["version"] == result["receipt"]["accepted_version"]
        return snapshot

    def receipt(self, actor, save, request_id):
        """查询幂等回执：请求超时或重发后，用它确认这一步到底有没有被接受。"""
        receipt = ok(
            self.http.get(
                f"/api/saves/{save['id']}/receipts/{request_id}", headers=actor.headers
            )
        )
        assert isinstance(receipt["accepted"], bool)
        if receipt["accepted"]:
            assert receipt["request_id"] == request_id
        # 未接受时只回 {"accepted": False}，不泄露请求详情
        return receipt


def command(save, kind, args=None, request_id=None):
    """命令请求体的最小模板：幂等键 + 乐观锁版本 + 动作。"""
    return {
        "request_id": request_id or str(uuid4()),  # 幂等键：重发同一 ID 不会重复执行
        "expected_version": save[
            "version"
        ],  # 新请求检查版本；已接受的原请求先查幂等回执
        "kind": kind,
        "args": {} if args is None else args,  # 服务端要求该字段必须存在且为对象
    }


def lighthouse_to_decision(game, a, b, save):
    """按 docs/02 的验收轨迹把《跨时灯塔》推进到 decision 场景，不投票。

    每一步都踩在前一步产生的事实上：两次 set_emitter 才凑齐有效锁定条件
    （日志、航道图、90°、pulse、amber），route_power 到 tower 后 A 才能检查
    齿轮并维修。顺序调换会被前置条件挡下（422）。
    """
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
    # 停在选择结局：投哪个结局由调用它的测试自己决定
    assert save["scene_id"] == "decision" and not save["completed"]
    return save


def starline_to_decision(game, a, b, save):
    """按 docs/02 的验收轨迹把《末班星轨》推进到 decision 场景，不投票。

    本剧本的机制是功率预算（总量 5）：勘测要求 sonar 开、engine 关，装好
    导轨后，确认信号需要信号灯开启；发车还需要引擎开启、声呐关闭。
    两次allocate_power用于勘测/发车切换，是机制的一部分。
    """
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
