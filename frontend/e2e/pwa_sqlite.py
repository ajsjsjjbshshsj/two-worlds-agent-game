"""Real FastAPI + SQLite + production Vite preview offline/UUID recovery.

Run from frontend after build and backend uv sync: python e2e/pwa_sqlite.py
Uses existing Python Playwright/httpx, project Python 3.12 child API and temporary
TEST-ONLY sealed publications. No API/WS response mocks or offline rule execution.
"""

from contextlib import ExitStack, closing
from pathlib import Path
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

from pwa_cache import ROOT, OUT, free_port, wait_url

BACKEND = ROOT.parent / "backend"


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix="sqlite-", dir=OUT) as directory,
        ExitStack() as stack,
    ):
        folder = Path(directory)
        api_port, ui_port = free_port(), free_port()
        api, base = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{ui_port}"
        source = """from pathlib import Path
import sys
from tests.save_support import make_publications
from twoworlds.dev import create_dev_app
import uvicorn
root=Path(sys.argv[1])
store,publish=make_publications(root)
publish();publish(identifier="starline")
app=create_dev_app(publication_store=store)
uvicorn.run(app,host="127.0.0.1",port=int(sys.argv[2]),access_log=False,log_level="critical",ws="websockets-sansio")
"""
        worker = folder / "server.py"
        worker.write_text(source, encoding="utf-8")
        env = {
            **os.environ,
            "PYTHONPATH": str(BACKEND),
            "TWOWORLDS_STORAGE_BACKEND": "sqlite",
            "TWOWORLDS_SQLITE_PATH": str(folder / "game.sqlite"),
            "TWOWORLDS_ALLOWED_ORIGINS": base,
            "TWOWORLDS_EMAIL_MODE": "console",
            "TWOWORLDS_COOKIE_SECURE": "0",
        }
        console = stack.enter_context((folder / "console.log").open("w"))
        python = (
            BACKEND / ".venv/Scripts/python.exe"
            if os.name == "nt"
            else BACKEND / ".venv/bin/python"
        )
        child = subprocess.Popen(
            [str(python), str(worker), str(folder), str(api_port)],
            cwd=BACKEND,
            env=env,
            stdout=console,
            stderr=console,
        )

        def stop(process):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)

        stack.callback(stop, child)
        wait_url(api + "/api/scripts")
        headers = {"Origin": base}
        owner = stack.enter_context(
            httpx.Client(base_url=api, headers=headers, trust_env=False)
        )
        partner = stack.enter_context(
            httpx.Client(base_url=api, headers=headers, trust_env=False)
        )
        email = "pwa-" + uuid4().hex + "@example.com"
        password = "test-only-password-123"

        def register(client, address, name):
            assert (
                client.post(
                    "/api/verification-codes",
                    json=dict(email=address, purpose="register"),
                ).status_code
                == 202
            )
            code = None
            for _ in range(100):
                match = re.search(
                    r"to=" + re.escape(address) + r" purpose=register code=([0-9]{6})",
                    (folder / "console.log").read_text("utf-8"),
                )
                if match:
                    code = match[1]
                    break
                time.sleep(0.05)
            assert code
            response = client.post(
                "/api/accounts",
                json=dict(
                    email=address, code=code, password=password, display_name=name
                ),
            )
            assert response.status_code == 200, response.text

        register(owner, email, "TEST-ONLY A")
        register(partner, "partner-" + uuid4().hex + "@example.com", "TEST-ONLY B")
        pair = owner.post("/api/pairs").json()
        assert (
            partner.post(
                "/api/pairs/join", json=dict(invite_token=pair["invite_token"])
            ).status_code
            == 200
        )
        save = owner.post(
            "/api/saves",
            json=dict(
                pair_id=pair["id"], script_id="lighthouse", script_version="1.0.0"
            ),
        ).json()
        save_path = "/api/saves/" + save["id"]
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
        with sync_playwright() as p:
            profile = folder / "profile"
            browser = p.chromium.launch_persistent_context(
                str(profile),
                channel=os.environ.get("PWA_BROWSER", "msedge"),
                headless=True,
                viewport=dict(width=390, height=844),
            )
            page = browser.new_page()
            page.set_default_timeout(10000)
            page.goto(base)
            page.evaluate("async()=>await navigator.serviceWorker.ready")
            page.wait_for_function("navigator.serviceWorker.controller !== null")
            page.locator("#email").fill(email)
            page.locator("#password").fill(password)
            page.get_by_role("button", name="登录", exact=True).click()
            expect(page).to_have_url(base + "/pairs")
            page.goto(base + "/saves/" + save["id"])
            expect(
                page.locator(".game-action[data-kind=inspect] button").first
            ).to_be_enabled()
            captured = {}

            def lose_response(route):
                command = route.request.post_data_json
                response = route.fetch()
                assert response.status == 200
                captured.update(
                    uuid=command["request_id"],
                    version=response.json()["receipt"]["accepted_version"],
                )
                browser.set_offline(True)
                route.abort("failed")

            page.route("**" + save_path + "/commands", lose_response, times=1)
            page.locator(".game-action[data-kind=inspect] button").first.click()
            expect(page.locator(".network-notice")).to_be_visible()
            for _ in range(100):
                if captured:
                    break
                page.wait_for_timeout(50)
            assert captured["version"] == 1
            assert owner.get(save_path).json()["version"] == 1
            # While A is offline, B advances this same authoritative save to v2.
            change = partner.post(
                save_path + "/commands",
                json=dict(
                    request_id=str(uuid4()),
                    expected_version=1,
                    kind="inspect",
                    args=dict(target="sea_chart"),
                ),
            )
            assert change.status_code == 200, change.text
            assert change.json()["save"]["version"] == 2
            browser.close()  # Both the page and browser process exit; disk journal persists.
            browser = p.chromium.launch_persistent_context(
                str(profile),
                channel=os.environ.get("PWA_BROWSER", "msedge"),
                headless=True,
                viewport=dict(width=390, height=844),
            )
            browser.set_offline(True)
            page = browser.new_page()
            page.set_default_timeout(10000)
            page.goto(base)  # Manifest start_url: no private document is restored.
            expect(page.get_by_role("heading", name="暂时无法连接")).to_be_visible()
            assert email not in page.content() and save["id"] not in page.content()
            requests = []
            page.on(
                "request",
                lambda request: requests.append(
                    (request.method, urlsplit(request.url).path)
                ),
            )
            browser.set_offline(False)
            page.get_by_role("button", name="重新连接").click()
            expect(
                page.get_by_role("link", name="进入我的房间", exact=False)
            ).to_be_visible()
            page.get_by_role("link", name="进入我的房间", exact=False).click()
            page.get_by_role("link", name="进入房间", exact=False).click()
            page.get_by_role("link", name="进入剧本书架", exact=False).click()
            page.locator("[data-test=continue-save]").click()
            expect(page.locator("[data-test=save-entry]")).to_contain_text("进度 2")
            expect(page.locator("#game-status")).to_contain_text("服务器已确认原操作")
            receipt = save_path + "/receipts/" + captured["uuid"]
            assert (
                ("GET", "/api/me") in requests
                and ("GET", save_path) in requests
                and ("GET", receipt) in requests
            )
            assert (
                requests.index(("GET", "/api/me"))
                < requests.index(("GET", save_path))
                < requests.index(("GET", receipt))
            )
            assert not any(
                method == "POST" and path.endswith("/commands")
                for method, path in requests
            )
            action = page.locator(".game-action[data-kind=set_emitter]")
            expect(action.locator("button")).to_be_enabled()
            action.locator("select[name=angle]").select_option("1")
            action.locator("select[name=pattern]").select_option("1")
            action.locator("button").click()
            expect(page.locator("[data-test=save-entry]")).to_contain_text("进度 3")
            with closing(sqlite3.connect(folder / "game.sqlite")) as db:
                stored = json.loads(
                    db.execute(
                        "SELECT document FROM saves WHERE save_id=?", (save["id"],)
                    ).fetchone()[0]
                )
            assert stored["version"] == 3
            assert [r["accepted_version"] for r in stored["receipts"]] == [1, 2, 3]
            assert (
                sum(r["request_id"] == captured["uuid"] for r in stored["receipts"])
                == 1
            )
            assert (
                page.evaluate(
                    "async()=>{let ids=[];for(const k of await caches.keys()) ids.push(...(await (await caches.open(k)).keys()).map(r=>r.url));return ids}"
                ).count(base + save_path)
                == 0
            )
            view = owner.get(save_path).json()
            private_text = view["personal"]["clues"][0]["text"]
            voices = [
                a["asset_id"]
                for cue in view["presentation"]["cues"]
                for a in cue["assets"]
                if a["kind"] == "narration"
            ]
            assert voices
            media = page.evaluate(
                """async url=>{const r=await fetch(url,{credentials:'include',cache:'no-store'});return {status:r.status,bytes:(await r.arrayBuffer()).byteLength}}""",
                save_path + "/media/" + voices[0],
            )
            assert media["status"] == 200 and media["bytes"] > 0
            assert not page.evaluate(
                """async secrets=>{for(const name of await caches.keys())for(const request of await(await caches.open(name)).keys()){
              if(new URL(request.url).pathname.startsWith('/api/'))return true;
              const text=await(await(await caches.open(name)).match(request)).text();
              if(secrets.some(secret=>text.includes(secret)))return true;
            }return false}""",
                [email, private_text],
            )
            browser.close()
        (OUT / "sqlite-results.json").write_text(
            json.dumps(
                dict(
                    backend="real FastAPI + SQLite",
                    initial_committed_version=1,
                    partner_version=2,
                    continued_version=3,
                    original_receipts=1,
                    automatic_reposts=0,
                    identity_then_save_then_receipt=True,
                    private_offline_content=False,
                    physical_devices="not tested",
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
    print(
        "Real SQLite PWA close/reopen, authoritative v2 recovery, original UUID and continued v3 passed"
    )


if __name__ == "__main__":
    run()
