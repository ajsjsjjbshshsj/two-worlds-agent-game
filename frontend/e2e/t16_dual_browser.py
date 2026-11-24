"""T16 dual-browser acceptance: real API, real storage, real WebSocket.

Two fully independent browser contexts (separate cookies/storage/network) play
one account each against a real FastAPI child process and a production Vite
preview. Every HTTP response body and WebSocket frame is captured per context
and checked for cross-role private leakage; UI actions drive both scripts.

Run from frontend with backend venv synced (dev group includes playwright):
  T16_STORAGE=sqlite python e2e/t16_dual_browser.py
  T16_STORAGE=mongo MONGO_URI=... python e2e/t16_dual_browser.py
T16_BROWSER selects the channel (msedge/chrome on Windows, chromium in CI).
T16_BROWSER_EXECUTABLE can point to an installed Chromium for local runs.
No response mocks: only the console email transport is a dev adapter.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

from pwa_cache import ROOT, free_port, wait_url

BACKEND = ROOT.parent / "backend"
OUT = ROOT / "test-results" / "t16"
PYTHON = (
    BACKEND / ".venv/Scripts/python.exe"
    if os.name == "nt"
    else BACKEND / ".venv/bin/python"
)
NPM = "npm.cmd" if os.name == "nt" else "npm"
CHANNEL = os.environ.get("T16_BROWSER", "msedge" if os.name == "nt" else "chromium")
WIDTH, HEIGHT = (
    int(value) for value in os.environ.get("T16_VIEWPORT", "1280x900").split("x")
)
TOUCH = os.environ.get("T16_TOUCH", "0") == "1"
ENDING = os.environ.get("T16_ENDING", "guide_now")
OTHER_ENDING = "wait_tide" if ENDING == "guide_now" else "guide_now"
PASSWORD = "test-only-password-123"
SCRIPTS = {
    script: json.loads(
        (BACKEND / f"src/twoworlds/content/scripts/{script}/1.0.0.json").read_text(
            "utf-8"
        )
    )
    for script in ("lighthouse", "starline")
}
SHARED_CLUES = {"lighthouse": {"a_maintenance_log"}, "starline": set()}
PRIVATE = {
    script: {
        role: {
            c["id"]: c["text"]
            for c in data["clues"]
            if c["role"] == role and c["id"] not in SHARED_CLUES[script]
        }
        for role in ("a", "b")
    }
    for script, data in SCRIPTS.items()
}
SHARED = {
    script: {
        c["id"]: c["text"] for c in data["clues"] if c["id"] in SHARED_CLUES[script]
    }
    for script, data in SCRIPTS.items()
}


@contextmanager
def real_stack(storage):
    OUT.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix=f"t16-{storage}-", dir=OUT) as directory,
        ExitStack() as stack,
    ):
        folder = Path(directory)
        api_port, ui_port = free_port(), free_port()
        api = f"http://127.0.0.1:{api_port}"
        base = f"http://127.0.0.1:{ui_port}"
        worker = folder / "server.py"
        worker.write_text(
            """from pathlib import Path
import sys
from tests.save_support import make_publications
from twoworlds.content.publication import PublicationStore
from twoworlds.dev import create_dev_app
import uvicorn
root = Path(sys.argv[1])
releases = root / "releases"
if releases.exists():
    store = PublicationStore(releases)
else:
    store, publish = make_publications(root)
    publish(); publish(identifier="starline")
app = create_dev_app(publication_store=store)
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[2]),
            access_log=False, log_level="critical", ws="websockets-sansio")
