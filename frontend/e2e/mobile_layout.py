"""Real browser layout checks with explicit TEST-ONLY HTTP/WS response fixtures.

Run while Vite is serving: python e2e/mobile_layout.py
Requires the Python Playwright package and an installed Chromium/Edge browser.
This checks frontend behavior, not real API/database or physical mobile devices.
"""

import copy
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("LAYOUT_BASE_URL", "http://127.0.0.1:5193")
OUT = Path(__file__).resolve().parents[1] / "test-results" / "t13-1"
SIZES = [
    (320, 568),
    (375, 667),
    (390, 844),
    (430, 932),
    (768, 1024),
    (1024, 768),
    (1440, 900),
]


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel=os.environ.get("LAYOUT_BROWSER", "msedge"), headless=True
        )
        seed = browser.new_page()
        seed.goto(BASE)
        data = seed.evaluate("""async () => {
          const f = await import('/tests/fixtures.ts');
          const r = await import('/tests/resource-fixtures.ts');
          const g = await import('/tests/game-fixture.ts');
          return { me: f.me, pair: r.pairA, script: r.script, invitation: r.invitation, game: g.game() };
        }""")
        seed.close()
        for width, height in SIZES:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                has_touch=width < 1024,
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(6000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            model = {
                "logged_in": False,
                "save": None,
                "commands": [],
                "uncertain": False,
            }

            def route(request):
                path = urlparse(request.request.url).path
                method = request.request.method
                status = 200
                response = {}
                if path == "/api/me":
                    response = (
                        data["me"]
                        if model["logged_in"]
                        else {
                            "error": {
                                "code": "UNAUTHORIZED",
                                "message": "test",
                                "retryable": False,
                            }
                        }
                    )
                    status = 200 if model["logged_in"] else 401
                elif path == "/api/sessions":
                    model["logged_in"] = True
                    response = data["me"]
                elif path == "/api/pairs":
                    response = (
                        data["invitation"]
                        if method == "POST"
                        else [dict(data["pair"], member_count=2)]
                    )
                elif path.endswith("/invite"):
                    response = data["invitation"]
                elif path == "/api/pairs/join":
                    response = {"id": data["pair"]["id"], "role": "b"}
                elif path == "/api/scripts":
                    response = [
                        dict(
                            data["script"], id="lighthouse", title="TEST-ONLY 跨时灯塔"
                        ),
                        dict(data["script"], id="starline", title="TEST-ONLY 末班星轨"),
                    ]
                elif path == "/api/saves":
                    response = []
                elif "/receipts/" in path:
                    response = {"accepted": False}
                elif path.endswith("/commands"):
                    command = request.request.post_data_json
                    model["commands"].append(command)
                    if model["uncertain"]:
                        status = 503
                        response = {
                            "error": {
                                "code": "DEPENDENCY_UNAVAILABLE",
                                "message": "TEST-ONLY unavailable",
                                "retryable": True,
                            }
                        }
                    else:
                        model["save"]["version"] += 1
                        if command["kind"] == "vote_ending":
                            model["save"].update(
                                scene_id="completed",
                                completed=True,
                                available_actions=[],
                            )
                            model["save"]["public"]["ending"] = command["args"][
                                "choice"
                            ]
                        response = {
                            "save": model["save"],
                            "receipt": {
                                "request_id": command["request_id"],
                                "status": "accepted",
                                "duplicate": False,
                                "accepted_version": model["save"]["version"],
                            },
                            "audio_events": [],
                        }
                elif "/media/" in path:
                    status = 404
                    response = {
                        "error": {
                            "code": "MEDIA_NOT_FOUND",
                            "message": "test",
                            "retryable": False,
                        }
                    }
                elif path.startswith("/api/saves/"):
                    response = model["save"]
                request.fulfill(
                    status=status, json=response, headers={"Cache-Control": "no-store"}
                )

            context.route("**/api/**", route)
            context.route_web_socket(
                "**/api/ws/saves/*",
                lambda ws: ws.send(
                    json.dumps({"type": "snapshot", "save": model["save"]})
                ),
            )

            def layout(label):
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth + 1"
                ), (width, label, "horizontal overflow")
                for control in page.locator(
                    "button:visible, input:visible, select:visible, summary:visible, a:visible"
                ).all():
                    if "skip-link" in (control.get_attribute("class") or ""):
                        continue
                    box = control.bounding_box()
                    assert box and box["width"] >= 43.5 and box["height"] >= 43.5, (
                        width,
                        label,
                        control.inner_text(),
                        box,
                    )
                for field in page.locator(
                    "input:visible, select:visible, textarea:visible"
                ).all():
                    assert field.evaluate("el => el.labels.length > 0"), (
                        label,
                        "missing label",
                    )
                assert not errors, errors
                results.append(
                    {"size": f"{width}x{height}", "page": label, "result": "passed"}
                )

            page.goto(BASE)
            expect(page.locator("#email")).to_be_visible()
            page.keyboard.press("Tab")
            expect(page.locator(".skip-link")).to_be_focused()
            page.keyboard.press("Enter")
            expect(page.locator("#identity-panel")).to_be_focused()
            page.locator("button[type=submit]").click()
            expect(page.locator("#identity-feedback")).to_contain_text("邮箱")
            expect(page.locator("#email")).to_be_focused()
            layout("login-validation")
            page.get_by_role("button", name="立即注册", exact=True).click()
            expect(page.locator("#display-name")).to_be_focused()
            layout("register")
            if width == 390:
                page.screenshot(path=str(OUT / "phone-identity.png"), full_page=True)
            page.get_by_role("button", name="返回登录", exact=True).click()
            page.get_by_role("button", name="忘记密码？", exact=True).click()
            layout("reset")
            page.get_by_role("button", name="返回登录", exact=True).click()
            page.locator("#email").fill("player@example.test")
            page.locator("#password").fill("example-password-123")
            page.get_by_role("button", name="显示密码", exact=True).click()
            assert page.locator("#password").get_attribute("type") == "text"
            page.get_by_role("button", name="登录", exact=True).click()
            expect(page).to_have_url(BASE + "/pairs")
            expect(page.locator("[data-test=pair-card]")).to_be_visible()
            layout("pairs")
            page.locator("[data-test=create-pair]").click()
            expect(page).to_have_url(BASE + "/pairs/pair_one")
            # Override only the member count to exercise the existing invitation form.
            page.route(
                "**/api/pairs",
                lambda r: r.fulfill(json=[dict(data["pair"], member_count=1)]),
            )
            page.reload()
            expect(page.get_by_role("button", name="生成新的邀请")).to_be_visible()
            page.get_by_role("button", name="生成新的邀请").click()
            expect(page.locator("#invite-link")).to_be_visible()
            layout("invitation")
            page.unroute("**/api/pairs")
            page.goto(BASE + "/pairs#invite=tw_invite_TEST_ONLY")
            expect(page.locator("[data-test=join-pair]")).to_be_visible()
            layout("join-confirmation")
            page.locator("[data-test=join-pair]").click()
            expect(page).to_have_url(BASE + "/pairs/pair_one")
            page.goto(BASE + "/pairs/pair_one/library")
            expect(page.locator("[data-test=script-card]")).to_have_count(2)
            layout("library")
            if width == 768:
                page.screenshot(path=str(OUT / "tablet-library.png"), full_page=True)

            for story, stages in [
                ("lighthouse", ["calibration", "repair", "decision", "completed"]),
                ("starline", ["survey", "boarding", "decision", "completed"]),
            ]:
                for stage in stages:
                    save = copy.deepcopy(data["game"])
                    save.update(
                        id="save_one",
                        script_id=story,
                        scene_id=stage,
                        version=7,
                        completed=stage == "completed",
                    )
                    save["personal"]["observations"][0]["text"] = (
                        "TEST-ONLY 长文本 " + "unbroken_identifier_" * 35
                    )
                    save["public"]["clues"] = [
                        {"id": "shared", "text": "TEST-ONLY 公共线索"}
                    ]
                    if story == "starline":
                        save["personal"]["devices"] = {
                            "echo_gate": {"position": "closed"}
                        }
                        save["available_actions"] = [
                            {
                                "id": "gate",
                                "kind": "set_echo_gate",
                                "parameters": [
                                    {
                                        "id": "position",
                                        "value_type": "string",
                                        "choices": ["closed", "east"],
                                        "max_length": 6,
                                    }
                                ],
                            }
                        ]
                    if save["completed"]:
                        save["available_actions"] = []
                    save["presentation"]["cues"] = [
                        {
                            "id": "voice",
                            "alt_text": "TEST-ONLY 当前旁白",
                            "assets": [
                                {
                                    "asset_id": "voice",
                                    "kind": "narration",
                                    "alt_text": "TEST-ONLY 当前旁白",
                                    "transcript": "TEST-ONLY 声音不可用时仍可阅读完整叙事文字。",
                                }
                            ],
                        }
                    ]
                    model["save"] = save
                    page.goto(BASE + "/saves/save_one")
                    expect(page.locator(".scene-stage")).to_have_attribute(
                        "data-stage", f"{story}-{stage}"
                    )
                    expect(page.locator("#game-audio")).to_be_visible()
                    if save["completed"]:
                        expect(page.locator("#game-actions")).to_have_count(0)
                    else:
                        hotspot = page.locator(".device-hotspot").first
                        hotspot.tap() if width < 1024 else hotspot.click()
                        expect(page.locator(".confirmed-device").first).to_be_focused()
                        assert (
                            page.locator(".confirmed-device").first.evaluate(
                                "el => getComputedStyle(el).outlineStyle"
                            )
                            != "none"
                        )
                        page.get_by_role("link", name="行动", exact=True).click()
                        action = page.locator("#game-actions")
                        assert (
                            action.bounding_box()["y"]
                            < page.locator("#game-information").bounding_box()["y"]
                            or width >= 768
                        )
                        expect(action.locator("button").first).to_be_enabled()
                    page.get_by_text("声音与字幕设置", exact=True).click()
                    page.locator("input[type=range]").first.fill("0.25")
                    layout(f"{story}-{stage}")
                    if (
                        width == 390
                        and story == "lighthouse"
                        and stage == "calibration"
                    ):
                        page.screenshot(
                            path=str(OUT / "phone-game.png"), full_page=True
                        )
                    if width == 1440 and story == "starline" and stage == "survey":
                        page.screenshot(
                            path=str(OUT / "desktop-game.png"), full_page=True
                        )
                    if stage == stages[0]:
                        before = len(model["commands"])
                        page.locator("#game-actions select").first.select_option("1")
                        page.locator("#game-actions button[type=submit]").first.click()
                        expect(page.locator("[data-test=save-entry]")).to_contain_text(
                            "进度 8"
                        )
                        assert len(model["commands"]) == before + 1
                        assert model["commands"][-1]["expected_version"] == 7
                        if story == "lighthouse":
                            model["uncertain"] = True
                            page.locator(
                                "#game-actions button[type=submit]"
                            ).first.click()
                            expect(
                                page.get_by_role(
                                    "button", name="手动确认原请求", exact=False
                                )
                            ).to_be_visible()
                            layout("pending-command")
                            page.reload()
                            expect(
                                page.get_by_role("button", name="查询原操作回执")
                            ).to_be_visible()
                            layout("recovered-uuid")
                            page.once("dialog", lambda dialog: dialog.dismiss())
                            clear = page.get_by_role(
                                "button", name="清除本机待确认记录"
                            )
                            clear.click()
                            expect(clear).to_be_focused()
                            model["uncertain"] = False
                            # Remove this TEST-ONLY pending record through its real UI confirmation.
                            page.once("dialog", lambda dialog: dialog.accept())
                            clear.click()
                            expect(clear).to_have_count(0)
            for story in ["lighthouse", "starline"]:
                partner = copy.deepcopy(data["game"])
                partner.update(
                    script_id=story,
                    role="b",
                    scene_id="repair" if story == "lighthouse" else "boarding",
                )
                partner["personal"]["devices"] = (
                    {"power_router": {"target": "shore"}}
                    if story == "lighthouse"
                    else {
                        "power_panel": {"engine": False, "sonar": True, "lamp": False}
                    }
                )
                partner["available_actions"] = [
                    {
                        "id": "power",
                        "kind": "allocate_power",
                        "parameters": [
                            {
                                "id": key,
                                "value_type": "boolean",
                                "choices": [],
                                "max_length": None,
                            }
                            for key in ["engine", "sonar", "lamp"]
                        ],
                    }
                ]
                model["save"] = partner
                page.goto(BASE + "/saves/save_one")
                expect(page.locator(".device-hotspot")).to_be_visible()
                assert (
                    page.locator(".confirmed-device").inner_text().find("emitter") == -1
                )
                page.locator("input[name=engine]").check()
                layout(story + "-partner-touch-controls")
                page.locator(".device-hotspot").tap() if width < 1024 else page.locator(
                    ".device-hotspot"
                ).click()
                expect(page.locator(".confirmed-device")).to_be_focused()
            # Exercise a real WAAPI ending and its in-flow skip control at each size.
            page.emulate_media(reduced_motion="no-preference")
            ending = copy.deepcopy(data["game"])
            ending.update(script_id="lighthouse", scene_id="decision")
            ending["available_actions"] = [
                {
                    "id": "vote",
                    "kind": "vote_ending",
                    "parameters": [
                        {
                            "id": "choice",
                            "value_type": "string",
                            "choices": ["guide_now", "wait_tide"],
                            "max_length": 16,
                        }
                    ],
                }
            ]
            model["save"] = ending
            page.goto(BASE + "/saves/save_one")
            page.locator("#game-actions button[type=submit]").click()
            skip = page.get_by_role("button", name="跳过演出", exact=True)
            expect(skip).to_be_visible()
            layout("skippable-ending")
            skip.tap() if width < 1024 else skip.click()
            expect(skip).to_have_count(0)
            expect(page.locator("#game-actions")).to_have_count(0)
            page.emulate_media(reduced_motion="reduce")
            # Text enlargement/reflow and landscape use the same public page.
            page.goto(BASE + "/pairs/pair_one/library")
            page.add_style_tag(
                content="html { font-size: 32px; } p, button, a, label, h2 { font-size: 2em; }"
            )
            layout("enlarged-text")
            if width == 1440:
                assert (
                    page.locator(".script-grid").evaluate(
                        "el => getComputedStyle(el).gridTemplateColumns.split(' ').length"
                    )
                    == 2
                )
            page.set_viewport_size({"width": height, "height": width})
            layout("landscape")
            context.close()
        (OUT / "results.json").write_text(
            json.dumps(
                {
                    "browser": browser.version,
                    "cases": results,
                    "physical_devices": "not tested",
                    "backend": "explicit HTTP/WS fixtures",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()
    print(f"{len(results)} browser layout cases passed; evidence: {OUT}")


if __name__ == "__main__":
    run()
