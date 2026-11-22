"""Production Vite preview + real SW/Cache Storage; explicit private HTTP fixtures.

Requires existing Python Playwright and Edge. No mock service worker, no DB claim.
Run from frontend: python e2e/pwa_cache.py
"""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-results/pwa"
MARKER = "PRIVATE_T13_2_DO_NOT_CACHE"


def snapshot():
    return dict(
        id="save_one",
        pair_id="pair_one",
        script_id="lighthouse",
        script_version="1.0.0",
        version=7,
        scene_id="calibration",
        completed=False,
        role="a",
        personal=dict(
            clues=[dict(id="own", text=MARKER)],
            observations=[dict(topic="own", text=MARKER)],
            devices=dict(emitter=dict(angle=0, pattern="steady")),
            dialogue=[],
        ),
        public=dict(
            clues=[],
            ending=None,
            events=[],
            recap=dict(milestones=[], ending_id=None, summary=None),
        ),
        available_actions=[
            dict(
                id="adjust",
                kind="set_emitter",
                parameters=[
                    dict(
                        id="angle",
                        value_type="integer",
                        choices=[0, 90],
                        max_length=None,
                    ),
                    dict(
                        id="pattern",
                        value_type="string",
                        choices=["steady", "pulse"],
                        max_length=12,
                    ),
                ],
            )
        ],
        presentation=dict(background=None, cues=[]),
    )


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_url(url):
    import urllib.request

    for _ in range(150):
        try:
            urllib.request.urlopen(url, timeout=1).close()
            return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("Owned preview did not start")


@contextmanager
def preview():
    state = dict(
        version=1,
        redirect_static=False,
        logged_in=True,
        account="account_test",
        commands=[],
        receipts=[],
        save=snapshot(),
        seen=[],
    )
    me = dict(
        account=dict(
            id="account_test", email="test@example.test", display_name="TEST-ONLY"
        ),
        session=dict(expires_at="2027-01-01T00:00:00Z"),
    )
    sw = (ROOT / "dist/sw.js").read_text("utf-8")
    config = json.loads(re.search(r"const config = (.*);", sw)[1])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.reply()

        def do_POST(self):
            self.reply()

        def do_DELETE(self):
            self.reply()

        def reply(self):
            state["seen"].append((self.command, self.path))
            path = urlsplit(self.path).path
            if path == "/sw.js":
                text = (
                    sw
                    if state["version"] == 1
                    else sw.replace(
                        config["version"],
                        config["version"] + "v" + str(state["version"]),
                    )
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(text.encode())
                return
            if path == "/pwa/offline.css":
                self.send_response(302 if state["redirect_static"] else 200)
                if state["redirect_static"]:
                    self.send_header("Location", "/api/me")
                else:
                    self.send_header("Content-Type", "text/css")
                self.end_headers()
                if not state["redirect_static"]:
                    self.wfile.write((ROOT / "public/pwa/offline.css").read_bytes())
                return
            size = int(self.headers.get("Content-Length", "0"))
            body = (
                json.loads(self.rfile.read(size))
                if size
                and self.headers.get("Content-Type", "").startswith("application/json")
                else {}
            )
            status = 200
            if path == "/api/me":
                response = (
                    dict(
                        account={**me["account"], "id": state["account"]},
                        session=me["session"],
                    )
                    if state["logged_in"]
                    else dict(
                        error=dict(code="UNAUTHORIZED", message=MARKER, retryable=False)
                    )
                )
                status = 200 if state["logged_in"] else 401
            elif path == "/api/sessions":
                state["logged_in"] = self.command != "DELETE"
                response = me
                status = 204 if self.command == "DELETE" else 200
            elif path == "/api/saves/save_one":
                response = state["save"]
            elif path.endswith("/commands"):
                state["commands"].append(body)
                response = dict(
                    error=dict(
                        code="DEPENDENCY_UNAVAILABLE", message=MARKER, retryable=True
                    )
                )
                status = 503
            elif "/receipts/" in path:
                state["receipts"].append(path)
                response = dict(accepted=False)
            else:
                response = dict(marker=MARKER, path=self.path)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Set-Cookie", "test_fixture=PRIVATE_T13_2_DO_NOT_CACHE; SameSite=Lax"
            )
            self.end_headers()
            if status != 204:
                self.wfile.write(json.dumps(response).encode())

    api = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=api.serve_forever, daemon=True).start()
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    target = f"http://127.0.0.1:{api.server_port}"
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    settings = work / "pwa-preview.config.mjs"
    settings.write_text(
        "export default "
        + json.dumps(
            dict(
                root=str(ROOT),
                preview=dict(
                    proxy={
                        r"^/(api|%|private|redirect)": target,
                        "/sw.js": target,
                        "/pwa/offline.css": target,
                        r"^/assets/.*\?": target,
                    }
                ),
            )
        )
        + ";",
        encoding="utf-8",
    )
    with (OUT / "preview.log").open("w") as log:
        child = subprocess.Popen(
            [
                "node",
                str(ROOT / "node_modules/vite/bin/vite.js"),
                "preview",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
                "--config",
                str(settings),
            ],
            cwd=ROOT,
            stdout=log,
            stderr=log,
        )
        try:
            wait_url(base)
            yield base, target, state, config
        finally:
            child.terminate()
            child.wait(timeout=10)
            api.shutdown()
            api.server_close()


