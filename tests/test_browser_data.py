"""Drive synchronous fetch, training, signed evaluation, and the holdout gate."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from playwright.sync_api import sync_playwright, expect
from test_browser import browser_user, login, launch_options, assert_rendering
from test_data_views import fetcher
from lab.models import Dataset, Evaluation

pytestmark=[pytest.mark.browser,pytest.mark.django_db(transaction=True)]
SHOTS=Path('screenshots/milestone-3')


def read_db(function):
    # Playwright's synchronous API still owns an event loop on this thread.
    # Keep Django's synchronous DB access in a separate, short-lived thread.
    def read():
        from django.db import connections
        try:
            return function()
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(read).result()


def shot(page,name):
    SHOTS.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(SHOTS/f'{name}.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')


def fill_fetch(page,symbols='SPY, AGG',source='alpaca'):
    page.locator('#id_name').fill('Browser market history')
    page.get_by_label('Data provider').select_option(source)
    page.get_by_label('Ticker symbols').fill(symbols)
    page.get_by_label('Start date').fill('2023-01-01')
    page.get_by_label('End date').fill('2024-12-31')


def chart_visible(page):
    expect(page.locator('.chart .main-svg').first).to_be_visible()
    page.wait_for_function('document.documentElement.scrollWidth <= window.innerWidth')


def test_dataset_to_validation_and_confirmed_final(live_server,browser_user,fetcher):
    with sync_playwright() as p:
        browser=p.chromium.launch(**launch_options())
        page=browser.new_page(viewport={'width':1280,'height':900})
        page.set_default_timeout(8000)
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('console',lambda msg:errors.append(msg.text) if msg.type=='error' else None)
        login(page,live_server.url)
        page.get_by_role('link',name='Datasets',exact=True).click()
        fill_fetch(page)
        shot(page,'01-dataset-fetch')
        page.get_by_role('button',name='Fetch & save dataset').click()
        expect(page.get_by_role('heading',name='Browser market history',exact=True)).to_be_visible()
        chart_visible(page)
        assert '123456.789' not in page.content()
        expect(page.get_by_text('Final holdout locked.',exact=False)).to_be_visible()
        shot(page,'02-dataset-windows')
        dataset_url=page.url
        page.get_by_label('Starting example').select_option('mean-variance')
        page.get_by_label('Training return observations').fill('100')
        page.get_by_role('button',name='Create editable problem').click()
        expect(page.get_by_role('heading',name='Training data binding')).to_be_visible()
        assert_rendering(page)
        math=page.locator('.math-panel .math').first
        # Check the actual typeset specification, not just the live input preview.
        assert r'\left(' not in math.locator('annotation').text_content()
        shot(page,'03-training-problem-minimal-grouping')
        page.locator('.math-panel').screenshot(path=str(SHOTS/'15-mathematical-specification.png'))
        page.get_by_role('button',name='Solve & save experiment').click()
        expect(page.locator('#solver-status')).to_have_text('optimal')
        page.get_by_role('link',name='Evaluate fixed holdings').click()
        expect(page.get_by_text('Imported estimates and scenarios are unchanged',exact=False)).to_be_visible()
        expect(page.get_by_label('Frozen dataset')).to_have_value(read_db(lambda:str(Dataset.objects.get().pk)))
        page.get_by_label('Entry trading cost').fill('15')
        shot(page,'04-evaluation-settings')
        page.get_by_role('button',name='Evaluate validation & save').click()
        expect(page.get_by_role('heading',name='Validation evaluation',exact=True)).to_be_visible()
        chart_visible(page)
        shot(page,'05-validation-result')
        page.get_by_role('button',name='Expand chart').first.click()
        expect(page.locator('#chart-dialog')).to_be_visible()
        expect(page.locator('#expanded-chart .main-svg').first).to_be_visible()
        shot(page,'06-expanded-evaluation-chart')
        page.get_by_role('button',name='Close chart',exact=True).click()
        page.get_by_role('link',name='Evaluate with other validation assumptions').click()
        page.get_by_role('button',name='Review final holdout…').click()
        expect(page.get_by_role('heading',name='Confirm final holdout',exact=True)).to_be_visible()
        assert read_db(lambda:Evaluation.objects.filter(window='holdout').count())==0
        shot(page,'07-holdout-confirmation')
        page.get_by_role('link',name='Cancel and return to validation').click()
        assert read_db(lambda:Evaluation.objects.filter(window='holdout').count())==0
        page.get_by_role('button',name='Review final holdout…').click()
        page.get_by_role('checkbox').check()
        page.get_by_role('button',name='Open final holdout & save').click()
        expect(page.get_by_role('heading',name='Final holdout evaluation',exact=True)).to_be_visible()
        chart_visible(page)
        assert read_db(lambda:Evaluation.objects.filter(window='holdout').count())==1
        final_url=page.url
        shot(page,'08-final-holdout-result')
        page.goto(dataset_url)
        page.get_by_role('link',name='View its frozen evaluation').click()
        assert page.url==final_url
        page.set_viewport_size({'width':390,'height':844})
        page.goto(final_url)
        chart_visible(page)
        shot(page,'09-mobile-evaluation')
        page.goto(dataset_url)
        chart_visible(page)
        shot(page,'10-mobile-dataset')
        assert not errors,errors
        browser.close()


def test_single_asset_yfinance_fetch_errors_and_signed_weights(live_server,browser_user,fetcher):
    with sync_playwright() as p:
        browser=p.chromium.launch(**launch_options())
        page=browser.new_page(viewport={'width':1280,'height':900})
        page.set_default_timeout(8000)
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        login(page,live_server.url)
        page.goto(live_server.url+'/datasets/')
        fill_fetch(page,'top 100 market cap nasdaq tickers')
        page.get_by_role('button',name='Fetch & save dataset').click()
        expect(page.get_by_text('Enter 1–20 actual ticker symbols',exact=False)).to_be_visible()
        assert read_db(lambda:Dataset.objects.count())==0
        shot(page,'11-invalid-tickers')
        fill_fetch(page,'SPY','yfinance')
        page.get_by_role('button',name='Fetch & save dataset').click()
        chart_visible(page)
        expect(page.get_by_role('button',name='Create editable problem')).to_be_visible()
        page.get_by_role('button',name='Create editable problem').click()
        page.get_by_role('button',name='Solve & save experiment').click()
        expect(page.locator('#solver-status')).to_have_text('optimal')
        page.get_by_role('link',name='Evaluate fixed holdings').click()
        page.get_by_role('button',name='Evaluate validation & save').click()
        expect(page.get_by_role('heading',name='Validation evaluation',exact=True)).to_be_visible()
        shot(page,'12-single-asset-evaluation')
        # A signed problem remains freely editable: specify exact +120%/-20%.
        page.goto(live_server.url+'/datasets/')
        fill_fetch(page)
        page.get_by_role('button',name='Fetch & save dataset').click()
        page.get_by_label('Starting example').select_option('signed')
        page.get_by_role('button',name='Create editable problem').click()
        page.get_by_role('button',name='Use expression input',exact=True).click()
        page.locator('#id_constraints').fill('sum(w) == 1\nnorm(w, 1) <= 1.5\nw[0] == 1.2\nw[1] == -0.2')
        page.get_by_role('button',name='Solve & save experiment').click()
        expect(page.locator('#solver-status')).to_have_text('optimal')
        assert_rendering(page)
        page.get_by_role('link',name='Evaluate fixed holdings').click()
        page.get_by_label('Annual short borrow rate').fill('.05')
        page.get_by_role('button',name='Evaluate validation & save').click()
        expect(page.locator('#evaluation-status')).to_have_text('complete')
        result=read_db(lambda:Evaluation.objects.latest('created_at').result['portfolio'])
        assert result['gross_exposure']==pytest.approx(1.4)
        assert result['initial_weights'][1]==pytest.approx(-.2)
        assert result['borrow_cost']>0
        chart_visible(page)
        shot(page,'13-signed-portfolio-evaluation')
        # Simulate a provider access failure through the actual browser form.
        from core.parser import ProblemError
        fetcher.side_effect=ProblemError('Alpaca could not fetch daily prices. Check credentials/access or retry.')
        page.goto(live_server.url+'/datasets/')
        fill_fetch(page)
        page.get_by_role('button',name='Fetch & save dataset').click()
        expect(page.get_by_text('Alpaca could not fetch daily prices.',exact=False)).to_be_visible()
        shot(page,'14-provider-error')
        assert not errors,errors
        browser.close()
