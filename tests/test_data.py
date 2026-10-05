"""Synthetic prices only; future values must never leak into training estimates."""
from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from sklearn.covariance import LedoitWolf
from core.data import aligned_prices, estimate_training, problem_from_training, split_windows, estimates_edited, PORTFOLIO_PRESETS
from core.parser import ProblemError, build_problem
from core.solve import solve


def synthetic_frame(symbols=('SPY','AGG'),count=301):
    rng = np.random.default_rng(42)
    returns = rng.normal(.0003,.008,size=(count-1,len(symbols)))
    values = np.vstack([np.ones(len(symbols)),np.cumprod(1+returns,axis=0)])*100
    return pd.DataFrame(values,index=pd.bdate_range('2023-01-02',periods=count),columns=symbols)


@pytest.fixture
def prices():
    return aligned_prices(synthetic_frame(),['SPY','AGG'])[0]


def test_chronological_disjoint_return_windows(prices):
    spans = split_windows(prices)
    assert [(s['start'],s['end'],s['count']) for s in spans.values()] == [(0,180,180),(180,240,60),(240,300,60)]
    assert spans['validation']['previous_close'] == spans['train']['last']
    assert spans['validation']['first'] == prices['dates'][181]
    assert spans['holdout']['previous_close'] == spans['validation']['last']


@pytest.mark.parametrize('estimator',['sample','ledoit-wolf'])
def test_estimates_use_training_only(prices,estimator):
    before = estimate_training(prices,estimator)
    changed = deepcopy(prices)
    changed['values'][181:] = (np.asarray(changed['values'][181:])*[500,.002]).tolist()
    assert estimate_training(changed,estimator) == before
    assert before['observations']==180
    matrix = np.asarray(before['Sigma'])
    assert np.linalg.eigvalsh(matrix).min()>=-1e-14
    scenarios = np.asarray(before['R'])
    expected = np.cov(scenarios,rowvar=False,ddof=1) if estimator=='sample' else LedoitWolf(store_precision=False).fit(scenarios).covariance_
    np.testing.assert_allclose(matrix,expected)
    np.testing.assert_allclose(before['mu'],scenarios.mean(axis=0))


def test_lookback_and_one_asset_covariance():
    payload,_ = aligned_prices(synthetic_frame(('SPY',)),['SPY'])
    for method in ('sample','ledoit-wolf'):
        estimate = estimate_training(payload,method,20)
        assert np.asarray(estimate['Sigma']).shape==(1,1)
        assert len(estimate['R'])==20
    for bad in (1,181,2.5,True):
        with pytest.raises(ProblemError,match='lookback'):
            estimate_training(payload,lookback=bad)
    with pytest.raises(ProblemError):
        estimate_training(payload,'other')


@pytest.mark.parametrize('preset',PORTFOLIO_PRESETS)
def test_imports_are_ordinary_editable_convex_specs(prices,preset):
    spec,estimate,digest = problem_from_training(prices,preset,lookback=40)
    assert estimate['observations']==40
    assert build_problem(spec).problem.is_dcp()
    assert next(v for v in spec['variables'] if v['name']=='w')['shape']==[2]
    spec['data']={'estimates_digest':digest}
    assert estimates_edited(spec) is False
    if 'objective' in spec:
        assert solve(build_problem(spec))['verified_optimal']
    if spec['parameters']:
        spec['parameters'][0]['value'] = 1
        assert estimates_edited(spec) is True


def test_boundary_alignment_without_inventing_prices():
    frame = synthetic_frame()
    frame.loc[frame.index[:3],'SPY']=np.nan
    frame.loc[frame.index[-2:],'AGG']=np.nan
    payload,meta = aligned_prices(frame,['SPY','AGG'])
    assert len(payload['dates'])==296
    assert meta['trimmed_dates']==5
    assert meta['coverage'][0]['observations']==298
    frame.loc[frame.index[50],'SPY']=np.nan
    with pytest.raises(ProblemError,match='inside'):
        aligned_prices(frame,['SPY','AGG'])


def test_provenance_ignores_equivalent_number_formatting_order_and_labels(prices):
    spec,_,digest=problem_from_training(prices,'cvar')
    spec['data']={'estimates_digest':digest}
    spec['parameters'].reverse()
    for p in spec['parameters']:
        p['meaning']='An edited description'
        if p['name']=='scenario_count': p['value']=float(p['value'])
    assert estimates_edited(spec) is False
    spec['parameters'].append({'name':'extra','value':1})
    assert estimates_edited(spec) is False
    spec['parameters']=[p for p in spec['parameters'] if p['name']!='R']
    assert estimates_edited(spec) is True


def test_negative_zero_is_equivalent_to_javascript_zero():
    from core.data import estimates_fingerprint
    assert estimates_fingerprint([{'name':'Sigma','value':[[.01,-0.],[0.,.02]]}])==estimates_fingerprint([{'name':'Sigma','value':[[.01,0],[0,.02]]}])


@pytest.mark.parametrize('bad',['missing','zero','infinite','duplicate','short','strings','dates'])
def test_bad_history_is_a_friendly_error(bad):
    frame=synthetic_frame()
    if bad=='missing': frame['AGG']=np.nan
    if bad=='zero': frame.iloc[5,0]=0
    if bad=='infinite': frame.iloc[5,0]=np.inf
    if bad=='duplicate': frame.index=[frame.index[0]]*len(frame)
    if bad=='short': frame=frame.iloc[:20]
    if bad=='strings': frame=frame.astype(str); frame.iloc[5,0]='bad'
    if bad=='dates': frame.index=['bad']*len(frame)
    with pytest.raises(ProblemError): aligned_prices(frame,['SPY','AGG'])


def test_no_django_dependency():
    from pathlib import Path
    for name in ('data','evaluation','providers'):
        assert 'from django' not in Path(f'core/{name}.py').read_text()
