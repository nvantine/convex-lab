"""Real Chromium tests with synthetic examples and a temporary Django database."""
import asyncio
import os
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from playwright.sync_api import sync_playwright, expect
from playwright.async_api import async_playwright

pytestmark = [pytest.mark.browser, pytest.mark.django_db(transaction=True)]
SHOTS = Path("screenshots/milestone-1")


def launch_options():
    executable = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    return {"executable_path": executable} if executable else {}


@pytest.fixture
def browser_user():
    return get_user_model().objects.create_user(username="guest", password="testing-passphrase-123")


def login(page, base):
    page.goto(base + "/login/")
    page.get_by_label("Username").fill("guest")
    page.get_by_label("Password").fill("testing-passphrase-123")
    page.get_by_role("button", name="Log in", exact=True).click()
    expect(page.get_by_role("heading", name="Your optimization notebook")).to_be_visible()


def screenshot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


def assert_rendering(page):
    page.wait_for_load_state("load")
    assert page.locator(".math[data-math]").count() > 0
    expect(page.locator(".math[data-math] .katex")).to_have_count(page.locator(".math[data-math]").count())
    assert page.locator(".math-error, .katex-error").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_browser_editor_results_errors_and_mobile(live_server, browser_user):
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_options())
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        errors, external = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("request", lambda request: external.append(request.url) if not request.url.startswith(live_server.url) else None)
        page.goto(live_server.url + "/login/")
        screenshot(page, "01-login")
        page.get_by_label("Username").fill("guest")
        page.get_by_label("Password").fill("wrong-password")
        page.get_by_role("button", name="Log in", exact=True).click()
        expect(page.get_by_text("Please enter a correct username and password.")).to_be_visible()
        login(page, live_server.url)
        screenshot(page, "02-home-empty")
        page.get_by_role("link", name="New problem", exact=True).click()
        expect(page.locator("#variables-editor .declaration")).to_have_count(1)
        assert_rendering(page)
        screenshot(page, "03-editor")
        # Change the problem through the actual row editor, not raw JSON.
        page.locator("#id_name").fill("Browser minimum variance")
        page.get_by_role("button", name="Solve & save experiment").click()
        expect(page.locator("#solver-status")).to_have_text("optimal")
        expect(page.locator(".chart .main-svg").first).to_be_visible()
        assert_rendering(page)
        screenshot(page, "04-result")
        original_url = page.url
        page.get_by_role("button", name="Expand chart").click()
        expect(page.locator("#chart-dialog")).to_be_visible()
        expect(page.locator("#expanded-chart .main-svg").first).to_be_visible()
        screenshot(page, "05-expanded-chart")
        page.get_by_role("button", name="Close chart", exact=True).click()
        page.get_by_role("button", name="Clone into an editable problem").click()
        page.locator("#id_constraints").fill("sum(w) == 1\nw >= 0\nw[0] <= 0.6")
        page.get_by_role("button", name="Check math & DCP").click()
        expect(page.locator(".constraints > li")).to_have_count(3)
        assert_rendering(page)
        page.get_by_role("button", name="Save draft", exact=True).click()
        expect(page.get_by_text("Draft saved.", exact=False)).to_be_visible()
        page.get_by_role("button", name="Solve & save experiment").click()
        expect(page.locator("#solver-status")).to_have_text("optimal")
        # Original experiment remains unchanged.
        page.goto(original_url)
        expect(page.locator(".constraints > li")).to_have_count(2)
        page.get_by_role("link", name="New problem", exact=True).click()
        page.locator("#id_expression").fill("w[0] * w[1]")
        page.get_by_role("button", name="Solve & save experiment").click()
        expect(page.get_by_text("DCP verdict: not recognized")).to_be_visible()
        assert_rendering(page)
        screenshot(page, "06-non-dcp")
        page.locator("#id_expression").fill("quad_form(")
        page.get_by_role("button", name="Solve & save experiment").click()
        expect(page.get_by_text("Bad syntax.", exact=False)).to_be_visible()
        screenshot(page, "07-bad-syntax")
        page.locator("#id_expression").fill("quad_form(w, Sigma)")
        page.locator("#id_constraints").fill("sum(w) == 1\nw >= 0\nw <= -1")
        page.get_by_role("button", name="Solve & save experiment").click()
        expect(page.locator("#solver-status")).to_have_text("infeasible")
        expect(page.locator(".duals-table tbody tr").first).to_contain_text("Unavailable")
        assert_rendering(page)
        screenshot(page, "08-infeasible")
        page.get_by_role("link", name="New problem", exact=True).click()
        page.locator("#id_expression").fill("missing_mu @ w")
        page.get_by_role("button", name="Check math & DCP").click()
        expect(page.get_by_text("Unknown name 'missing_mu'", exact=False)).to_be_visible()
        screenshot(page, "09-missing-parameter")
        # Parameter promotion is an actual editable role switch.
        page.goto(live_server.url + "/problems/new/?preset=mean-variance")
        page.locator("#parameters-editor .declaration").last.get_by_role("button", name="Make variable").click()
        expect(page.locator("#variables-editor .declaration")).to_have_count(2)
        page.get_by_role("button", name="Check math & DCP").click()
        expect(page.get_by_text("DCP verdict: not recognized")).to_be_visible()
        screenshot(page, "10-promoted-variable")
        # Add/remove declarations and reject malformed raw JSON without submitting.
        page.goto(live_server.url + "/problems/new/?preset=least-squares")
        page.get_by_role("button", name="Add parameter", exact=True).click()
        row = page.locator("#parameters-editor .declaration").last
        row.locator('[data-field="name"]').fill("extra")
        row.locator('[data-field="value"]').fill("{")
        page.get_by_role("button", name="Check math & DCP").click()
        expect(page.locator("#declaration-error")).to_be_visible()
        row.locator('[data-field="value"]').fill("2")
        page.get_by_role("button", name="Check math & DCP").click()
        expect(page.get_by_text("DCP verdict: passes")).to_be_visible()
        row = page.locator("#parameters-editor .declaration").last
        row.locator('[data-field="value"]').fill("1.234567890123456e-8")
        row.locator('[data-field="domain"]').select_option("nonneg")
        page.locator("#id_expression").fill("sum_squares(A @ x - b) + extra * sum_squares(x)")
        page.get_by_role("button", name="Check math & DCP").click()
        expect(page.get_by_text("DCP verdict: passes")).to_be_visible()
        assert_rendering(page)
        page.locator("#parameters-editor .declaration").last.get_by_role("button", name="Remove", exact=True).click()
        page.locator("#id_expression").fill("sum_squares(A @ x - b)")
        expect(page.locator("#parameters-editor .declaration")).to_have_count(2)
        raw = page.locator("#id_variables")
        raw.locator("..").locator("summary").click()
        good_json = raw.input_value()
        raw.fill("{")
        page.get_by_role("button", name="Check math & DCP").click()
        expect(page.locator("#declaration-error")).to_be_visible()
        raw.fill(good_json)
        page.get_by_role("button", name="Check math & DCP").click()
        expect(page.locator("#declaration-error")).to_have_count(0)
        assert_rendering(page)
        # Render every example, including matrices and large CVaR expressions.
        for preset in ["mean-variance", "risk-cap", "signed", "least-squares", "regularized-ls", "linear-program", "socp", "cvar"]:
            page.goto(live_server.url + f"/problems/new/?preset={preset}")
            assert_rendering(page)
            page.get_by_role("button", name="Solve & save experiment").click()
            expect(page.locator("#solver-status")).to_have_text("optimal")
            assert_rendering(page)
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(live_server.url + "/problems/new/?preset=cvar")
        assert_rendering(page)
        screenshot(page, "11-mobile-editor")
        page.goto(original_url)
        assert_rendering(page)
        expect(page.locator(".chart .main-svg").first).to_be_visible()
        screenshot(page, "12-mobile-result")
        page.get_by_role("link", name="Home", exact=True).click()
        screenshot(page, "13-home-saved")
        page.get_by_role("button", name="Log out guest").click()
        expect(page.get_by_role("heading", name="Log in", exact=True)).to_be_visible()
        assert not errors, errors
        assert not external, external
        browser.close()


