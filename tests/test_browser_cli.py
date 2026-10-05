"""Human review of research produced through the same services as the CLI."""
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from lab import services
from lab.workspaces import Scope, owner_workspace
from core.presets import get_preset
from test_browser import launch_options, assert_rendering
from test_browser_data import read_db

pytestmark = [pytest.mark.browser, pytest.mark.django_db(transaction=True)]


def shot(page, stage, name):
    folder = Path("screenshots/cli") / stage
    folder.mkdir(parents=True, exist_ok=True)
    page.wait_for_function("document.documentElement.scrollWidth <= window.innerWidth")
    page.wait_for_function("""() => [...document.querySelectorAll('.chart .main-svg')]
        .every(el => Number(el.getAttribute('width')) <= el.closest('.chart').clientWidth + 1)""")
    page.screenshot(path=str(folder / (name + ".png")), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def login_owner(page, base, owner):
    page.goto(base + "/login/")
    page.get_by_label("Username").fill(owner.username)
    page.get_by_label("Password").fill("testing-passphrase-123")
    page.get_by_role("button", name="Log in", exact=True).click()
    expect(page.get_by_role("heading", name="Your optimization notebook")).to_be_visible()


def test_cli_owner_result_on_website(live_server, owner):
    scope = Scope(owner, owner_workspace(owner))
    saved = services.solve_problem(scope, "CLI-created minimum variance", get_preset("min-variance"))
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_options())
        page = browser.new_page(viewport={"width":1280, "height":900})
        errors = []; page.on("pageerror", lambda e: errors.append(str(e)))
        login_owner(page, live_server.url, owner)
        shot(page, "milestone-1", "01-owner-notebook")
        page.locator(f'a[href="/results/{saved.pk}/"]').click()
        assert_rendering(page)
        expect(page.locator("#solver-status")).to_have_text("optimal")
        expect(page.locator(".chart .main-svg").first).to_be_visible()
        shot(page, "milestone-1", "02-cli-solution")
        page.set_viewport_size({"width":390, "height":844})
        shot(page, "milestone-1", "03-mobile-solution")
        assert not errors
        browser.close()


def test_custom_research_source_errors_and_live_update(live_server, owner, settings, tmp_path):
    from lab import research
    settings.LAB_ARTIFACT_ROOT = tmp_path / "artifacts"
    scope = Scope(owner, owner_workspace(owner))
    revision = research.register(scope, Path("examples/research"), "simulation.py:run", "research", "Normal simulation")
    run, _ = research.begin(scope, revision.name, "research", {"seed":42}, revision=revision)
    research.run_python(run, {"count":50}, {}, 42, 30)
    pending, _ = research.begin(scope, "Pending model", "research", {})
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_options())
        page = browser.new_page(viewport={"width":1280,"height":900})
        errors=[]; page.on("pageerror",lambda e: errors.append(str(e)))
        login_owner(page,live_server.url,owner)
        page.get_by_role("link",name="Research",exact=True).click()
        expect(page.get_by_role("heading",name="Research ledger")).to_be_visible()
        shot(page,"milestone-2","01-research-ledger")
        page.locator(f'a[href="/research/{run.pk}/"]').click()
        assert_rendering(page)
        expect(page.locator(".chart .main-svg").first).to_be_visible()
        shot(page,"milestone-2","02-simulation-report")
        page.get_by_role("link",name="Source revision:",exact=False).click()
        page.get_by_text("simulation.py",exact=True).click()
        expect(page.get_by_text("def run(context, params):",exact=False)).to_be_visible()
        shot(page,"milestone-2","03-source-revision")
        page.goto(f"{live_server.url}/research/{pending.pk}/")
        expect(page.locator("#research-status")).to_have_text("running")
        read_db(lambda: research.finish(pending,status="failed",error="Intentional model failure for browser verification"))
        expect(page.locator("#research-status")).to_have_text("failed",timeout=12000)
        expect(page.get_by_role("alert")).to_contain_text("Intentional model failure")
        shot(page,"milestone-2","04-saved-failure")
        page.goto(f"{live_server.url}/research/{run.pk}/")
        page.set_viewport_size({"width":390,"height":844})
        shot(page,"milestone-2","05-mobile-report")
        assert not errors
        browser.close()
