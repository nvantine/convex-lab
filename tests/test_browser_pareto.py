"""Drive LaTeX editing and frontier workflows with local assets and actual Chromium."""
import json
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from test_browser import launch_options, login, assert_rendering, browser_user

pytestmark = [pytest.mark.browser, pytest.mark.django_db(transaction=True)]
SHOTS = Path('.local/browser-regression-m2')


def shot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f'{name}.png'), full_page=True)


def solve_frontier(page, base, key, method='weighted'):
    page.goto(base + '/problems/new/?preset=' + key)
    page.locator('#id_samples').fill('12')
    page.locator('#id_method').select_option(method)
    assert_rendering(page)
    page.get_by_role('button', name='Solve & save experiment').click()
    expect(page.locator('#frontier-status')).to_have_text('complete')
    expect(page.locator('.frontier-chart .plot-container').first).to_be_visible()
    assert_rendering(page)
    return page.url


def test_latex_equations_edit_convert_and_errors(live_server, browser_user):
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_options())
        page = browser.new_page(viewport={'width':1280,'height':900})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        login(page, live_server.url)
        page.goto(live_server.url+'/problems/new/?preset=mean-variance')
        expect(page.locator('#id_expression')).to_be_hidden()
        expect(page.locator('.equation-render .katex').first).to_be_visible()
        assert_rendering(page)
        shot(page, '01-latex-editor')
        page.get_by_role('button', name='Edit equation LaTeX', exact=True).click()
        expression = page.locator('#id_expression')
        expect(expression).to_be_visible()
        expression.fill(r'\mu^{\top} w - 3 w^{\top} \Sigma w')
        expect(page.locator('#single-editor .equation-render .katex')).to_be_visible()
        shot(page, '02-live-preview')
        page.locator('#id_name').click()
        expect(expression).to_be_hidden()
        page.get_by_role('button', name='Check math & DCP').click()
        assert_rendering(page)
        assert 'quad_form' not in page.locator('.math-panel').inner_text()
        shot(page, '03-mathematical-problem')
        page.get_by_role('button', name='Use expression input', exact=True).click()
        expect(page.locator('#id_expression')).to_be_visible()
        page.locator('#id_expression').fill(r'latex(r"\mu^\top w") - 3 * quad_form(w, Sigma)')
        page.get_by_role('button', name='Solve & save experiment').click()
        expect(page.locator('#solver-status')).to_have_text('optimal')
        assert_rendering(page)
        shot(page, '04-latex-result-and-duals')
        page.get_by_role('button', name='Clone into an editable problem').click()
        page.get_by_role('button', name='Edit equation LaTeX', exact=True).click()
        page.locator('#id_expression').fill(r'w_0 w_1')
        page.get_by_role('button', name='Check math & DCP').click()
        expect(page.get_by_text('DCP verdict: not recognized')).to_be_visible()
        assert_rendering(page)
        shot(page, '05-latex-dcp-error')
        page.get_by_role('button', name='Edit equation LaTeX', exact=True).click()
        page.locator('#id_expression').fill(r'\unsupported{w}')
        page.get_by_role('button', name='Check math & DCP').click()
        expect(page.locator('#problem-form > .errorlist')).to_contain_text('LaTeX input')
        shot(page, '06-latex-syntax-error')
        page.goto(live_server.url+'/problems/new/')
        page.get_by_role('button', name='Edit constraints LaTeX', exact=True).click()
        page.locator('#id_constraints').fill(r'\sum_i w_i = 1'+'\n'+r'w \le -1')
        page.get_by_role('button', name='Solve & save experiment').click()
        expect(page.locator('#solver-status')).to_have_text('infeasible')
        assert_rendering(page)
        shot(page, '07-infeasible')
        page.goto(live_server.url+'/problems/new/')
        page.get_by_role('button', name='Edit equation LaTeX', exact=True).click()
        page.locator('#id_expression').fill(r'\theta^\top w')
        page.get_by_role('button', name='Check math & DCP').click()
        expect(page.locator('#problem-form > .errorlist')).to_contain_text('Unknown symbol')
        shot(page, '08-missing-parameter')
        assert not errors, errors
        browser.close()