def test_browser_five_guest_sessions_solve_together(live_server, browser_user):
    async def exercise():
        async with async_playwright() as p:
            browser = await p.chromium.launch(**launch_options())
            contexts = [await browser.new_context() for _ in range(5)]
            pages = [await context.new_page() for context in contexts]
            async def sign_in(page, index):
                await page.goto(live_server.url + "/login/")
                await page.get_by_label("Username").fill("guest")
                await page.get_by_label("Password").fill("testing-passphrase-123")
                await page.get_by_role("button", name="Log in", exact=True).click()
                await page.get_by_role("link", name="New problem", exact=True).click()
                await page.locator("#id_name").fill(f"Concurrent guest {index}")
            await asyncio.gather(*(sign_in(page, i) for i, page in enumerate(pages)))
            await asyncio.gather(*(page.get_by_role("button", name="Solve & save experiment").click() for page in pages))
            urls = [page.url for page in pages]
            for i, page in enumerate(pages):
                assert await page.locator("#solver-status").inner_text() == "optimal"
                await page.goto(live_server.url + "/")
                assert await page.locator("tbody tr").count() == 1
                assert await page.locator("tbody").get_by_role("link", name=f"Concurrent guest {i}", exact=True).count() == 1
                response = await page.goto(urls[(i + 1) % 5])
                assert response.status == 404
            await browser.close()
    asyncio.run(exercise())
