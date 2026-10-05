"""Known-answer accounting and causal refits; no Django and no vendor network."""
from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from core import rolling
from core.data import problem_from_training
from core.evaluation import fixed_holdings
from core.parser import Limits, ProblemError, build_problem
from test_data import prices
from test_evaluation import payload


def policy(**kwargs):
    return dict(mode='rolling',frequency='monthly',lookback=30,estimator='sample',
                covariance_parameter='Sigma',cost_bps=10,**kwargs)


@pytest.mark.parametrize('weights',[[.5,.5],[1.2,-.2],[2,-.5]])
def test_hold_policy_matches_original_closed_form(weights):
    data=payload(100,100);options=dict(cost_bps=100,borrow_rate=.1,financing_rate=.2)
    old=fixed_holdings(data,weights,options=options)
    new=rolling.portfolio_path(data,weights,options=options)
    for key in ('wealth','returns','borrow_cost','financing_cost','ending_cash','entry_cost'):
        np.testing.assert_allclose(new[key],old[key],atol=1e-14)
    assert len(new['trades'])==1


@pytest.mark.parametrize('weights,current,cost',[
    ([.5,.5],[0,0],.01),([1.2,-.2],[.7,.3],.001),([2,-1],[1,-.2],.1),
    ([20,-19],[.5,.5],.1),([0,0],[.5,.5],.01),([.5,.5],[.5,.5],.1)])
def test_every_rebalance_satisfies_exact_self_financing(weights,current,cost):
    after,deltas=rolling.trade_to_weights(1,np.array(current),weights,cost)
    assert after+cost*np.abs(deltas).sum()==pytest.approx(1)
    np.testing.assert_allclose(np.array(current)+deltas,after*np.array(weights))


def test_infeasible_trading_costs():
    with pytest.raises(ProblemError): rolling.trade_to_weights(1,np.array([100,-99]),[0,0],.1)


@pytest.mark.parametrize('frequency,count',[('hold',1),('daily',9),('weekly',3),('monthly',2)])
def test_calendar_schedules_skip_final_mark(frequency,count):
    dates=pd.bdate_range('2024-01-26',periods=10)
    indices=rolling.rebalance_indices(dates,frequency)
    assert len(indices)==count and 0 in indices and 9 not in indices


def test_fixed_rebalances_have_trades_and_drifting_holdings(prices):
    result=rolling.portfolio_path(prices,[1.2,-.2],options=dict(mode='fixed',frequency='weekly',cost_bps=15))
    assert len(result['trades'])>5 and result['trading_cost']>result['entry_cost']
    assert result['borrow_cost']>0
    for trade in result['trades']:
        assert trade['weights']==[1.2,-.2]
        assert trade['pre_equity']==pytest.approx(trade['post_equity']+trade['cost'])
        assert trade['cost']==pytest.approx(.0015*np.abs(trade['dollar_trades']).sum())


def test_future_prices_do_not_change_first_refit_or_previous_weights(prices):
    spec,_,_=problem_from_training(prices,'min-variance')
    first=rolling.portfolio_path(prices,[.5,.5],options=policy(),spec=spec)
    changed=deepcopy(prices)
    changed['values'][181:]=(np.array(changed['values'][181:])*[10,.2]).tolist()
    other=rolling.portfolio_path(changed,[.5,.5],options=policy(),spec=spec)
    assert first['refits'][0]['parameter_digest']==other['refits'][0]['parameter_digest']
    np.testing.assert_allclose(first['trades'][0]['weights'],other['trades'][0]['weights'])
    for trade,record in zip(first['trades'],first['refits']):
        assert record['last_return']==trade['signal_date']<trade['date']
        weights=trade['weights']
        assert sum(weights)==pytest.approx(1,abs=1e-7) and min(weights)>=-1e-7
    frame=pd.DataFrame(prices['values']).iloc[150:181]
    covariance=np.cov(frame.pct_change().iloc[1:].to_numpy(),rowvar=False,ddof=1)
    inv=np.linalg.solve(covariance,np.ones(2));expected=inv/inv.sum()
    np.testing.assert_allclose(first['trades'][0]['weights'],expected,atol=1e-4)


def test_manual_parameters_remain_fixed_and_cvar_auxiliary_resizes(prices):
    spec,_,_=problem_from_training(prices,'cvar',lookback=40)
    options=dict(lookback=30,returns_parameter='R',scenario_count_parameter='scenario_count',scenario_variable='u')
    changed,evidence=rolling.refit_spec(spec,prices,180,[.4,.6],options)
    assert next(v for v in changed['variables'] if v['name']=='u')['shape']==[30]
    assert next(p for p in changed['parameters'] if p['name']=='R')['value']!=next(p for p in spec['parameters'] if p['name']=='R')['value']
    assert build_problem(changed).problem.is_dcp()
    for parameter in spec['parameters']:
        if parameter['name'] not in ('R','scenario_count'):
            assert parameter==next(p for p in changed['parameters'] if p['name']==parameter['name'])


