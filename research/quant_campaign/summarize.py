"""Turn retained CLI evidence into a reviewable website report and Markdown."""
import json
from pathlib import Path
import numpy as np
import plotly.graph_objects as go
from core.research import file_checksum
from finalize import read_cli
from run_campaign import ROOT,OUT,cli,data,FAMILIES


def main():
    frozen=json.loads((OUT/'frozen-final.json').read_text())
    all_rows=[];primary=[];observed=[];datasets=[];exposures=[];links=[];combined=[]
    for selection in frozen['selections']:
        key=selection['universe'];record=json.loads((OUT/f'final-{key}.json').read_text());run=data(record)
        evidence=read_cli(['runs','show',run['id']])
        item=next(a for a in evidence['artifacts'] if a['path']=='artifacts/holdout.json')
        artifact=ROOT/'.local/research'/run['id']/item['path']
        assert file_checksum(artifact)==item['sha256']
        details=json.loads(artifact.read_text())
        table=run['result']['tables'][0];rows=table['rows']
        for row in rows: all_rows.append([key,*row])
        champion=max(selection['candidates'],key=lambda c:c['score'])
        chosen=next(r for r in rows if r[0]==champion['label'])
        baseline=next(r for r in rows if r[0]=='equal')
        winner=max((r for r in rows if r[1]=='complete'),key=lambda r:r[5])
        spy=next(d['result']['metrics'] for d in details if d['label']=='SPY buy-and-hold')
        primary.append([key,champion['label'],champion['score'],chosen[3],chosen[5],chosen[6],baseline[3],spy['cagr']])
        observed.append([key,winner[0],winner[3],winner[5],winner[6],baseline[3],winner[10]])
        metadata=selection['metadata'];window=metadata['windows']['holdout']
        datasets.append([key,len(metadata['symbols']),metadata['provenance']['provider'],metadata['windows']['train']['previous_close'],window['first'],window['last'],window['count']])
        links.append([key,run['id'],run['url']])
        for detail in details:
            if detail['label']=='SPY buy-and-hold' or 'result' not in detail:continue
            path=detail['result'];trades=path['trades']
            avg=np.mean(np.array([t['weights'] for t in trades]),axis=0)
            top=np.argsort(-np.abs(avg))[:3]
            exposures.append([key,detail['label'],', '.join(f'{metadata["symbols"][i]} {avg[i]:.1%}' for i in top),
                              float(np.mean([sum(abs(w) for w in t['weights']) for t in trades])),path['borrow_cost'],path['financing_cost']])
    main_rows=[r for r in all_rows if r[0] in ('5','10','20','50','100','154')]
    family_stats=[]
    for family in FAMILIES:
        rows=[r for r in main_rows if r[1]==family]
        family_stats.append([family,float(np.median([r[4] for r in rows])),float(np.median([r[6] for r in rows])),
            sum(r[10]>0 for r in rows),sum(r[11][0]>0 for r in rows),len(rows)])
    figure=go.Figure()
    for key in ('5','10','20','50','100','154'):
        rows=[r for r in main_rows if r[0]==key]
        figure.add_trace(go.Bar(x=[r[1] for r in rows],y=[r[4] for r in rows],name=key+' assets'))
    figure.update_layout(title='Final CAGR · same one-year dates, differing universes/providers',yaxis={'title':'Annual return fraction','tickformat':'.0%'},template='plotly_white',height=600,margin={'b':180},barmode='group',legend={'orientation':'h'})
    sharpe=go.Figure()
    for key in ('5','10','20','50','100','154'):
        rows=[r for r in main_rows if r[0]==key]
        sharpe.add_trace(go.Scatter(x=[r[1] for r in rows],y=[r[6] for r in rows],mode='lines+markers',name=key+' assets'))
    sharpe.update_layout(title='Final Sharpe · descriptive comparison',template='plotly_white',height=600,margin={'b':180},legend={'orientation':'h'})
    costs=go.Figure()
    for key in ('5','154'):
        r=data(json.loads((OUT/f'costs-{key}.json').read_text()))['result']['tables'][0]['rows']
        for family in ('momentum','signed_momentum','neutral_reversion','turnover'):
            selected=sorted([row for row in r if row[3]['params.family']==family],key=lambda row:row[3]['options.cost_bps'])
            costs.add_trace(go.Scatter(x=[row[3]['options.cost_bps'] for row in selected],y=[row[4] for row in selected],name=key+' · '+family,mode='lines+markers'))
    costs.update_layout(title='Validation cost sensitivity · weekly, 63-day lookback',xaxis_title='Cost bps per traded notional',yaxis_title='Sharpe',template='plotly_white',height=600,margin={'b':140},legend={'orientation':'h'})
    interval_positive=sum(r[11][0]>0 for r in all_rows)
    text=(f'676 validation sweep trials: 664 completed candidates ranked, 12 deliberate infeasible cases excluded. '
        f'104 frozen final candidates completed across eight datasets. Selection used validation only; freeze SHA256 {(OUT/"frozen-final.sha256").read_text().strip()}. '
        'The primary table shows the validation champion, not the best strategy retrospectively selected on final data. '
        'All models, including disappointing models, remain in the full comparison. Main universes share 2025-10-03 to 2026-10-02 final dates; long/new-listing windows differ and are not pooled. '
        f'{interval_positive}/104 exploratory 21-day block-bootstrap intervals for annual mean excess over matched equal weights had a positive lower endpoint. These are NOT adjusted for multiple comparisons and overlapping universes are not independent. '
        'Costs were 10bps, annual short borrow 3%, negative-cash financing 5%, cash yield/risk-free assumption zero. No account execution, margin/locate simulation, options, or proof of future profitability. '
        'Smaller datasets use adjusted IEX; larger datasets use adjusted Yahoo because IEX coverage blocked saving. Current symbols introduce survivorship/selection bias. '
        'Numerical stress solved 1000-variable structured synthetic QPs and 500-asset native dense-matrix inputs; 154 assets is demonstrated real-data capacity, not a hard hardware limit. '
        'Confirmed problems: portfolio tests require unavailable dataset input, invalid fetch exit code, unlocalized data gaps, provider diagnostics, SCS accuracy labeling, repeated native ARPACK failures/partial-evidence loss, discovery/navigation limits, and a port-dependent test. App code was not changed. '
        'Regression: 319 passed, one test failed because it splits a configured 8020 URL on literal 8000; source model suites passed 16 and 17 tests. See the reproducible issue register in research/quant_campaign/ISSUES.md.')
    tables=[{'title':'Primary outcome · validation-selected champion','columns':['Universe','Chosen family','Validation Sharpe','Final CAGR','Final Sharpe','Final drawdown','Equal-weight CAGR','SPY CAGR'],'rows':primary},
        {'title':'Observed final Sharpe leaders · descriptive, not a new selection','columns':['Universe','Family','CAGR','Sharpe','Drawdown','Equal-weight CAGR','95% mean-excess interval'],'rows':observed},
        {'title':'All frozen strategies','columns':['Universe',*table['columns']],'rows':all_rows},
        {'title':'Main-window family summaries · overlapping, nonindependent datasets','columns':['Family','Median CAGR','Median Sharpe','Positive mean excess','Positive lower interval','Universes'],'rows':family_stats},
        {'title':'Data windows and provider differences','columns':['Universe','Assets','Provider','First price','Final first','Final last','Final returns'],'rows':datasets},
        {'title':'Holdout trade-average exposures · not daily time averages','columns':['Universe','Family','Top mean signed weights','Mean gross','Borrow cost / initial equity','Financing cost / initial equity'],'rows':exposures},
        {'title':'Saved final runs','columns':['Universe','Run ID','Website URL'],'rows':links}]
    report={'text':text,'metrics':{'validation_trials':{'value':676,'unit':'count'},'final_candidates':{'value':104,'unit':'count'},'largest_real_universe':{'value':154,'unit':'count'}},
        'tables':tables,'charts':[{'figure':fig.to_plotly_json()} for fig in (figure,sharpe,costs)],
        'equations':[r'\min_w\ w^\top\hat\Sigma w',r'\max_w\ \hat\mu^\top w-\gamma w^\top\hat\Sigma w-\kappa\|w-w_{\rm prev}\|_1',r'\min_{w,z}\ z+\frac{1}{(1-\alpha)T}\sum_{t=1}^T(-r_t^\top w-z)_+']}
    params=OUT/'summary-params.json';params.write_text(json.dumps(report,allow_nan=False))
    revision=data(cli('register-summary',['strategies','register','research/quant_campaign','--entry-point','report.py:run','--interface','research','--name','Quant campaign · findings and all final strategies']))
    saved=data(cli('summary-report',['research','run',revision['id'],'--params','@'+str(params),'--timeout','120']))
    print('SUMMARY',saved['id'],saved['url'],flush=True)
    markdown=['# Quant CLI campaign · 2026-10-05','',text,'','## Validation-selected primary outcomes','',
        '| Universe | Selected family | Validation Sharpe | Final CAGR | Final Sharpe | Drawdown | Equal CAGR | SPY CAGR |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for key,family,v,c,s,d,e,spy in primary:
        markdown.append(f'| {key} | {family} | {v:.2f} | {c:.1%} | {s:.2f} | {d:.1%} | {e:.1%} | {spy:.1%} |')
    markdown+=['','## Family summaries for the six main universes','',
        '| Family | Median final CAGR | Median Sharpe | Positive mean excess | Positive exploratory lower interval |',
        '|---|---:|---:|---:|---:|']
    for family,c,s,p,l,n in family_stats:markdown.append(f'| {family} | {c:.1%} | {s:.2f} | {p}/{n} | {l}/{n} |')
    markdown+=['','## Review in the app','',f'- Summary: {saved["url"]}',*['- '+key+': '+url for key,run_id,url in links],
        '', '## Reproducibility','', '- [Issue register](ISSUES.md)', '- [Driver and universe](run_campaign.py)', '- [Policies](strategies.py)', '- [Selection and holdout protocol](finalize.py)',
        '- Private command JSON, freeze, artifacts, and raw evidence remain under .local and the owner database. Do not rerun final phases against an already-opened dataset.',
        '', '## Verified library references','', '- [CVXPY solver settings](https://www.cvxpy.org/tutorial/solvers/index.html)',
        '- [Ledoit–Wolf API](https://scikit-learn.org/stable/modules/generated/sklearn.covariance.LedoitWolf.html)',
        '- [Ridge API](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html)',
        '- [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbarsingle-1)']
    (ROOT/'research/quant_campaign/REPORT.md').write_text('\n'.join(markdown)+'\n')
    (OUT/'analysis-summary.json').write_text(json.dumps({'primary':primary,'observed':observed,'family_stats':family_stats,'exposures':exposures,'positive_intervals':interval_positive,'summary_id':saved['id'],'summary_url':saved['url']},indent=2))


if __name__=='__main__':main()
