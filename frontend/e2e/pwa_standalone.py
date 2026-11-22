"""Install, launch and uninstall TwoWorlds in an isolated desktop Chrome profile.

Requires the production build, project backend environment, Chrome, and a desktop
session. Uses Chrome's PWA DevTools commands with a real app window.
"""

import json

from playwright.sync_api import expect, sync_playwright

from mobile_lifecycle import launch_options, login
from pwa_cache import OUT
from pwa_sqlite import sqlite_preview


def run():
    with (
        sqlite_preview() as (folder, base, _, _, email, password, save),
        sync_playwright() as p,
    ):
        context = p.chromium.launch_persistent_context(
            str(folder / "standalone-profile"),
            **launch_options("chrome"),
            headless=False,
            viewport={"width": 1440, "height": 900},
        )
        page = context.pages[0]
        page.goto(base)
        page.evaluate("async()=>{await navigator.serviceWorker.ready}")
        page.wait_for_function("navigator.serviceWorker.controller !== null")
        cdp = context.new_cdp_session(page)
        assert cdp.send("Page.getInstallabilityErrors")["installabilityErrors"] == []
        login(page, email, password)
        manager = context.browser.new_browser_cdp_session()
        app = {"manifestId": base + "/"}
        manager.send("PWA.install", {**app, "installUrlOrBundleUrl": base + "/"})
        try:
            manager.send(
                "PWA.changeAppUserSettings", {**app, "displayMode": "standalone"}
            )

            def launch():
                with context.expect_page(timeout=10000) as launched:
                    manager.send("PWA.launch", app)
                return launched.value

            installed = launch()
            expect(
                installed.get_by_role("link", name="进入我的房间", exact=False)
            ).to_be_visible()
            assert installed.evaluate(
                'matchMedia("(display-mode: standalone)").matches'
            )
            game_url = base + "/saves/" + save["id"]
            installed.goto(game_url)
            expect(installed.locator("#game-actions button").first).to_be_enabled()
            assert installed.evaluate(
                "document.documentElement.scrollWidth <= innerWidth+1"
            )
            installed.close()

            # Apply offline at target creation, before the installed window navigates.
            context.set_offline(True)
            installed = launch()
            expect(
                installed.get_by_role("heading", name="暂时无法连接")
            ).to_be_visible()
            assert installed.evaluate(
                'matchMedia("(display-mode: standalone)").matches'
            )
            assert (
                email not in installed.content()
                and save["id"] not in installed.content()
            )
            installed.screenshot(path=str(OUT / "standalone-offline.png"))
            entries = installed.evaluate("""async()=>{
              const all=[]; for(const key of await caches.keys()) {
                const cache=await caches.open(key);
                for(const req of await cache.keys()) all.push(new URL(req.url).pathname);
              } return all;
            }""")
            assert len(entries) == 10 and all(
                not key.startswith("/api/") for key in entries
            )
            context.set_offline(False)
            installed.get_by_role("button", name="重新连接").click()
            expect(
                installed.get_by_role("link", name="进入我的房间", exact=False)
            ).to_be_visible()
            installed.goto(game_url)
            expect(installed.locator("#game-actions button").first).to_be_enabled()
            expect(installed.locator("[data-test=save-entry]")).to_contain_text(
                "进度 0"
            )
            (OUT / "standalone-results.json").write_text(
                json.dumps(
                    {
                        "browser": context.browser.version,
                        "installability": True,
                        "display_mode": "standalone",
                        "offline_relaunch": True,
                        "connected_recovery": True,
                        "cache_count": len(entries),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            try:
                manager.send("PWA.uninstall", app)
            finally:
                context.close()
    print("Desktop Chrome installed standalone, offline relaunch, and recovery passed")


if __name__ == "__main__":
    run()
