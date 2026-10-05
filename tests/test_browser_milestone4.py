"""Actual DOM batches, rolling math, comparison zoom, and mobile rendering."""
from pathlib import Path
from time import sleep
from unittest.mock import Mock
import pytest
from playwright.sync_api import sync_playwright,expect
from lab import data_views
from lab.models import FetchRequest,Evaluation
from core.parser import ProblemError
from test_browser import browser_user,login,launch_options,assert_rendering
from test_browser_data import fill_fetch,chart_visible,read_db
from test_data import synthetic_frame

pytestmark=[pytest.mark.browser,pytest.mark.django_db(transaction=True)]
SHOTS=Path('screenshots/milestone-4')


def shot(page,name):
    SHOTS.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(SHOTS/f'{name}.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')


@pytest.fixture
def batches(monkeypatch):
    def fake(source,symbols,start,end,seconds):
        sleep(.4)
        return synthetic_frame(tuple(symbols)),{'provider':source,'feed':'iex','adjustment':'all','library_version':'test'}
    mock=Mock(side_effect=fake);monkeypatch.setattr(data_views,'fetch_prices',mock)
    return mock


def test_batches_pause_resume_rolling_and_comparisons(live_server,browser_user,batches):
    with sync_playwright() as p:
        browser=p.chromium.launch(**launch_options());page=browser.new_page(viewport={'width':1280,'height':900})
        page.set_default_timeout(10000)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('console',lambda msg:errors.append(msg.text) if msg.type=='error' else None)
        login(page,live_server.url);page.goto(live_server.url+'/datasets/')
        fill_fetch(page,','.join(f'A{i}' for i in range(12)))
        shot(page,'01-batch-fetch-form')
        page.get_by_role('button',name='Fetch & save dataset').click()
        page.get_by_role('button',name='Pause after this batch').click()
        expect(page.locator('#fetch-resume')).to_be_enabled()
        assert read_db(lambda:len(FetchRequest.objects.get().series)) in (5,10)
        shot(page,'02-paused-progress')
        progress_url=page.url
        page.goto(live_server.url+'/datasets/')
        page.goto(progress_url)
        expect(page.get_by_role('heading',name='Browser market history',exact=True)).to_be_visible()
        chart_visible(page);shot(page,'03-completed-dataset')
        assert batches.call_count==3 and all(len(c.args[1])<=5 for c in batches.call_args_list)
        page.get_by_role('button',name='Create editable problem').click()
        page.get_by_role('button',name='Solve & save experiment').click()
        page.get_by_role('link',name='Evaluate historical portfolio').click()
        expect(page.get_by_label('Rebalance policy')).to_have_value('rolling')
        page.get_by_label('Rolling lookback (past return observations)').fill('30')
        page.get_by_label('Rebalance frequency').select_option('weekly')
        shot(page,'04-rolling-settings')
        page.get_by_role('button',name='Evaluate validation & save').click()
        expect(page.locator('#evaluation-status')).to_have_text('complete')
        chart_visible(page);shot(page,'05-rolling-trade-ledger')
        page.get_by_role('link',name='Inspect rolling solve 0',exact=False).click()
        assert_rendering(page);shot(page,'06-refit-math-and-duals')
        page.get_by_role('link',name='Return to evaluation').click()
        page.get_by_role('link',name='Evaluate with other validation assumptions').click()
        page.get_by_label('Rebalance policy').select_option('fixed')
        page.get_by_label('Rebalance frequency').select_option('monthly')
        page.get_by_label('Trading cost').fill('20')
        page.get_by_role('button',name='Evaluate validation & save').click()
        page.get_by_role('link',name='Compare',exact=True).click()
        boxes=page.locator('input[name=evaluation]')
        expect(boxes).to_have_count(2)
        boxes.nth(0).check();boxes.nth(1).check()
        page.get_by_role('button',name='Compare selected').click()
        expect(page.get_by_text('Different assumptions:',exact=False)).to_be_visible()
        chart_visible(page);shot(page,'07-comparison')
        page.evaluate("Plotly.relayout(document.querySelector('#compare-history'), {'xaxis2.range':['2023-09-20','2023-10-20']})")
        assert page.evaluate("document.querySelector('#compare-history')._fullLayout.xaxis.range.join() === document.querySelector('#compare-history')._fullLayout.xaxis2.range.join()")
        shot(page,'08-synchronized-comparison-zoom')
        page.get_by_role('button',name='Expand chart').click()
        expect(page.locator('#expanded-chart .main-svg').first).to_be_visible()
        assert page.evaluate("document.querySelector('#expanded-chart')._fullLayout.xaxis2.range.join() === document.querySelector('#compare-history')._fullLayout.xaxis2.range.join()")
        shot(page,'09-expanded-comparison')
        page.get_by_role('button',name='Close chart',exact=True).click()
        page.set_viewport_size({'width':390,'height':844});chart_visible(page);shot(page,'10-mobile-comparison')
        page.locator('.table-scroll').first.evaluate('(element) => element.scrollLeft = element.scrollWidth')
        shot(page,'14-mobile-comparison-scrolled')
        assert not errors,errors
        assert read_db(lambda:Evaluation.objects.filter(window='holdout').count())==0
        browser.close()


def test_partial_provider_errors_are_visible_and_can_be_retried(live_server,browser_user,batches):
    original=batches.side_effect
    def missing(*args):
        frame,meta=original(*args);return frame.drop(columns='AGG'),meta
    batches.side_effect=missing
    with sync_playwright() as p:
        browser=p.chromium.launch(**launch_options());page=browser.new_page(viewport={'width':1280,'height':900})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        login(page,live_server.url);page.goto(live_server.url+'/datasets/');fill_fetch(page)
        page.get_by_role('button',name='Fetch & save dataset').click()
        expect(page.get_by_role('button',name='Resume fetching')).to_be_enabled()
        expect(page.locator('#fetch-errors')).to_contain_text('AGG')
        expect(page.locator('#fetch-meter')).to_have_attribute('value','1')
        shot(page,'11-partial-provider-error')
        batches.side_effect=original
        page.get_by_role('button',name='Retry failed symbols one at a time').click()
        expect(page.get_by_role('heading',name='Browser market history',exact=True)).to_be_visible()
        assert batches.call_args.args[1]==['AGG']
        chart_visible(page);shot(page,'12-recovered-dataset')
        page.get_by_role('button',name='Create editable problem').click()
        page.get_by_role('button',name='Solve & save experiment').click()
        page.get_by_role('link',name='Evaluate historical portfolio').click()
        page.get_by_label('Rolling lookback (past return observations)').fill('999')
        page.get_by_role('button',name='Evaluate validation & save').click()
        expect(page.get_by_text('Lookback must be between',exact=False)).to_be_visible()
        shot(page,'13-rolling-input-error')
        assert not errors
        browser.close()