def test_frontier_plot_click_choose_epsilon_and_many_criteria(live_server, browser_user):
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_options())
        page = browser.new_page(viewport={'width':1280,'height':900})
        errors, external = [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type=='error' else None)
        page.on('request', lambda r: external.append(r.url) if not r.url.startswith(live_server.url) else None)
        login(page, live_server.url)
        page.goto(live_server.url+'/problems/new/?preset=return-risk')
        expect(page.locator('#criteria-editor .declaration')).to_have_count(2)
        page.get_by_role('button', name='Add criterion', exact=True).click()
        row = page.locator('#criteria-editor .declaration').last
        row.locator('[data-field="name"]').fill('Position size')
        row.get_by_role('button', name='Edit equation LaTeX').click()
        row.locator('[data-field="expression"]').fill(r'\|w\|_2^2')
        page.get_by_role('button', name='Check math & DCP').click()
        expect(page.get_by_text('DCP verdict: passes')).to_be_visible()
        expect(page.locator('.math-panel h4')).to_have_count(3)
        page.locator('#criteria-editor .declaration').last.get_by_role('button', name='Remove', exact=True).click()
        page.locator('#id_samples').fill('12')
        shot(page, '09-criteria-editor')
        page.get_by_role('button', name='Solve & save experiment').click()
        expect(page.locator('#frontier-status')).to_have_text('complete')
        expect(page.locator('#frontier-2d .scatterlayer .point').first).to_be_visible()
        frontier = page.url
        assert_rendering(page)
        shot(page, '10-two-criteria-frontier')
        # Real pointer click on a plotted point, not a synthetic Plotly event.
        page.locator('#frontier-2d .scatterlayer .point').nth(2).click(force=True)
        expect(page.get_by_role('heading', name='How this point was produced')).to_be_visible()
        expect(page.get_by_text('Weight / epsilon bound', exact=True)).to_be_visible()
        assert_rendering(page)
        shot(page, '11-inspected-point')
        page.get_by_role('button', name='Save as chosen solution').click()
        expect(page.locator('#solver-status')).to_have_text('optimal')
        expect(page.get_by_role('link', name='Return to frontier')).to_be_visible()
        shot(page, '12-chosen-solution')
        page.goto(frontier)
        page.get_by_role('button', name='Expand chart', exact=True).click()
        expect(page.locator('#chart-dialog')).to_be_visible()
        shot(page, '13-expanded-frontier')
        page.get_by_role('button', name='Close chart', exact=True).click()
        solve_frontier(page, live_server.url, 'return-risk', 'epsilon')
        shot(page, '14-epsilon-frontier')
        # Pick an epsilon-generated point using its table entry.
        page.locator('tr').filter(has=page.locator('td', has_text='epsilon')).first.get_by_role('link').click()
        expect(page.get_by_text('secondary objective', exact=False)).to_be_visible()
        assert_rendering(page)
        shot(page, '15-epsilon-math-and-duals')
        solve_frontier(page, live_server.url, 'return-risk-turnover')
        expect(page.locator('#frontier-3d canvas').first).to_be_visible()
        page.locator('#frontier-3d').scroll_into_view_if_needed()
        box = page.locator('#frontier-3d').bounding_box()
        page.mouse.move(box['x']+box['width']/2, box['y']+220)
        page.mouse.down(); page.mouse.move(box['x']+box['width']/2+80, box['y']+250); page.mouse.up()
        # Enable optional surface from the legend when this sample supports it.
        legend = page.locator('#frontier-3d .legendtext').filter(has_text='Interpolation')
        expect(legend).to_have_count(1)
        legend.locator('..').locator('.legendtoggle').click()
        page.wait_for_function("document.querySelector('#frontier-3d').data[1].visible === true")
        page.wait_for_timeout(400)
        shot(page, '16-three-criteria-surface')
        many = solve_frontier(page, live_server.url, 'four-criteria')
        expect(page.locator('#parallel .parcoords')).to_be_visible()
        expect(page.locator('#pairwise canvas').first).to_be_visible()
        shot(page, '17-four-criteria-views')
        page.set_viewport_size({'width':390,'height':844})
        page.goto(many)
        assert_rendering(page)
        shot(page, '18-mobile-frontier')
        page.goto(live_server.url+'/problems/new/?preset=four-criteria')
        assert_rendering(page)
        shot(page, '19-mobile-criteria-editor')
        assert not errors, errors
        assert not external, external
        browser.close()
