"""Known answers and timing/feasibility checks, saved by the research CLI."""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from core.research import StrategyContext
from strategies import target_weights, FAMILIES


def context(n=5,rows=127):
    rng=np.random.default_rng(123)
    returns=rng.normal(.0002,.01,size=(rows-1,n))
    prices=100*np.vstack([np.ones(n),np.cumprod(1+returns,axis=0)])
    symbols=tuple(f"A{i}" for i in range(n))
    frame=pd.DataFrame(prices,index=pd.bdate_range('2020-01-01',periods=rows),columns=symbols)
    return StrategyContext(frame,symbols,str(frame.index[-1].date()),dict.fromkeys(symbols,0.),rng,Path('.'))


@pytest.mark.parametrize('family',FAMILIES)
def test_families_are_finite_and_feasible(family):
    c=context(); result=target_weights(c,{'family':family},None)
    w=np.array(list(result.weights.values()))
    assert np.isfinite(w).all()
    if family=='neutral_reversion':
        assert abs(w.sum())<2e-5 and abs(w).sum()<=1.00002
    elif family=='trend_cash': assert 0<=w.sum()<=1
    else: assert w.sum()==pytest.approx(1,abs=2e-5)
    if family not in ('signed_momentum','neutral_reversion'): assert w.min()>=-2e-5


def test_two_asset_min_variance_closed_form():
    c=context(2,5)
    # Orthogonal centered returns create diag(0.0001333,0.0005333).
    r=np.array([[.01,.02],[-.01,.02],[.01,-.02],[-.01,-.02]])
    c.history.iloc[:]=100*np.vstack([np.ones(2),np.cumprod(1+r,axis=0)])
    out=target_weights(c,{'family':'min_variance','estimator':'sample','cap':1},None)
    assert list(out.weights.values())==pytest.approx([.8,.2],abs=2e-5)


def test_impossible_cap_is_not_silently_relaxed():
    with pytest.raises(ValueError,match='infeasible'):
        target_weights(context(),{'family':'min_variance','cap':.1},None)


def test_asset_permutation_equivariance():
    c=context(); first=target_weights(c,{'family':'min_variance'},None)
    c.symbols=tuple(reversed(c.symbols));c.history=c.history.loc[:,c.symbols]
    second=target_weights(c,{'family':'min_variance'},None)
    for name in c.symbols: assert first.weights[name]==pytest.approx(second.weights[name],abs=2e-5)


def test_final_batch_on_synthetic_prices(tmp_path):
    from batch import run
    from core.research import ResearchContext, result_payload
    c=context()
    result=run(ResearchContext(c.history,c.history.iloc[:76],c.symbols,'holdout',c.rng,tmp_path),
        {'candidates':[{'label':family,'params':{'family':family},
                       'options':{'mode':'rolling','frequency':'weekly','lookback':63,'cost_bps':10}}
                      for family in FAMILIES]})
    payload=result_payload(result)
    assert payload['metrics']['strategies_completed']['value']==len(FAMILIES)
    assert (tmp_path/'holdout.json').is_file()
    assert all(len(row)==12 for row in payload['tables'][0]['rows'])
