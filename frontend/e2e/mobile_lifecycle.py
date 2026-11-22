"""Production browser lifecycle checks with real SQLite, Cookie, HTTP and WS.

Run after npm run build and backend uv sync: python e2e/mobile_lifecycle.py.
Visibility changes are injected in Chromium to make mobile lifecycle ordering
deterministic. Audio and Cache Storage use native browser implementations.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

from pwa_cache import OUT
from pwa_sqlite import sqlite_preview


SIZES = [(375, 667), (390, 844), (430, 932), (768, 1024), (1440, 900)]


def launch_options(channel):
    # Windows can have a stale per-user Chrome alongside the active system install.
    system_chrome = (
        Path(os.environ.get("ProgramFiles", ""))
        / "Google/Chrome/Application/chrome.exe"
    )
    if os.name == "nt" and channel == "chrome" and system_chrome.is_file():
        return {"executable_path": str(system_chrome)}
    return {"channel": channel}


PROBE = """() => {
  const nativePlay = HTMLMediaElement.prototype.play;
  const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
  const probe = window.probe = {plays: [], blobs: [], revoked: [], reject: ''};
  URL.createObjectURL = blob => {
    const url = create(blob);
    probe.blobs.push({url, type: blob.type});
    return url;
  };
  URL.revokeObjectURL = url => { probe.revoked.push(url); return revoke(url); };
  HTMLMediaElement.prototype.play = function () {
    probe.plays.push({element: this, url: this.src, loop: this.loop});
    return probe.reject ? Promise.reject(new DOMException('TEST-ONLY', probe.reject)) : nativePlay.call(this);
  };
  window.testVisibility = hidden => {
    Object.defineProperty(document, 'hidden', {configurable:true, get: () => hidden});
    document.dispatchEvent(new Event('visibilitychange'));
  };
}"""


def command(client, path, version, kind, args=None):
    res = client.post(
        path + "/commands",
        json={
            "request_id": str(uuid4()),
            "expected_version": version,
            "kind": kind,
            "args": args or {},
        },
    )
    assert res.status_code == 200, (kind, res.status_code)
    return res.json()["save"]


def login(page, email, password):
    page.locator("#email").fill(email)
    page.locator("#password").fill(password)
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page.get_by_role("heading", name="我的双人房间")).to_be_visible()


def run():
    browsers = os.environ.get("TWOWORLDS_LIFECYCLE_BROWSERS", "msedge,chrome").split(
        ","
    )
    results = {}
    for channel in browsers:
        with (
            sqlite_preview() as (_, base, owner, partner, email, password, save),
            sync_playwright() as p,
        ):
            path = "/api/saves/" + save["id"]
            browser = p.chromium.launch(
                **launch_options(channel),
                headless=True,
                args=["--autoplay-policy=user-gesture-required"],
            )
            ctx = browser.new_context(
                viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
            )
            ctx.add_init_script("(" + PROBE + ")()")
            page = ctx.new_page()
            page.set_default_timeout(10000)
            failures, requests, sockets = [], [], []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.on(
                "request",
                lambda req: requests.append((req.method, urlsplit(req.url).path)),
            )
            page.on("websocket", lambda ws: sockets.append(ws))
            page.goto(base)
            page.evaluate("async()=>{await navigator.serviceWorker.ready}")
            page.wait_for_function("navigator.serviceWorker.controller !== null")
            login(page, email, password)
            page.goto(base + path.removeprefix("/api"))
            sound = page.get_by_role("region", name="声音与字幕", exact=True)
            subtitles = sound.get_by_role("region", name="当前授权字幕")
            actions = page.locator("#game-actions")
            expect(actions.locator("button").first).to_be_enabled()
            transcript = subtitles.locator('[lang="zh-CN"]').first
            expect(transcript).to_be_visible()
            assert page.evaluate("probe.plays.length") == 0
            assert not any("/media/sea_wind" in url for _, url in requests)

            for width, height in SIZES:
                page.set_viewport_size({"width": width, "height": height})
                page.emulate_media(reduced_motion="reduce")
                if not sound.locator("details").get_attribute("open") == "":
                    sound.locator("summary").press("Enter")
                size = sound.get_by_role("slider", name="字幕字号")
                size.press("Home")
                assert (
                    transcript.evaluate("el=>getComputedStyle(el).fontSize") == "16px"
                )
                size.press("End")
                assert (
                    transcript.evaluate("el=>getComputedStyle(el).fontSize") == "28px"
                )
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth+1"
                )
                assert (
                    actions.bounding_box()["y"] + actions.bounding_box()["height"]
                    <= subtitles.bounding_box()["y"]
                )
            for size in [{"width": 844, "height": 390}, {"width": 390, "height": 844}]:
                page.set_viewport_size(size)
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth+1"
                )
            assert page.evaluate("probe.plays.length") == 0

            enable = sound.get_by_role("button", name="启用声音", exact=True)
            for error, status in [
                ("NotAllowedError", "浏览器限制播放"),
                ("NotSupportedError", "音频格式不受支持"),
            ]:
                page.evaluate("(error)=>{probe.reject=error}", error)
                before = page.evaluate("probe.plays.length")
                enable.tap()
                expect(sound.get_by_role("status").first).to_contain_text(status)
                expect(transcript).to_be_visible()
                assert page.evaluate("probe.plays.length") == before + 1
                page.get_by_role("button", name="重新读取 / 获取搭档进度").tap()
                expect(actions.locator("button").first).to_be_enabled()
                assert page.evaluate("probe.plays.length") == before + 1
                sound.get_by_role("button", name="关闭声音").tap()
            page.evaluate("probe.reject=''")
            enable.tap()
            page.wait_for_function("probe.plays.at(-1)?.element.currentTime > 0")
            sound.get_by_role("slider", name="环境音音量").press("Home")
            page.wait_for_function("probe.plays.at(-1).element.volume === 0")
            sound.get_by_role("slider", name="环境音音量").press("End")
            page.wait_for_function("probe.plays.at(-1).element.volume === 1")
            for label in ["设备音效音量", "旁白音量"]:
                slider = sound.get_by_role("slider", name=label)
                slider.press("Home")
                expect(slider).to_have_value("0")
                slider.press("End")
                expect(slider).to_have_value("1")
            sound.get_by_role("button", name="暂停声音", exact=True).press("Enter")
            assert page.evaluate("probe.plays.at(-1).element.paused")
            sound.get_by_role("button", name="继续声音", exact=True).press("Enter")
            page.wait_for_function("!probe.plays.at(-1).element.paused")
            sound.get_by_role("button", name="全局静音").press("Enter")
            assert page.evaluate(
                "probe.plays.at(-1).element.paused && probe.revoked.includes(probe.plays.at(-1).url)"
            )
            expect(transcript).to_be_visible()
            sound.get_by_role("checkbox", name="显示字幕").press("Space")
            expect(subtitles).to_have_count(0)
            sound.get_by_role("checkbox", name="显示字幕").press("Space")
            expect(transcript).to_be_visible()
            sound.get_by_role("button", name="恢复声音").press("Enter")
            page.wait_for_function("!probe.plays.at(-1).element.paused")
            sound.get_by_role("button", name="关闭声音").press("Enter")
            assert page.evaluate(
                "probe.plays.every(x=>x.element.paused && probe.revoked.includes(x.url))"
            )
            enable.tap()
            page.wait_for_function("!probe.plays.at(-1).element.paused")
            # Only a successful fresh command, not authorization or repeated reads, plays the SFX.
            actions.locator("[data-kind=inspect] button").first.tap()
            expect(page.locator("[data-test=save-entry]")).to_contain_text("进度 1")
            expect(actions.locator("[data-kind=set_emitter] button")).to_be_enabled()
            assert page.evaluate("probe.plays.filter(x=>!x.loop).length") == 0
            command(partner, path, 1, "inspect", {"target": "sea_chart"})
            expect(page.locator("[data-test=save-entry]")).to_contain_text("进度 2")
            action = actions.locator("[data-kind=set_emitter]")
            action.locator("[name=angle]").select_option(label="90")
            action.locator("[name=pattern]").select_option(label="pulse")
            action.locator("button").tap()
            expect(page.locator("[data-test=save-entry]")).to_contain_text("进度 3")
            page.wait_for_function("probe.plays.filter(x=>!x.loop).length === 1")
            page.get_by_role("button", name="重新读取 / 获取搭档进度").tap()
            expect(actions.locator("[data-kind=set_emitter] button")).to_be_enabled()
            assert page.evaluate("probe.plays.filter(x=>!x.loop).length") == 1

            # Background and network loss preserve a genuine unknown UUID.
            captured = {}

            def lose_response(route):
                response = route.fetch()
                assert response.status == 200
                captured.update(uuid=route.request.post_data_json["request_id"])
                route.abort("failed")

            page.route("**" + path + "/commands", lose_response, times=1)
            action.locator("[name=angle]").select_option(label="0")
            action.locator("[name=pattern]").select_option(label="pulse")
            action.locator("button").tap()
            expect(page.locator("#game-status")).to_contain_text("原 UUID 已保留")
            assert captured
            page.evaluate("testVisibility(true)")
            assert page.evaluate(
                "probe.plays.every(x=>x.element.paused && probe.revoked.includes(x.url))"
            )
            expect(actions.locator("button:enabled")).to_have_count(0)
            ctx.set_offline(True)
            expect(page.locator(".network-notice")).to_be_visible()
            command(partner, path, 4, "set_filter", {"filter": "amber"})
            start, socket_count, plays = (
                len(requests),
                len(sockets),
                page.evaluate("probe.plays.length"),
            )
            page.evaluate("testVisibility(false)")
            expect(actions.locator("button:enabled")).to_have_count(0)
            ctx.set_offline(False)
            expect(page.locator("[data-test=save-entry]")).to_contain_text("进度 5")
            expect(page.locator("#game-status")).to_contain_text("服务器已确认原操作")
            expect(actions.locator("[data-kind=set_emitter] button")).to_be_enabled()
            page.wait_for_function("navigator.onLine")
            restored = requests[start:]
            receipt = path + "/receipts/" + captured["uuid"]
            assert (
                restored.index(("GET", "/api/me"))
                < restored.index(("GET", path))
                < restored.index(("GET", receipt))
            )
            assert not any(method == "POST" for method, _ in restored)
            assert page.evaluate("probe.plays.length") == plays
            assert len(sockets[socket_count:]) == 1

            # Moving to repair removes the calibration transcript, retains the authorized bed.
            page.emulate_media(reduced_motion="no-preference")
            action.locator("[name=angle]").select_option(label="90")
            action.locator("[name=pattern]").select_option(label="pulse")
            action.locator("button").tap()
            expect(page.locator("[data-test=save-entry]")).to_contain_text("进度 6")
            enable.tap()
            page.wait_for_function("!probe.plays.at(-1).element.paused")
            old_url = page.evaluate("probe.plays.at(-1).url")
            command(partner, path, 6, "lock_signal")
            expect(page.locator(".scene-stage")).to_have_attribute(
                "data-stage", "lighthouse-repair"
            )
            expect(sound.locator("[data-cue=a_opening]")).to_have_count(0)
            page.wait_for_function("url=>probe.revoked.includes(url)", arg=old_url)
            command(partner, path, 7, "route_power", {"target": "tower"})
            expect(page.locator("[data-performance=clock-power-on]")).to_be_visible()
            page.evaluate("testVisibility(true)")
            expect(page.locator("[data-performance]")).to_have_count(0)
            assert page.evaluate(
                "probe.plays.every(x=>x.element.paused && probe.revoked.includes(x.url))"
            )

            # Revoke the actual browser session while hidden, then foreground it.
            token = next(c["value"] for c in ctx.cookies() if c["name"] == "tw_session")
            revoked = owner.delete(
                "/api/sessions/current", headers={"Cookie": "tw_session=" + token}
            )
            assert revoked.status_code == 204, revoked.status_code
            page.evaluate("testVisibility(false)")
            expect(page.locator("#email")).to_be_visible()
            expect(page.locator("[data-test=save-entry]")).to_have_count(0)
            assert page.evaluate("probe.blobs.every(b=>probe.revoked.includes(b.url))")
            assert page.evaluate(
                "async url=>fetch(url).then(()=>false,()=>true)", old_url
            )
            partner_email = partner.get("/api/me").json()["account"]["email"]
            login(page, partner_email, password)
            page.goto(base + path.removeprefix("/api"))
            expect(page.locator("[data-test=save-entry]")).to_contain_text("角色 B")
            expect(
                subtitles.get_by_text("发射器档位机械声", exact=False)
            ).to_have_count(0)
            assert (
                page.evaluate(
                    "async path => (await fetch(path + '/media/old_tower',{cache:'no-store'})).status",
                    path,
                )
                == 404
            )
            enable.tap()
            page.wait_for_function("probe.plays.at(-1)?.element.currentTime > 0")
            ctx.set_offline(True)
            assert page.evaluate(
                "async path => fetch(path + '/media/sea_wind',{cache:'no-store'}).then(()=>false,()=>true)",
                path,
            )
            ctx.set_offline(False)
            expect(
                page.get_by_role("link", name="返回书架", exact=False)
            ).to_be_visible()
            page.get_by_role("link", name="返回书架", exact=False).tap()
            expect(sound).to_have_count(0)
            assert page.evaluate(
                "probe.blobs.every(b => probe.revoked.includes(b.url))"
            )
            assert not failures, failures
            results[channel] = dict(
                version=browser.version,
                viewports=SIZES,
                background="injected visibility",
                real_sqlite=True,
                restored_version=5,
                continued_version=8,
            )
            browser.close()
    (OUT / "mobile-lifecycle.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        "Mobile audio, subtitles, lifecycle + real SQLite passed:", ", ".join(results)
    )


if __name__ == "__main__":
    run()
