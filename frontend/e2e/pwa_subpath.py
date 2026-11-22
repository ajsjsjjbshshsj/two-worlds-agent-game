"""Verify a second real production build under /worlds/, not just root hosting."""

import json
import os
import re
import subprocess

from playwright.sync_api import expect, sync_playwright

from pwa_cache import ROOT, OUT, free_port, wait_url


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    destination = ROOT / "work/pwa-subpath"
    vite = str(ROOT / "node_modules/vite/bin/vite.js")
    subprocess.run(
        ["node", vite, "build", "--base", "/worlds/", "--outDir", str(destination)],
        cwd=ROOT,
        check=True,
    )
    config = json.loads(
        re.search(r"const config = (.*);", (destination / "sw.js").read_text("utf-8"))[
            1
        ]
    )
    port = free_port()
    origin = f"http://127.0.0.1:{port}"
    with (OUT / "subpath.log").open("w") as log:
        process = subprocess.Popen(
            [
                "node",
                vite,
                "preview",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
                "--base",
                "/worlds/",
                "--outDir",
                str(destination),
            ],
            cwd=ROOT,
            stdout=log,
            stderr=log,
        )
        try:
            wait_url(origin + "/worlds/")
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    channel=os.environ.get("PWA_BROWSER", "msedge"), headless=True
                )
                context = browser.new_context()
                page = context.new_page()
                page.goto(origin + "/worlds/")
                scope = page.evaluate(
                    "async()=>{const r=await navigator.serviceWorker.ready;return r.scope}"
                )
                assert scope == origin + "/worlds/"
                page.wait_for_function("navigator.serviceWorker.controller !== null")
                manifest = context.request.get(
                    origin + "/worlds/manifest.webmanifest"
                ).json()
                assert (
                    manifest["start_url"]
                    == manifest["scope"]
                    == manifest["id"]
                    == "/worlds/"
                )
                assert all(
                    i["src"].startswith("/worlds/pwa/") for i in manifest["icons"]
                )
                context.set_offline(True)
                page.goto(origin + "/worlds/saves/private")
                expect(page.get_by_role("heading", name="暂时无法连接")).to_be_visible()
                assert (
                    page.get_by_role("link", name="返回应用入口").get_attribute("href")
                    == "/worlds/"
                )
                assert (
                    page.locator("body").evaluate(
                        "el=>getComputedStyle(el).backgroundColor"
                    )
                    == "rgba(0, 0, 0, 0)"
                )
                assert (
                    page.locator("html").evaluate(
                        "el=>getComputedStyle(el).backgroundColor"
                    )
                    == "rgb(9, 23, 37)"
                )
                keys = page.evaluate(
                    "async()=>{let out=[];for(const name of await caches.keys())out.push(...(await(await caches.open(name)).keys()).map(x=>x.url));return out}"
                )
                assert set(keys) == {
                    origin + "/worlds/" + r["path"] for r in config["resources"]
                }
                browser.close()
            (OUT / "subpath-results.json").write_text(
                json.dumps(
                    dict(
                        base="/worlds/",
                        scope=scope,
                        manifest=True,
                        offline=True,
                        cache_count=len(keys),
                    ),
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            process.terminate()
            process.wait(timeout=10)
    print(
        "Subpath production manifest, SW scope, cached styles and offline navigation passed"
    )


if __name__ == "__main__":
    run()
