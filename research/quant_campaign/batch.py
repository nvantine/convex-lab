"""One frozen batch per dataset permits fair final testing with one holdout opening."""
import json
from time import perf_counter
import numpy as np
import plotly.graph_objects as go
from core.data import split_windows
from core.rolling import portfolio_path
from core.research import ResearchResult
from strategies import target_weights


def run(context,params):
    payload={'symbols':list(context.symbols),'dates':context.prices.index.strftime('%Y-%m-%d').tolist(),
             'values':context.prices.to_numpy().tolist()}
    if context.window!='holdout': raise ValueError('This frozen batch is for final holdout only.')
    spans=split_windows(payload)
    rows=[]; details=[]; equity=go.Figure();drawdown=go.Figure()
    for candidate in params['candidates']:
        started=perf_counter();family=candidate['params']['family']
        label=candidate.get('label',family)
        try:
            options=candidate['options']
            path=portfolio_path(payload,np.zeros(len(context.symbols)),'holdout',options,
                strategy=lambda c,s:target_weights(c,candidate['params'],s),
                artifact_dir=context.artifact_dir,seed=42,maximum_refits=10000)
            m=path['metrics']
            reference=portfolio_path(payload,np.ones(len(context.symbols))/len(context.symbols),'holdout',
                {**options,'mode':'fixed'},stop_after=len(path['wealth']))
            excess=np.asarray(path['returns'])-np.asarray(reference['returns'])
            # Circular 21-observation blocks preserve some serial dependence.
            count=len(excess);block=21;means=[]
            for _ in range(1000):
                starts=context.rng.integers(0,count,size=int(np.ceil(count/block)))
                indices=np.concatenate([(start+np.arange(block))%count for start in starts])[:count]
                means.append(float(excess[indices].mean()*252))
            interval=np.quantile(means,[.025,.975]).tolist()
            rows.append([label,path['status'],m['total_return'],m['cagr'],m['volatility'],m['sharpe'],m['max_drawdown'],m['turnover'],len(path['trades']),float(excess.mean()*252),interval,perf_counter()-started])
            equity.add_trace(go.Scatter(x=path['dates'],y=path['wealth'],name=label))
            drawdown.add_trace(go.Scatter(x=path['dates'],y=path['drawdown'],name=label))
            details.append({'label':label,'configuration':candidate,'result':path,'equal_weight':reference,
                'annual_mean_excess':float(excess.mean()*252),'block_interval_95':interval})
        except Exception as error:
            rows.append([label,'failed',None,None,None,None,None,None,None,None,None,perf_counter()-started])
            details.append({'label':label,'configuration':candidate,'error':f'{type(error).__name__}: {error}'})
    if 'SPY' in context.symbols:
        weights=np.zeros(len(context.symbols));weights[context.symbols.index('SPY')]=1
        spy=portfolio_path(payload,weights,'holdout',{'mode':'fixed','frequency':'hold','cost_bps':10})
        equity.add_trace(go.Scatter(x=spy['dates'],y=spy['wealth'],name='SPY buy-and-hold',line={'dash':'dash'}))
        drawdown.add_trace(go.Scatter(x=spy['dates'],y=spy['drawdown'],name='SPY buy-and-hold',line={'dash':'dash'}))
        details.append({'label':'SPY buy-and-hold','result':spy})
    (context.artifact_dir/'holdout.json').write_text(json.dumps(details,allow_nan=False))
    for figure,title in ((equity,'Frozen final holdout · equity'),(drawdown,'Frozen final holdout · drawdown')):
        figure.update_layout(title=title,template='plotly_white',height=600,legend={'orientation':'h'},margin={'b':150})
    return ResearchResult(metrics={'strategies_attempted':{'value':len(rows),'unit':'count'},
        'strategies_completed':{'value':sum(r[1]=='complete' for r in rows),'unit':'count'}},
        text='All configurations were frozen before the final opening. No retuning after final results. Each strategy is compared to equal weights with the same costs and schedule. Excess is annualized arithmetic mean return, not CAGR. Circular 21-day block bootstrap intervals use 1,000 resamples and are exploratory, not adjusted for multiple comparisons. Adjusted prices are proxies, not executable prices. Current-symbol universes introduce survivorship/selection bias.',
        tables=[{'title':'Final holdout comparison','columns':['Strategy','Status','Return fraction','CAGR','Volatility','Sharpe','Max drawdown','Turnover','Trades','Annual mean excess','95% block interval','Seconds'],'rows':rows}],
        charts=[{'figure':equity.to_plotly_json()},{'figure':drawdown.to_plotly_json()}],artifacts=['holdout.json'])