def audit(page, config, base):
    entries = page.evaluate("""async()=>{
      const out=[];
      for(const name of await caches.keys()) for(const request of await (await caches.open(name)).keys()) {
        const response=await (await caches.open(name)).match(request);
        const bytes=await response.arrayBuffer();
        const hash=await crypto.subtle.digest('SHA-256',bytes);
        const b64=btoa(String.fromCharCode(...new Uint8Array(hash)));
        out.push({name,url:request.url,integrity:'sha256-'+b64,text:new TextDecoder().decode(bytes),headers:Object.fromEntries(response.headers)});
      }
      return out;
    }""")
    assert entries
    approved = {base + "/" + x["path"]: x["integrity"] for x in config["resources"]}
    for item in entries:
        assert item["url"] in approved, item["url"]
        assert item["integrity"] == approved[item["url"]], item["url"]
        assert MARKER not in item["text"]
        assert MARKER not in json.dumps(item["headers"])
        assert "set-cookie" not in item["headers"]
        assert "/api/" not in item["url"]
    return [
        dict(name=x["name"], url=x["url"], integrity=x["integrity"]) for x in entries
    ]


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    with preview() as (base, external, state, config), sync_playwright() as p:
        profile = tempfile.TemporaryDirectory(prefix="profile-", dir=OUT)
        context = p.chromium.launch_persistent_context(
            profile.name,
            channel=os.environ.get("PWA_BROWSER", "msedge"),
            headless=True,
            viewport=dict(width=390, height=844),
        )
        browser = context.browser
        page = context.new_page()
        page.set_default_timeout(10000)
        page.goto(base)
        page.evaluate("async()=>{await navigator.serviceWorker.ready}")
        page.wait_for_function("navigator.serviceWorker.controller !== null")
        manifest = context.request.get(base + "/manifest.webmanifest").json()
        assert (
            manifest["start_url"] == manifest["scope"] == "/"
            and manifest["display"] == "standalone"
        )
        for icon in manifest["icons"]:
            raw = context.request.get(base + icon["src"]).body()
            assert raw[:8] == b"\x89PNG\r\n\x1a\n"
            import struct

            assert struct.unpack(">II", raw[16:24]) == tuple(
                map(int, icon["sizes"].split("x"))
            )
        cdp = context.new_cdp_session(page)
        installability = cdp.send("Page.getInstallabilityErrors")
        assert not installability["installabilityErrors"], installability
        page.screenshot(path=str(OUT / "installation.png"), full_page=True)
        first = audit(page, config, base)
        # Actual network requests under control of the real worker, not route mocks.
        paths = [
            "/api/me",
            "/api/saves/save_one",
            "/api/saves/save_one/receipts/00000000-0000-4000-8000-000000000000",
            "/api/saves/save_one/talk",
            "/api/saves/save_one/media/private_image",
            "/api/saves/save_one/media/private_audio",
            "/%61pi/me",
            "/api%2fme",
            "/api/me?asset=public",
            "/private.html",
            "/apiary",
            "/assets/%69ndex.js",
        ]
        for path in paths:
            page.evaluate(
                'async path=>{try{const r=await fetch(path,{credentials:"include",cache:"no-store"});await r.text()}catch{}}',
                path,
            )
        static_url = "/" + next(
            r["path"]
            for r in config["resources"]
            if r["path"].endswith(".js") and r["path"].startswith("assets/")
        )
        for method in ["POST", "DELETE"]:
            page.evaluate(
                'async method=>{await fetch("/api/verification-codes",{method,body:"TEST-ONLY",credentials:"include"})}',
                method,
            )
        for path in [
            "/api/sessions",
            "/api/verification-codes",
            "/api/accounts",
            "/api/password-resets",
        ]:
            page.evaluate(
                'async path=>{await fetch(path,{method:"POST",body:"TEST-ONLY",credentials:"include"})}',
                path,
            )
        page.evaluate(
            "async url=>{await fetch(url).then(r=>r.text())}", external + "/api/me"
        )
        page.evaluate(
            'async path=>{await fetch(path+"?private="+encodeURIComponent("PRIVATE_T13_2_DO_NOT_CACHE"),{credentials:"include"}).then(r=>r.text())}',
            static_url,
        )
        assert len(audit(page, config, base)) == len(first)
        # A private route never becomes a cached HTML response.
        page.goto(base + "/saves/save_one")
        expect(page.locator("#game-actions")).to_be_visible()
        page.locator("#game-actions select").first.select_option("1")
        page.locator("#game-actions button").click()
        expect(
            page.get_by_role("button", name="手动确认原请求", exact=False)
        ).to_be_enabled()
        request_id = state["commands"][0]["request_id"]
        assert len(state["commands"]) == 1
        # Worker v2 installs but cannot reload or activate over this unresolved command.
        state["version"] = 2
        page.evaluate(
            "async()=>{await (await navigator.serviceWorker.getRegistration()).update()}"
        )
        page.wait_for_function(
            "navigator.serviceWorker.getRegistration().then(r=>!!r.waiting)"
        )
        expect(page.get_by_text("新版本已准备好。", exact=False)).to_be_visible()
        assert page.url == base + "/saves/save_one" and len(state["commands"]) == 1
        assert len(page.evaluate("caches.keys()")) == 2
        context.set_offline(True)
        expect(page.get_by_role("button", name="全局静音", exact=True)).to_be_enabled()
        page.get_by_role("button", name="全局静音", exact=True).click()
        expect(page.get_by_role("button", name="恢复声音", exact=True)).to_be_visible()
        assert not page.locator("#game-actions button").is_enabled()
        page.close()
        page = context.new_page()
        page.goto(
            base + "/"
        )  # PWA start_url; new document has only the public fallback.
        expect(page.get_by_role("heading", name="暂时无法连接")).to_be_visible()
        assert MARKER not in page.content()
        assert page.locator("[data-test=save-entry]").count() == 0
        page.screenshot(path=str(OUT / "offline.png"), full_page=True)
        # Retry works, but revoked sessions do not regain private content.
        state["logged_in"] = False
        context.set_offline(False)
        page.get_by_role("button", name="重新连接").click()
        expect(page.locator("#email")).to_be_visible()
        assert page.locator("[data-test=save-entry]").count() == 0
        state["logged_in"] = True
        page.goto(base + "/saves/save_one")
        expect(page.get_by_role("button", name="查询原操作回执")).to_be_visible()
        assert any(path.endswith(request_id) for path in state["receipts"])
        assert len(state["commands"]) == 1
        # Close all clients: the waiting worker can activate and clean only old shell caches.
        page.close()
        page = context.new_page()
        page.goto(base)
        page.wait_for_function(
            'caches.keys().then(x=>x.length===1 && x[0].endsWith("v2"))'
        )
        final = audit(page, config, base)
        # A redirected precache response rejects the new install and preserves v2.
        state["version"] = 3
        state["redirect_static"] = True
        assert page.evaluate("""async()=>{
          const r=await navigator.serviceWorker.getRegistration();
          const failed=new Promise(resolve=>r.addEventListener('updatefound',()=>{
            const worker=r.installing;
            worker.addEventListener('statechange',()=>{if(worker.state==='redundant')resolve(true)});
          },{once:true}));
          await r.update();return await failed;
        }""")
        assert len(page.evaluate("caches.keys()")) == 1
        assert page.evaluate("caches.keys()")[0].endswith("v2")
        state["redirect_static"] = False
        # A new account sees no previous account's cached game document.
        page.evaluate(
            'async()=>{await fetch("/api/sessions",{method:"DELETE",credentials:"include"})}'
        )
        context.set_offline(True)
        page.goto(base + "/saves/save_one")
        expect(page.get_by_role("heading", name="暂时无法连接")).to_be_visible()
        assert MARKER not in page.content()
        final = audit(page, config, base)
        context.set_offline(False)
        page.get_by_role("button", name="重新连接").click()
        expect(page.locator("#email")).to_be_visible()
        state["account"] = "account_other"
        state["logged_in"] = True
        page.reload()
        expect(
            page.get_by_role("link", name="进入我的房间", exact=False)
        ).to_be_visible()
        assert page.locator("[data-test=save-entry]").count() == 0
        final = audit(page, config, base)
        # No service worker support: online frontend still renders.
        state["logged_in"] = False
        plain = browser.new_context(service_workers="block")
        plain_page = plain.new_page()
        plain_page.goto(base)
        expect(plain_page.locator("#email")).to_be_visible()
        plain.close()
        (OUT / "cache-results.json").write_text(
            json.dumps(
                dict(
                    browser=browser.version,
                    installability=installability,
                    cache=final,
                    pending_uuid_preserved=True,
                    commands_sent=1,
                    update_waited=True,
                    redirected_install_rejected=True,
                    switched_identity_has_no_cached_private_document=True,
                    physical_devices="not tested",
                    backend="explicit HTTP fixtures",
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        context.close()
        profile.cleanup()
    print(
        "PWA production preview, installability, cache isolation, offline/retry, UUID and update checks passed"
    )


if __name__ == "__main__":
    run()
