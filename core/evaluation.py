"""Fixed holdings in adjusted-price units: no strategy refits, trades, or Django.

Weights may be signed; cash is 1-sum(w). Financing and borrow are explicit
simplified assumptions, not an executable margin model (Boyd §4.4.1).
"""
import numpy as np
from core.data import price_frame, split_windows
from core.parser import ProblemError


def evaluation_settings(options):
    defaults = {'cost_bps':10., 'borrow_rate':.03, 'financing_rate':0., 'risk_free_rate':0.}
    result = {**defaults, **options}
    for name in defaults:
        value = result[name]
        maximum = 1000 if name == 'cost_bps' else 1
        if type(value) not in (float,int) or not np.isfinite(value) or not 0 <= value <= maximum:
            raise ProblemError(f'{name} must be a finite number between 0 and {maximum}. Rates are annual fractions.')
    return result


def metrics(returns, wealth, dates, risk_free_rate=0):
    values = np.asarray(returns)
    path = np.r_[1., wealth]
    std = float(np.std(values, ddof=1)) if len(values)>1 else 0.
    years = (dates[-1]-dates[0]).days/365.25
    end = float(path[-1])
    with np.errstate(over='ignore', invalid='ignore'):
        cagr = np.expm1(np.log(end)/years) if end>0 and years>0 else None
    return {'total_return':end-1, 'cagr':float(cagr) if cagr is not None and np.isfinite(cagr) else None,
            'volatility':std*np.sqrt(252),
            'sharpe':float((values.mean()-((1+risk_free_rate)**(1/252)-1))/std*np.sqrt(252)) if std>1e-15 else None,
            'max_drawdown':float(np.max(1-path/np.maximum.accumulate(path)))}


def fixed_holdings(payload, weights, window='validation', options=None):
    """Enter at first evaluation close; subsequent closes earn returns. No rebalances.

Entry fee: V_after + c*G*V_after = 1. Therefore V_after=1/(1+c*G).
This accounts for buys AND shorts without charging an approximate fee on wealth.
Cash and signed adjusted-price units then evolve with calendar-day carry.
"""
    if window not in ('validation','holdout'):
        raise ProblemError('Evaluate validation or an explicitly confirmed final holdout.')
    settings = evaluation_settings(options or {})
    w = np.asarray(weights, dtype=float)
    if w.shape != (len(payload['symbols']),) or not np.isfinite(w).all():
        raise ProblemError('Choose a finite weight vector with one entry per dataset symbol, in the displayed order.')
    span = split_windows(payload)[window]
    prices = price_frame(payload).iloc[span['start']+1:span['end']+1]
    # Weights are proportions of POST-cost equity. Prices are adjusted proxies,
    # so these units represent a total-return approximation, not raw share counts.
    invested = 1/(1+settings['cost_bps']/10000*np.abs(w).sum())
    units = invested*w/prices.iloc[0].to_numpy()
    cash = invested*(1-w.sum())
    initial_cost = float(1-invested)
    equity, returns, borrow_costs, financing_costs = [], [], [], []
    previous_equity = 1.
    status = 'complete'
    for i, (date, row) in enumerate(prices.iterrows()):
        borrow = financing = 0.
        if i:
            days = (date-prices.index[i-1]).days
            previous_notional = units*prices.iloc[i-1].to_numpy()
            borrow = float(-np.minimum(previous_notional,0).sum()*settings['borrow_rate']*days/365)
            financing = float(max(-cash,0)*settings['financing_rate']*days/365)
            cash -= borrow+financing
        wealth = float(units @ row.to_numpy()+cash)
        if not np.isfinite(wealth):
            raise ProblemError('The chosen exposure produced nonfinite equity; reduce exposure or change the window.')
        returns.append(wealth/previous_equity-1)
        equity.append(wealth)
        borrow_costs.append(borrow)
        financing_costs.append(financing)
        if wealth <= 0:
            status = 'nonpositive_equity'
            break
        previous_equity = wealth
    dates = prices.index[:len(equity)]
    summary = metrics(returns, equity, dates, settings['risk_free_rate'])
    warnings = []
    if len(equity)<60:
        warnings.append('Fewer than 60 evaluation observations: annualized metrics can be unstable.')
    if status != 'complete':
        warnings.append('Equity became nonpositive. Evaluation stopped; CAGR is unavailable.')
    return {'status':status, 'dates':dates.strftime('%Y-%m-%d').tolist(), 'wealth':equity, 'returns':returns,
            'drawdown':(np.r_[1.,equity][1:]/np.maximum.accumulate(np.r_[1.,equity])[1:]-1).tolist(),
            'metrics':summary, 'settings':settings, 'initial_weights':w.tolist(),
            'net_exposure':float(w.sum()), 'gross_exposure':float(np.abs(w).sum()),
            'initial_cash_fraction':float(1-w.sum()), 'adjusted_units':units.tolist(),
            'entry_cost':initial_cost, 'borrow_cost':sum(borrow_costs), 'financing_cost':sum(financing_costs),
            'ending_cash':float(cash), 'window':span, 'warnings':warnings,
            'timing':'Enter at the first evaluation close. Fixed adjusted-price units earn subsequent close-to-close returns. Entry costs only; ending holdings are marked to market.'}


def evaluate_with_benchmark(payload, weights, window='validation', options=None):
    strategy = fixed_holdings(payload, weights, window, options)
    benchmark = fixed_holdings(payload, [1/len(weights)]*len(weights), window, options)
    return {'portfolio': strategy, 'equal_weight': benchmark}