def test_duplicate_bindings_and_unmapped_policy_are_clear(prices):
    spec,_,_=problem_from_training(prices,'min-variance')
    for options in ({'lookback':181,'covariance_parameter':'Sigma'}, {},
                    {'lookback':20,'covariance_parameter':'Sigma','mean_parameter':'Sigma'}):
        with pytest.raises(ProblemError): rolling.refit_spec(spec,prices,180,[0,0],options)


def test_late_solver_failure_keeps_completed_prefix_and_same_benchmark_schedule(prices,monkeypatch):
    spec,_,_=problem_from_training(prices,'min-variance')
    real=rolling.solve;count=0
    def fail_late(*args,**kwargs):
        nonlocal count
        count+=1
        if count==4: raise ProblemError('Test numerical failure')
        return real(*args,**kwargs)
    monkeypatch.setattr(rolling,'solve',fail_late)
    result=rolling.evaluate_portfolios(prices,[.5,.5],'validation',
        dict(mode='rolling',frequency='daily',lookback=30,covariance_parameter='Sigma'),spec,'w',Limits())
    chosen,benchmark=result['portfolio'],result['equal_weight']
    assert chosen['status']=='solver_failed' and len(chosen['wealth'])==3
    assert chosen['dates']==benchmark['dates']
    assert len(chosen['trades'])==len(benchmark['trades'])==3
    assert chosen['trading_cost']==pytest.approx(sum(t['cost'] for t in chosen['trades']))


def test_first_failure_and_refit_limit_do_not_save_partial_path(prices,monkeypatch):
    spec,_,_=problem_from_training(prices,'min-variance')
    with pytest.raises(ProblemError,match='request limit'):
        rolling.portfolio_path(prices,[.5,.5],options=policy(),spec=spec,maximum_refits=1)
    monkeypatch.setattr(rolling,'solve',lambda *a,**kw:{'verified_optimal':False,'status':'infeasible','variables':{}})
    with pytest.raises(ProblemError,match='first rolling problem'):
        rolling.portfolio_path(prices,[.5,.5],options=policy(),spec=spec)


def test_budget_is_explicit_partial_not_silent_success(prices,monkeypatch):
    spec,_,_=problem_from_training(prices,'min-variance')
    real=rolling.solve;clock=[0.]
    monkeypatch.setattr(rolling,'monotonic',lambda:clock[0])
    def elapsed(*a,**kw):
        result=real(*a,**kw);clock[0]+=1;return result
    monkeypatch.setattr(rolling,'solve',elapsed)
    result=rolling.portfolio_path(prices,[.5,.5],options={**policy(),'frequency':'daily'},spec=spec,seconds=2)
    assert result['status']=='budget_exhausted' and len(result['wealth'])==2
    assert result['warnings']


def test_prior_weight_binding_uses_signal_close_before_current_return(prices):
    spec,_,_=problem_from_training(prices,'min-variance')
    spec['parameters'].append({'name':'prior','value':[0,0]})
    result=rolling.portfolio_path(prices,[.5,.5],options={**policy(),'previous_weights_parameter':'prior'},spec=spec)
    all_prices=np.array(prices['values'])
    for i,record in enumerate(result['refits']):
        if i==0: assert record['previous_weights']==[0,0];continue
        trade=result['trades'][i-1]
        notional=np.array(trade['units'])*all_prices[record['signal_index']]
        close_index=result['dates'].index(record['last_return'])
        np.testing.assert_allclose(record['previous_weights'],notional/result['wealth'][close_index])


def test_failed_late_rebalance_rolls_back_unrecorded_carry(prices,monkeypatch):
    real=rolling.trade_to_weights;count=0
    def fail(*args):
        nonlocal count
        count+=1
        if count==3: raise ProblemError('Cost failure')
        return real(*args)
    monkeypatch.setattr(rolling,'trade_to_weights',fail)
    options=dict(frequency='daily',cost_bps=10,borrow_rate=.1,financing_rate=.2)
    failed=rolling.portfolio_path(prices,[2,-.5],options=options)
    monkeypatch.setattr(rolling,'trade_to_weights',real)
    prefix=rolling.portfolio_path(prices,[2,-.5],options=options,stop_after=len(failed['wealth']))
    assert failed['status']=='trading_cost_failure'
    for key in ('wealth','borrow_cost','financing_cost','ending_cash'):
        np.testing.assert_allclose(failed[key],prefix[key])


def test_gross_fee_equation_selects_largest_feasible_root():
    # Existing signed notionals can create two roots when c*sum(abs(w))>1.
    # f(0)>0, f(.45)<0, f(1)>0: the positive larger root is intended.
    after,deltas=rolling.trade_to_weights(1,np.array([10,-9]),[20,-19],.1)
    assert after==pytest.approx(2.9/4.9)
    assert after+.1*np.abs(deltas).sum()==pytest.approx(1)
