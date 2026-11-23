"""T16 dual-browser acceptance: real API, real storage, real WebSocket.

Two fully independent browser contexts (separate cookies/storage/network) play
one account each against a real FastAPI child process and a production Vite
preview. Every HTTP response body and WebSocket frame is captured per context
and checked for cross-role private leakage; UI actions drive both scripts.

Run from frontend with backend venv synced (dev group includes playwright):
  T16_STORAGE=sqlite python e2e/t16_dual_browser.py
  T16_STORAGE=mongo MONGO_URI=... python e2e/t16_dual_browser.py
T16_BROWSER selects the channel (msedge/chrome on Windows, chromium in CI).
No response mocks: only the console email transport is a dev adapter.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
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
CHANNEL = os.environ.get(
    "T16_BROWSER", "msedge" if os.name == "nt" else "chromium"
)
WIDTH, HEIGHT = (
    int(value) for value in os.environ.get("T16_VIEWPORT", "1280x900").split("x")
)
TOUCH = os.environ.get("T16_TOUCH", "0") == "1"
ENDING = os.environ.get("T16_ENDING", "guide_now")
OTHER_ENDING = "wait_tide" if ENDING == "guide_now" else "guide_now"
PASSWORD = "test-only-password-123"
LIGHTHOUSE = json.loads(
    (BACKEND / "src/twoworlds/content/scripts/lighthouse/1.0.0.json").read_text("utf-8")
)
TITLES = {
    "lighthouse": LIGHTHOUSE["metadata"]["title"],
    "starline": json.loads(
        (BACKEND / "src/twoworlds/content/scripts/starline/1.0.0.json").read_text("utf-8")
    )["metadata"]["title"],
}
SHARED_CLUE = "a_maintenance_log"
PRIVATE = {
    "a": [
        c["text"]
        for c in LIGHTHOUSE["clues"]
        if c["role"] == "a" and c["id"] != SHARED_CLUE
    ],
    "b": [c["text"] for c in LIGHTHOUSE["clues"] if c["role"] == "b"],
}
SHARED_TEXT = next(
    c["text"] for c in LIGHTHOUSE["clues"] if c["id"] == SHARED_CLUE
)


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
                dict(root=str(ROOT), preview=dict(proxy={"/api": dict(target=api, ws=True)}))
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
    pattern = re.compile(
        rf"to={re.escape(email)} purpose={purpose} code=([0-9]{{6}})"
    )
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


class Capture:
    """Per-context record of every API body and WS frame, for leakage checks."""

    def __init__(self, role):
        self.role = role
        self.http = []
        self.ws = []

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
            socket.on(
                "framereceived",
                lambda payload: self.ws.append(
                    payload if isinstance(payload, str) else payload.decode("utf-8", "replace")
                ),
            )

        page.on("response", on_response)
        page.on("websocket", on_socket)

    def blobs(self):
        return [body for _, _, body in self.http] + self.ws

    def assert_no_foreign_private(self, page):
        foreign = PRIVATE["b" if self.role == "a" else "a"]
        for marker in foreign:
            for blob in self.blobs():
                assert marker not in blob, (
                    f"{self.role} received foreign private text: {marker[:16]}"
                )
            assert marker not in page.content(), (
                f"{self.role} page shows foreign private: {marker[:16]}"
            )


def login(page, base, email):
    page.goto(base)
    page.locator("#email").fill(email)
    page.locator("#password").fill(PASSWORD)
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page).to_have_url(base + "/pairs")


def ui_action(page, client, save_id, kind, args, version, partner=None):
    for target in (page, partner):
        if target is not None and urlsplit(target.url).path != f"/saves/{save_id}":
            target.goto(urlsplit(target.url).scheme + "://" + urlsplit(target.url).netloc + "/saves/" + save_id)
    snapshot = client.get(f"/api/saves/{save_id}").json()
    action = next(
        (a for a in snapshot["available_actions"] if a["kind"] == kind), None
    )
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
    expect(page.locator('[data-test="save-entry"]')).to_contain_text(f"进度 {version}")
    if partner is not None:
        expect(partner.locator('[data-test="save-entry"]')).to_contain_text(
            f"进度 {version}"
        )


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
            browser = p.chromium.launch(channel=CHANNEL, headless=True)
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
            check("ui-create-and-join-pair", pair_id)

            saves = {}
            for script in ("lighthouse", "starline"):
                for page, client in ((page_a, owner), (page_b, partner)):
                    page.goto(base + f"/pairs/{pair_id}/library")
                    card = page.locator('[data-test="script-card"]', has_text=TITLES[script])
                    button = card.locator(
                        '[data-test="start-save"], [data-test="continue-save"]'
                    )
                    expect(button).to_be_visible()
                    if card.locator('[data-test="start-save"]').count():
                        card.locator('[data-test="start-save"]').click()
                    else:
                        card.locator('[data-test="continue-save"]').click()
                    expect(page.locator('[data-test="save-entry"]')).to_be_visible()
                saves[script] = urlsplit(page_a.url).path.rsplit("/", 1)[-1]
            check("two-scripts-entered", json.dumps(saves))

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
            expect(page_a.locator('[data-test="save-entry"]')).to_contain_text("已完成")
            expect(page_b.locator('[data-test="save-entry"]')).to_contain_text("已完成")
            check("lighthouse-full-cooperation-divergent-then-agreed-votes", f"v14 completed ending={ENDING}")
            capture_a.assert_no_foreign_private(page_a)
            capture_b.assert_no_foreign_private(page_b)
            for capture in (capture_a, capture_b):
                assert any(SHARED_TEXT in blob for blob in capture.blobs()), (
                    "shared clue must reach both players"
                )
            check("private-isolation-http-ws-page-after-lighthouse")

            # API-level tampering must not cross roles.
            b_save = partner.get(f"/api/saves/{saves['lighthouse']}").json()
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
            assert (
                outsider.get(f"/api/saves/{saves['lighthouse']}").status_code == 404
            )
            check("api-tamper-media-receipt-role-outsider")

            starline = saves["starline"]
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
            check("starline-independent-progress", "v10")
            assert owner.get(f"/api/saves/{saves['lighthouse']}").json()["version"] == 14
            check("script-isolation-lighthouse-unchanged")

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

            # A loses network while B advances; A recovers and converges.
            context_a.set_offline(True)
            advance = partner.post(
                f"/api/saves/{starline}/commands",
                json=dict(
                    request_id=str(uuid4()),
                    expected_version=11,
                    kind="vote_ending",
                    args=dict(choice=opposite),
                ),
            )
            assert advance.status_code == 200, advance.text
            context_a.set_offline(False)
            page_a.reload()
            expect(page_a.locator('[data-test="save-entry"]')).to_contain_text("进度 12")
            check("offline-reconnect-convergence")

            page_a.reload()
            page_b.reload()
            expect(page_a.locator('[data-test="save-entry"]')).to_contain_text("进度 12")
            expect(page_b.locator('[data-test="save-entry"]')).to_contain_text("进度 12")
            check("refresh-keeps-progress")

            stack["restart"]()
            page_a.reload()
            page_b.reload()
            expect(page_a.locator('[data-test="save-entry"]')).to_contain_text("进度 12")
            expect(page_b.locator('[data-test="save-entry"]')).to_contain_text("进度 12")
            final_version = None
            for client in (owner, partner):
                snapshot = client.get(f"/api/saves/{starline}").json()
                if snapshot["completed"]:
                    final_version = snapshot["version"]
                    break
                choice = next(
                    a
                    for a in snapshot["available_actions"]
                    if a["kind"] == "vote_ending"
                )["parameters"][0]["choices"][0]
                response = client.post(
                    f"/api/saves/{starline}/commands",
                    json=dict(
                        request_id=str(uuid4()),
                        expected_version=snapshot["version"],
                        kind="vote_ending",
                        args=dict(choice=choice),
                    ),
                )
                if response.status_code == 422:
                    assert response.json()["error"]["code"] == "NO_STATE_CHANGE"
                    continue  # this player already holds the target choice
                assert response.status_code == 200, response.text
                final_version = response.json()["save"]["version"]
            assert owner.get(f"/api/saves/{starline}").json()["completed"]
            page_a.reload()
            page_b.reload()
            expect(page_a.locator('[data-test="save-entry"]')).to_contain_text("已完成")
            expect(page_b.locator('[data-test="save-entry"]')).to_contain_text("已完成")
            check("service-restart-then-finish-starline", f"v{final_version} completed")

            # Re-login in fresh cookies restores both saves independently.
            for context, page, client, email in (
                (context_a, page_a, owner, email_a),
                (context_b, page_b, partner, email_b),
            ):
                context.clear_cookies()
                login(page, base, email)
                page.goto(base + f"/pairs/{pair_id}/library")
                page.locator('[data-test="continue-save"]').first.click()
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