"""Closed-form fixed-holdings accounting, including signed exposures and carry."""
import numpy as np
import pandas as pd
import pytest
from core.evaluation import fixed_holdings, evaluate_with_benchmark, metrics
from core.parser import ProblemError


def payload(a=110,b=90):
    values = [[100,100] for _ in range(101)]
    values[62:] = [[a,b] for _ in range(39)]
    return {'symbols':['A','B'],'dates':pd.date_range('2024-01-01',periods=101).strftime('%Y-%m-%d').tolist(),'values':values}


@pytest.mark.parametrize('weights,end',[([1,0],1.1),([.5,.5],1),([1.2,-.2],1.14),([.5,0],1.05),([2,0],1.2)])
def test_fixed_units_drift_and_signed_cash(weights,end):
    result=fixed_holdings(payload(),weights,options={'cost_bps':0,'borrow_rate':0})
    assert result['wealth'][0]==pytest.approx(1)
    assert result['wealth'][-1]==pytest.approx(end)
    assert result['gross_exposure']==sum(abs(w) for w in weights)
    assert result['net_exposure']==sum(weights)
    assert result['initial_cash_fraction']==1-sum(weights)
    assert result['adjusted_units']==pytest.approx(np.asarray(weights)/100)
    assert result['metrics']['total_return']==pytest.approx(end-1)
    assert len(result['wealth'])==20


def test_entry_fee_satisfies_exact_capital_identity():
    result=fixed_holdings(payload(100,100),[1.2,-.2],options={'cost_bps':100,'borrow_rate':0})
    after=1/(1+.01*1.4)
    assert result['wealth'][0]==pytest.approx(after)
    assert result['wealth'][-1]==pytest.approx(after)
    assert result['entry_cost']==pytest.approx(1-after)
    assert result['entry_cost']==pytest.approx(.01*np.abs(result['adjusted_units']).sum()*100)


def test_calendar_days_short_borrow_and_negative_cash_financing():
    data=payload(100,100)
    data['dates']=pd.bdate_range('2024-01-01',periods=101).strftime('%Y-%m-%d').tolist()
    result=fixed_holdings(data,[2,-.5],options={'cost_bps':0,'borrow_rate':.1,'financing_rate':.2})
    cash=-.5
    dates=pd.to_datetime(result['dates'])
    borrow=financing=0
    for i in range(1,len(dates)):
        days=(dates[i]-dates[i-1]).days
        b=.5*.1*days/365
        f=-cash*.2*days/365
        cash-=b+f
        borrow+=b; financing+=f
    assert result['borrow_cost']==pytest.approx(borrow)
    assert result['financing_cost']==pytest.approx(financing)
    assert result['ending_cash']==pytest.approx(cash)
    assert result['wealth'][-1]==pytest.approx(1.5+cash)


def test_entry_has_no_prior_interval_return_and_holdout_is_separate():
    data=payload()
    data['values'][61]=[500,50]
    result=fixed_holdings(data,[1,0],options={'cost_bps':0})
    assert result['returns'][0]==0
    assert result['wealth'][1]==pytest.approx(110/500)
    holdout=fixed_holdings(data,[1,0],'holdout',{'cost_bps':0})
    assert holdout['dates'][0]==data['dates'][81]
    assert holdout['wealth'][-1]==1


def test_bankruptcy_stops_without_clipping_wealth():
    result=fixed_holdings(payload(400,100),[-1,2],options={'cost_bps':0,'borrow_rate':0})
    assert result['status']=='nonpositive_equity'
    assert result['wealth'][-1]==pytest.approx(-2)
    assert len(result['wealth'])==2
    assert result['metrics']['cagr'] is None
    assert result['metrics']['max_drawdown']==pytest.approx(3)


def test_metrics_calendar_cagr_and_undefined_sharpe():
    dates=pd.to_datetime(['2023-01-01','2024-01-01'])
    result=metrics([0,.1],[1,1.1],dates)
    assert result['cagr']==pytest.approx(1.1**(365.25/365)-1)
    assert metrics([0,0],[1,1],dates)['sharpe'] is None
    extreme=metrics([0,1e10],[1,1e10],pd.to_datetime(['2024-01-01','2024-01-02']))
    assert extreme['cagr'] is None


def test_benchmark_uses_same_assumptions():
    result=evaluate_with_benchmark(payload(),[1.2,-.2],options={'cost_bps':10,'borrow_rate':.03})
    assert result['portfolio']['settings']==result['equal_weight']['settings']
    assert result['equal_weight']['initial_weights']==[.5,.5]


@pytest.mark.parametrize('options',[{'cost_bps':-1},{'borrow_rate':2},{'risk_free_rate':float('nan')},{'financing_rate':True}])
def test_invalid_assumptions(options):
    with pytest.raises(ProblemError): fixed_holdings(payload(),[.5,.5],options=options)


def test_wrong_vectors_or_window():
    for weights in ([1],[1,float('nan')],[[1,0]]):
        with pytest.raises(ProblemError): fixed_holdings(payload(),weights)
    with pytest.raises(ProblemError): fixed_holdings(payload(),[1,0],'train')