""",
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "PYTHONPATH": str(BACKEND),
            "TWOWORLDS_ALLOWED_ORIGINS": base,
            "TWOWORLDS_EMAIL_MODE": "console",
            "TWOWORLDS_COOKIE_SECURE": "0",
        }
        if storage == "mongo":
            env["TWOWORLDS_STORAGE_BACKEND"] = "mongo"
            env["MONGO_DATABASE"] = "t16_" + uuid4().hex[:12]
        else:
            env["TWOWORLDS_STORAGE_BACKEND"] = "sqlite"
            env["TWOWORLDS_SQLITE_PATH"] = str(folder / "game.sqlite")
        console = stack.enter_context((folder / "console.log").open("w"))

        def spawn():
            return subprocess.Popen(
                [str(PYTHON), str(worker), str(folder), str(api_port)],
                cwd=BACKEND,
                env=env,
                stdout=console,
                stderr=console,
            )

        child = spawn()

        def stop(process):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)

        stack.callback(lambda: stop(child))

        def wait_api():
            for _ in range(300):
                if child.poll() is not None:
                    raise AssertionError(
                        "API child exited: "
                        + (folder / "console.log").read_text("utf-8")[-800:]
                    )
                try:
                    urllib.request.urlopen(api + "/api/scripts", timeout=1).close()
                    return
                except OSError:
                    time.sleep(0.1)
            raise AssertionError("API did not start in 30s")

        wait_api()

        def restart():
            nonlocal child
            stop(child)
            child = spawn()
            wait_api()

        subprocess.run([NPM, "run", "build"], cwd=ROOT, check=True, capture_output=True)
        settings = folder / "preview.config.mjs"
        settings.write_text(
            "export default "
            + json.dumps(
                dict(
                    root=str(ROOT),
                    preview=dict(proxy={"/api": dict(target=api, ws=True)}),
                )
            )
            + ";",
            encoding="utf-8",
        )
        preview_log = stack.enter_context((folder / "preview.log").open("w"))
        vite = subprocess.Popen(
            [
                "node",
                str(ROOT / "node_modules/vite/bin/vite.js"),
                "preview",
                "--host",
                "127.0.0.1",
                "--port",
                str(ui_port),
                "--strictPort",
                "--config",
                str(settings),
            ],
            cwd=ROOT,
            stdout=preview_log,
            stderr=preview_log,
        )
        stack.callback(stop, vite)
        wait_url(base)
        yield dict(
            folder=folder,
            base=base,
            api=api,
            env=env,
            restart=restart,
            storage=storage,
        )


def console_code(folder, email, purpose="register"):
    pattern = re.compile(rf"to={re.escape(email)} purpose={purpose} code=([0-9]{{6}})")
    for _ in range(200):
        match = pattern.search((folder / "console.log").read_text("utf-8"))
        if match:
            return match.group(1)
        time.sleep(0.05)
    raise AssertionError(f"no {purpose} code printed for {email}")


def register(client, folder, email, name):
    assert (
        client.post(
            "/api/verification-codes", json=dict(email=email, purpose="register")
        ).status_code
        == 202
    )
    response = client.post(
        "/api/accounts",
        json=dict(
            email=email,
            code=console_code(folder, email),
            password=PASSWORD,
            display_name=name,
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()


def wait_for(page, probe, description):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = probe()
        if result:
            return result
        page.wait_for_timeout(50)  # Let Playwright dispatch network events.
    raise AssertionError(description)


@dataclass
class Connection:
    save_id: str
    frames: list[str] = field(default_factory=list)
    snapshots: dict[int, dict] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=lambda: ["created"])
    closed: bool = False

    def receive(self, payload):
        frame = (
            payload if isinstance(payload, str) else payload.decode("utf-8", "replace")
        )
        self.frames.append(frame)
        message = json.loads(frame)
        if message["type"] == "snapshot":
            if not self.snapshots:
                self.events.append("established")
            save = message["save"]
            self.snapshots[save["version"]] = save

    def error(self, message):
        self.errors.append(message)
        self.events.append("error")

    def close(self, *_):
        self.closed = True
        self.events.append("closed")


class Capture:
    """Per-context record of every API body and WS frame, for leakage checks."""

    def __init__(self, role):
        self.role = role
        self.http = []
        self.connections = []

    def attach(self, page):
        def on_response(response):
            path = urlsplit(response.url).path
            if not path.startswith("/api/"):
                return
            try:
                body = response.text()
            except Exception:
                body = ""
            self.http.append((path, response.status, body))

        def on_socket(socket):
            path = urlsplit(socket.url).path
            if not path.startswith("/api/ws/saves/"):
                return
            connection = Connection(path.rsplit("/", 1)[-1])
            self.connections.append(connection)
            socket.on("framereceived", connection.receive)
            socket.on("socketerror", connection.error)
            socket.on("close", connection.close)

        page.on("response", on_response)
        page.on("websocket", on_socket)

    @property
    def ws(self):
        return [frame for connection in self.connections for frame in connection.frames]

    def cursor(self):
        return len(self.http), len(self.connections)

    def lifecycle(self):
        return dict(
            created=len(self.connections),
            established=sum(bool(c.snapshots) for c in self.connections),
            closed=sum(c.closed for c in self.connections),
            errors=sum(len(c.errors) for c in self.connections),
        )

    def socket_at(self, page, save_id, version, *, since=0):
        return wait_for(
            page,
            lambda: next(
                (
                    c
                    for c in self.connections[since:]
                    if c.save_id == save_id and version in c.snapshots and not c.closed
                ),
                None,
            ),
            f"{self.role}: no live WebSocket with snapshot v{version} after connection {since}",
        )

    def assert_no_foreign_private(self, page):
        foreign_role = "b" if self.role == "a" else "a"
        surfaces = {
            "HTTP": [body for _, _, body in self.http],
            "WS": self.ws,
            "DOM": [page.content()],
        }
        for script, roles in PRIVATE.items():
            for clue_id, text in roles[foreign_role].items():
                for surface, blobs in surfaces.items():
                    assert all(
                        text not in blob and clue_id not in blob for blob in blobs
                    ), f"{script}: {self.role} received {clue_id} via {surface}"

    def assert_projection(self, page, script, save_id, version, since):
        """Require fresh GET and WS payloads plus the corresponding rendered view."""
        http_since, socket_since = since

        def saved_http():
            for path, status, body in self.http[http_since:]:
                if path == f"/api/saves/{save_id}" and status == 200 and body:
                    snapshot = json.loads(body)
                    if snapshot["version"] == version:
                        return snapshot
            return None

        http = wait_for(
            page,
            saved_http,
            f"{self.role}: no fresh GET snapshot for {script} v{version}",
        )
        socket = self.socket_at(page, save_id, version, since=socket_since)
        expected_private = PRIVATE[script][self.role]
        for surface, snapshot in (("HTTP", http), ("WS", socket.snapshots[version])):
            assert snapshot["id"] == save_id
            assert snapshot["script_id"] == script and snapshot["role"] == self.role
            for projection, expected in (
                ("personal", expected_private),
                ("public", SHARED[script]),
            ):
                clues = {c["id"]: c["text"] for c in snapshot[projection]["clues"]}
                assert expected.items() <= clues.items(), (
                    self.role,
                    script,
                    surface,
                    projection,
                )
            for other_script, roles in PRIVATE.items():
                if other_script != script:
                    payload = json.dumps(snapshot, ensure_ascii=False)
                    assert all(
                        clue_id not in payload and text not in payload
                        for clues in (*roles.values(), SHARED[other_script])
                        for clue_id, text in clues.items()
                    )
        information = page.locator("#game-information")
        for heading, clues in (
            ("我的私人线索", expected_private),
            ("已公开线索", SHARED[script]),
        ):
            paragraphs = information.locator(
                f'xpath=.//p[preceding-sibling::h2[1][normalize-space()="{heading}"]]'
            )
            for text in clues.values():
                expect(paragraphs.filter(has_text=text)).to_be_visible()
        for other_script, roles in PRIVATE.items():
            if other_script != script:
                for clues in (*roles.values(), SHARED[other_script]):
                    for text in clues.values():
                        expect(page.get_by_text(text, exact=True)).to_have_count(0)
        self.assert_no_foreign_private(page)


def login(page, base, email):
    page.goto(base)
    page.locator("#email").fill(email)
    page.locator("#password").fill(PASSWORD)
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page).to_have_url(base + "/pairs")


def enter_script(page, base, pair_id, script):
    if urlsplit(page.url).path.startswith("/saves/"):
        page.get_by_role("link", name="返回书架 →", exact=True).click()
    else:
        page.goto(base + f"/pairs/{pair_id}/library")
    card = page.locator(
        '[data-test="script-card"]', has_text=SCRIPTS[script]["metadata"]["title"]
    )
    card.locator('[data-test="start-save"], [data-test="continue-save"]').click()
    expect(page.locator('[data-test="save-entry"]')).to_contain_text(script)
    return urlsplit(page.url).path.rsplit("/", 1)[-1]


def expect_version(page, version):
    expect(page.locator('[data-test="save-entry"]')).to_contain_text(
        re.compile(rf"进度\s+{version}(?!\d)")
    )


def ui_action(page, client, save_id, kind, args, version, partner=None):
    for target in (page, partner):
        if target is not None and urlsplit(target.url).path != f"/saves/{save_id}":
            target.goto(
                urlsplit(target.url).scheme
                + "://"
                + urlsplit(target.url).netloc
                + "/saves/"
                + save_id
            )
    snapshot = client.get(f"/api/saves/{save_id}").json()
    action = next((a for a in snapshot["available_actions"] if a["kind"] == kind), None)
    if action is None:
        raise AssertionError(
            f"role={snapshot['role']} save={save_id} v={snapshot['version']} "
            f"scene={snapshot['scene_id']} kind={kind} "
            f"available={[a['kind'] for a in snapshot['available_actions']]}"
        )
    form = page.locator(f'.game-action[data-kind="{kind}"]')
    for parameter in action["parameters"]:
        value = args[parameter["id"]]
        control = form.locator(f'[name="{parameter["id"]}"]')
        if parameter["choices"]:
            control.select_option(value=str(parameter["choices"].index(value)))
        elif parameter["value_type"] == "boolean":
            control.check() if value else control.uncheck()
        else:
            control.fill(str(value))
    form.locator('button[type="submit"]').click()
    expect_version(page, version)
    if partner is not None:
        expect_version(partner, version)


def run(storage):
    results = dict(
        storage=storage,
        channel=CHANNEL,
        viewport=f"{WIDTH}x{HEIGHT}",
        touch=TOUCH,
        ending=ENDING,
        checks=[],
    )

    def check(name, detail=""):
        results["checks"].append(dict(name=name, detail=detail))
        print(f"PASS {name} {detail}", flush=True)

    with real_stack(storage) as stack:
        folder, base, api = stack["folder"], stack["base"], stack["api"]
        headers = {"Origin": base}
        owner = httpx.Client(base_url=api, headers=headers, trust_env=False)
        partner = httpx.Client(base_url=api, headers=headers, trust_env=False)
        outsider = httpx.Client(base_url=api, headers=headers, trust_env=False)
        email_a = "t16a-" + uuid4().hex[:10] + "@example.com"
        email_b = "t16b-" + uuid4().hex[:10] + "@example.com"
        register(owner, folder, email_a, "验收A")
        register(partner, folder, email_b, "验收B")
        register(outsider, folder, "t16x-" + uuid4().hex[:10] + "@example.com", "外人")
        check("register-three-accounts")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel=CHANNEL,
                executable_path=os.environ.get("T16_BROWSER_EXECUTABLE"),
                headless=True,
            )
            results["browser_version"] = browser.version
            context_a = browser.new_context(
                viewport=dict(width=WIDTH, height=HEIGHT),
                has_touch=TOUCH,
                is_mobile=TOUCH,
            )
            context_b = browser.new_context(
                viewport=dict(width=WIDTH, height=HEIGHT),
                has_touch=TOUCH,
                is_mobile=TOUCH,
            )
            page_a, page_b = context_a.new_page(), context_b.new_page()
            for page in (page_a, page_b):
                page.set_default_timeout(15000)
            capture_a, capture_b = Capture("a"), Capture("b")
            capture_a.attach(page_a)
            capture_b.attach(page_b)
            login(page_a, base, email_a)
            login(page_b, base, email_b)
            check("ui-login-two-independent-contexts")

            page_a.locator('[data-test="create-pair"]').click()
            expect(page_a).to_have_url(re.compile(re.escape(base) + r"/pairs/pair_"))
            pair_id = owner.get("/api/pairs").json()[0]["id"]
            invite = owner.post(f"/api/pairs/{pair_id}/invite").json()["invite_token"]
            page_b.goto(base + "/pairs#invite=" + invite)
            page_b.locator('[data-test="join-pair"]').click()
            expect(page_b).to_have_url(re.compile(re.escape(base) + r"/pairs/pair_"))
            check("ui-create-and-join-pair")

            browsers = ((page_a, capture_a), (page_b, capture_b))
            saves = {}
            for script in SCRIPTS:
                saves[script] = enter_script(page_a, base, pair_id, script)
                assert enter_script(page_b, base, pair_id, script) == saves[script]
            check("two-scripts-entered", ", ".join(saves))

            def verify_views(script, version, *, reenter=None):
                save_id = saves[script]
                for page, capture in browsers:
                    http_since, socket_since = capture.cursor()
                    if reenter is None:
                        # Read a current browser GET in addition to the live snapshot.
                        page.evaluate(
                            "async path => (await fetch(path)).text()",
                            f"/api/saves/{save_id}",
                        )
                        socket_since = 0
                    else:
                        reenter(page, script)
                    expect_version(page, version)
                    capture.assert_projection(
                        page, script, save_id, version, (http_since, socket_since)
                    )

            def switch_script(page, script):
                capture = capture_a if page == page_a else capture_b
                previous_id = urlsplit(page.url).path.rsplit("/", 1)[-1]
                previous = next(
                    (
                        c
                        for c in reversed(capture.connections)
                        if c.save_id == previous_id and c.snapshots and not c.closed
                    ),
                    None,
                )
                document = page.evaluate("performance.timeOrigin")
                assert enter_script(page, base, pair_id, script) == saves[script]
                if previous is not None:
                    wait_for(
                        page,
                        lambda: previous.closed,
                        "old save socket survived the script switch",
                    )
                    assert page.evaluate("performance.timeOrigin") == document

            for page, _ in browsers:
                switch_script(page, "lighthouse")
            trace = [
                ("a", "inspect", dict(target="maintenance_log")),
                ("b", "inspect", dict(target="sea_chart")),
                ("a", "share_clue", dict(clue_id="a_maintenance_log")),
                ("b", "set_filter", dict(filter="amber")),
                ("a", "set_emitter", dict(angle=180, pattern="pulse")),
                ("a", "set_emitter", dict(angle=90, pattern="pulse")),
                ("b", "lock_signal", {}),
                ("b", "route_power", dict(target="tower")),
                ("a", "inspect", dict(target="clock_gears")),
                ("a", "repair_clock", dict(mode="steady")),
                ("b", "confirm_route", {}),
                ("a", "vote_ending", dict(choice=ENDING)),
                ("b", "vote_ending", dict(choice=OTHER_ENDING)),
                ("b", "vote_ending", dict(choice=ENDING)),
            ]
            for index, (role, kind, args) in enumerate(trace, start=1):
                page, client = (page_a, owner) if role == "a" else (page_b, partner)
                other = page_b if role == "a" else page_a
                ui_action(page, client, saves["lighthouse"], kind, args, index, other)
                if index == 2:
                    for clue_id, text in SHARED["lighthouse"].items():
                        assert all(
                            text not in body and clue_id not in body
                            for _, _, body in capture_b.http
                        )
                        assert all(
                            text not in frame and clue_id not in frame
                            for frame in capture_b.ws
                        )
                        expect(page_b.get_by_text(text, exact=True)).to_have_count(0)
            expect(page_a.locator('[data-test="save-entry"]')).to_contain_text("已完成")
            expect(page_b.locator('[data-test="save-entry"]')).to_contain_text("已完成")
            check(
                "lighthouse-full-cooperation-divergent-then-agreed-votes",
                f"v14 completed ending={ENDING}",
            )
            verify_views("lighthouse", 14)
            check(
                "private-isolation-http-ws-page-after-lighthouse",
                "own private clues and shared maintenance log",
            )

            # API-level tampering must not cross roles.
            assert (
                owner.get(
                    f"/api/saves/{saves['lighthouse']}/media/receiver_tone"
                ).status_code
                == 404
            )
            b_request = None
            for path, status, body in capture_b.http:
                if path.endswith("/commands") and status == 200:
                    b_request = json.loads(body)["receipt"]["request_id"]
            assert b_request
            assert owner.get(
                f"/api/saves/{saves['lighthouse']}/receipts/{b_request}"
            ).json() == {"accepted": False}
            assert (
                owner.post(
                    f"/api/saves/{saves['lighthouse']}/commands",
                    json=dict(
                        request_id=str(uuid4()),
                        expected_version=14,
                        kind="inspect",
                        args=dict(target="sea_chart"),
                        role="b",
                    ),
                ).status_code
                == 422
            )
            assert outsider.get(f"/api/saves/{saves['lighthouse']}").status_code == 404
            check("api-tamper-media-receipt-role-outsider")

            starline = saves["starline"]
            for page, _ in browsers:
                switch_script(page, "starline")
            starline_trace = [
                ("a", "inspect", dict(target="station_log")),
                ("b", "inspect", dict(target="power_board")),
                ("a", "set_echo_gate", dict(position="east")),
                ("b", "allocate_power", dict(engine=False, sonar=True, lamp=True)),
                ("b", "scan_track", {}),
                ("a", "install_rail", dict(segment="bridge_2")),
                ("b", "allocate_power", dict(engine=True, sonar=False, lamp=True)),
                ("b", "confirm_signal", {}),
                ("a", "set_platform", dict(track="track_2")),
                ("b", "dispatch_train", {}),
            ]
            for index, (role, kind, args) in enumerate(starline_trace, start=1):
                page, client = (page_a, owner) if role == "a" else (page_b, partner)
                other = page_b if role == "a" else page_a
                ui_action(page, client, starline, kind, args, index, other)
            verify_views("starline", 10)
            check(
                "private-isolation-http-ws-page-after-starline",
                "a_station_log and b_power_board",
            )
            check("starline-independent-progress", "v10")
            assert (
                owner.get(f"/api/saves/{saves['lighthouse']}").json()["version"] == 14
            )
            check("script-isolation-lighthouse-unchanged")
            verify_views("lighthouse", 14, reenter=switch_script)
            verify_views("starline", 10, reenter=switch_script)
            check("private-isolation-after-switching-both-saves")

            # Concurrent submissions at the same expected version: one winner.
            snapshot = owner.get(f"/api/saves/{starline}").json()
            choices = next(
                a for a in snapshot["available_actions"] if a["kind"] == "vote_ending"
            )["parameters"][0]["choices"]
            envelopes = [
                dict(
                    request_id=str(uuid4()),
                    expected_version=10,
                    kind="vote_ending",
                    args=dict(choice=choices[0]),
                ),
                dict(
                    request_id=str(uuid4()),
                    expected_version=10,
                    kind="vote_ending",
                    args=dict(choice=choices[-1]),
                ),
            ]
            with ThreadPoolExecutor(2) as pool:
                responses = list(
                    pool.map(
                        lambda item: item[0].post(
                            f"/api/saves/{starline}/commands", json=item[1]
                        ),
                        ((owner, envelopes[0]), (partner, envelopes[1])),
                    )
                )
            assert sorted(r.status_code for r in responses) == [200, 409]
            winner_index = 0 if responses[0].status_code == 200 else 1
            winner = envelopes[winner_index]
            winner_choice = winner["args"]["choice"]
            opposite = choices[-1] if winner_choice == choices[0] else choices[0]
            replay = (owner if responses[0].status_code == 200 else partner).post(
                f"/api/saves/{starline}/commands", json=winner
            )
            assert replay.status_code == 200
            assert replay.json()["receipt"]["duplicate"] is True
            check("concurrent-submit-and-idempotent-replay")

            # A loses network while B advances through the UI.
            for page, _ in browsers:
                expect_version(page, 11)
            a_socket = capture_a.socket_at(page_a, starline, 11)
            b_socket = capture_b.socket_at(page_b, starline, 11)
            a_before = capture_a.lifecycle()
            a_document = page_a.evaluate("performance.timeOrigin")
            context_a.set_offline(True)
            assert not page_a.evaluate("navigator.onLine")
            wait_for(
                page_a,
                lambda: a_socket.closed,
                "A's original socket did not close offline",
            )
            assert not b_socket.closed
            ui_action(
                page_b, partner, starline, "vote_ending", dict(choice=opposite), 12
            )
            stored = partner.get(f"/api/saves/{starline}").json()
            assert stored["version"] == 12 and not stored["completed"]
            assert 12 not in a_socket.snapshots
            offline_connections = capture_a.lifecycle()["created"]
            assert offline_connections == a_before["created"]
            context_a.set_offline(False)
            a_reconnected = capture_a.socket_at(
                page_a, starline, 12, since=offline_connections
            )
            assert next(iter(a_reconnected.snapshots)) == 12
            b_current = capture_b.socket_at(page_b, starline, 12)
            assert b_current is b_socket
            assert (
                a_reconnected.snapshots[12]["public"]
                == b_current.snapshots[12]["public"]
            )
            expect_version(page_a, 12)
            expect_version(page_b, 12)
            assert page_a.evaluate("performance.timeOrigin") == a_document
            a_after = capture_a.lifecycle()
            assert a_after["closed"] > a_before["closed"]
            assert a_after["established"] == a_before["established"] + 1
            results["offline_recovery"] = dict(
                a_before=a_before, a_after=a_after, version=12, reloaded=False
            )
            check(
                "offline-reconnect-convergence",
                "A closed and reconnected at v12 without reload; B stayed online",
            )

            restart_before = {
                capture.role: capture.lifecycle() for _, capture in browsers
            }
            documents = {
                capture.role: page.evaluate("performance.timeOrigin")
                for page, capture in browsers
            }
            old_sockets = {"a": a_reconnected, "b": b_current}
            stack["restart"]()
            resumed = {}
            for page, capture in browsers:
                role = capture.role
                wait_for(
                    page,
                    lambda: old_sockets[role].closed,
                    f"{role}: old socket survived service restart",
                )
                resumed[role] = capture.socket_at(
                    page, starline, 12, since=restart_before[role]["created"]
                )
                assert next(iter(resumed[role].snapshots)) == 12
                expect_version(page, 12)
            assert (
                resumed["a"].snapshots[12]["public"]
                == resumed["b"].snapshots[12]["public"]
            )
            restart_after = {
                capture.role: capture.lifecycle() for _, capture in browsers
            }
            for role in resumed:
                assert restart_after[role]["closed"] > restart_before[role]["closed"]
                assert (
                    restart_after[role]["established"]
                    == restart_before[role]["established"] + 1
                )
            ui_action(
                page_a,
                owner,
                starline,
                "vote_ending",
                dict(choice=opposite),
                13,
                page_b,
            )
            completed = owner.get(f"/api/saves/{starline}").json()
            assert completed["completed"] and completed["public"]["ending"] == opposite
            for page, capture in browsers:
                expect(page.locator('[data-test="save-entry"]')).to_contain_text(
                    "已完成"
                )
                assert capture.socket_at(page, starline, 13) is resumed[capture.role]
                assert (
                    page.evaluate("performance.timeOrigin") == documents[capture.role]
                )
            results["restart_recovery"] = dict(
                before=restart_before,
                after=restart_after,
                restored_version=12,
                completed_version=13,
                reloaded=False,
            )
            check(
                "service-restart-then-finish-starline",
                "A/B reconnected at v12; A voted in UI and both completed at v13",
            )

            # Refresh is an explicit, separate isolation check after both recovery scenarios.
            verify_views("starline", 13, reenter=lambda page, _: page.reload())
            verify_views("lighthouse", 14, reenter=switch_script)
            verify_views("lighthouse", 14, reenter=lambda page, _: page.reload())
            check(
                "refresh-keeps-progress",
                "fresh HTTP/WS/DOM projections for both scripts",
            )

            # Re-login in fresh cookies restores both saves independently.
            for context, page, email in (
                (context_a, page_a, email_a),
                (context_b, page_b, email_b),
            ):
                context.clear_cookies()
                login(page, base, email)
            verify_views("lighthouse", 14, reenter=switch_script)
            verify_views("starline", 13, reenter=switch_script)
            assert owner.get(f"/api/saves/{saves['lighthouse']}").json()["completed"]
            assert owner.get(f"/api/saves/{starline}").json()["completed"]
            check("relogin-restores-both-saves")

            capture_a.assert_no_foreign_private(page_a)
            capture_b.assert_no_foreign_private(page_b)
            check("private-isolation-final")
            results["http_captured"] = dict(
                a=len(capture_a.http), b=len(capture_b.http)
            )
            results["ws_frames"] = dict(a=len(capture_a.ws), b=len(capture_b.ws))
            assert capture_a.ws and capture_b.ws, "expected real WebSocket frames"
            results["websocket_lifecycles"] = {
                capture.role: dict(
                    totals=capture.lifecycle(),
                    connections=[
                        dict(events=c.events, snapshot_versions=list(c.snapshots))
                        for c in capture.connections
                    ],
                )
                for _, capture in browsers
            }
            browser.close()
        owner.close()
        partner.close()
        outsider.close()
    (OUT / f"t16-{storage}-{CHANNEL}-{WIDTH}x{HEIGHT}-{ENDING}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"T16 {storage}: {len(results['checks'])} checks passed", flush=True)


if __name__ == "__main__":
    run(os.environ.get("T16_STORAGE", "sqlite"))
