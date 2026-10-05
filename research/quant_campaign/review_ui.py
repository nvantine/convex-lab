"""Read-only server-rendered report review; no passwords or browser login changes.

Django RequestFactory calls the scoped GET views as the configured owner.
Chromium renders captured HTML with local assets. Separate app Playwright tests
cover live-server routing, authentication, and actions.
"""
import os
os.environ['OPENBLAS_NUM_THREADS']='1'
os.environ['OMP_NUM_THREADS']='1'
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
import json
import resource
from pathlib import Path
from time import perf_counter
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.urls import resolve
from playwright.sync_api import sync_playwright
from finalize import read_cli
from run_campaign import ROOT,OUT,data


def main():
    user=get_user_model().objects.get(username=read_cli(['whoami'])['owner'])
    summary=json.loads((OUT/'analysis-summary.json').read_text())
    final=data(json.loads((OUT/'final-154.json').read_text()))
    native=data(json.loads((OUT/'native-PSD-solve-500-CLARABEL.json').read_text()))
    targets=[('summary','/research/'+summary['summary_id']+'/'),
             ('conclusions','/research/'+summary['conclusions_id']+'/'),
             ('final-154','/research/'+final['id']+'/'),
             ('native-500','/results/'+native['id']+'/'),('ledger','/research/')]
    output=OUT/'rendered';output.mkdir(exist_ok=True)
    shots=ROOT/'screenshots/quant-campaign';shots.mkdir(exist_ok=True)
    records=[];rendered=[]
    # Render before Playwright starts its event loop: Django sync ORM access
    # correctly refuses to run inside that async context.
    for label,path in targets:
        started=perf_counter();request=RequestFactory().get(path,HTTP_HOST='localhost')
        request.user=user;request.session={}
        match=resolve(path);response=match.func(request,**match.kwargs)
        html=response.content.decode().replace('/static/',(ROOT/'lab/static').as_uri()+'/')
        local=output/(label+'.html');local.write_text(html)
        rendered.append((label,path,local,response.status_code,len(response.content),perf_counter()-started,
                         resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    with sync_playwright() as p:
        browser=p.chromium.launch(args=['--allow-file-access-from-files'])
        page=browser.new_page(viewport={'width':1280,'height':900})
        for label,path,local,status,html_bytes,render_seconds,rss in rendered:
            started=perf_counter()
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(local.as_uri(),wait_until='load',timeout=60000)
            page.wait_for_function("[...document.querySelectorAll('.chart')].every(e=>e.querySelector('.main-svg'))",timeout=60000)
            page.screenshot(path=str(shots/(label+'-desktop.png')))
            charts=page.locator('.chart')
            if charts.count():
                charts.first.scroll_into_view_if_needed();page.screenshot(path=str(shots/(label+'-chart.png')))
            desktop={'overflow':page.evaluate('document.documentElement.scrollWidth>innerWidth'),
                'math_errors':page.locator('.math-error,.katex-error').count(),'charts':charts.count()}
            page.set_viewport_size({'width':390,'height':844})
            page.wait_for_timeout(500)
            if charts.count():charts.first.scroll_into_view_if_needed()
            page.screenshot(path=str(shots/(label+'-mobile.png')))
            mobile={'overflow':page.evaluate('document.documentElement.scrollWidth>innerWidth'),
                    'oversized_charts':page.evaluate("[...document.querySelectorAll('.chart .main-svg')].filter(e=>Number(e.getAttribute('width'))>e.closest('.chart').clientWidth+1).length")}
            records.append({'page':label,'path':path,'http_status':status,'desktop':desktop,'mobile':mobile,
                            'errors':errors,'browser_seconds':perf_counter()-started,'html_bytes':html_bytes,
                            'render_seconds':render_seconds,'process_peak_rss_kib':rss})
            print(label,records[-1],flush=True)
            page.set_viewport_size({'width':1280,'height':900})
        browser.close()
    (OUT/'ui-review.json').write_text(json.dumps(records,indent=2))


if __name__=='__main__':main()
