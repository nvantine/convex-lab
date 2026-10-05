"""Aligned daily prices, chronological splits, and training-only parameters."""
from copy import deepcopy
import hashlib
import json
from importlib.metadata import version
import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf
from core.parser import ProblemError
from core.presets import get_preset


def content_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def aligned_prices(frame, symbols, minimum=30, maximum=5000):
    """Trim unequal start/end histories; reject interior holes instead of inventing prices."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ProblemError('No daily prices were returned. Check symbols, dates, and provider access.')
    missing = [symbol for symbol in symbols if symbol not in frame or frame[symbol].isna().all()]
    if missing:
        raise ProblemError('No prices for: ' + ', '.join(missing) + '. Check ticker spelling for this provider.')
    try:
        frame = frame.loc[:, symbols].copy().astype(float)
        frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    except (TypeError, ValueError):
        raise ProblemError('Provider returned invalid dates or nonnumeric prices.') from None
    if frame.index.isna().any():
        raise ProblemError('Provider returned invalid dates.')
    if frame.index.has_duplicates:
        raise ProblemError('Provider returned duplicate dates; the dataset was not saved.')
    frame = frame.sort_index().dropna(how='all')
    observed = frame.to_numpy()
    valid = observed[~np.isnan(observed)]
    if not np.isfinite(valid).all() or (valid <= 0).any():
        raise ProblemError('Adjusted prices must be positive and finite.')
    shared = frame.dropna()
    if len(shared) < minimum or len(shared) > maximum:
        raise ProblemError(f'Need between {minimum} and {maximum} shared daily prices. Change the date window or symbols.')
    interior = frame.loc[shared.index[0]:shared.index[-1]]
    if interior.isna().any().any():
        raise ProblemError('Some assets have missing prices inside the shared window. Choose another window, provider, or universe; prices are never filled.')
    coverage = [{'symbol': symbol, 'first': str(frame[symbol].first_valid_index().date()),
                 'last': str(frame[symbol].last_valid_index().date()), 'observations': int(frame[symbol].notna().sum())}
                for symbol in symbols]
    payload = {'dates': shared.index.strftime('%Y-%m-%d').tolist(), 'symbols': symbols, 'values': shared.to_numpy().tolist()}
    return payload, {'coverage': coverage, 'trimmed_dates': len(frame)-len(shared), 'shared_prices': len(shared)}


def price_frame(payload):
    return pd.DataFrame(payload['values'], columns=payload['symbols'], index=pd.to_datetime(payload['dates']))


def split_windows(payload):
    """Split return observations, not overlapping price rows: first 60%, next 20%, rest."""
    count = len(payload['dates'])-1
    train, validation = int(count*.6), int(count*.8)
    if train < 2 or validation <= train or validation >= count:
        raise ProblemError('More history is needed for a chronological 60/20/20 split.')
    return {name: {'start': start, 'end': end, 'count': end-start,
            'first': payload['dates'][start+1], 'last': payload['dates'][end],
            'previous_close': payload['dates'][start]}
            for name, start, end in [('train',0,train), ('validation',train,validation), ('holdout',validation,count)]}


def estimate_training(payload, estimator='ledoit-wolf', lookback=None):
    window = split_windows(payload)['train']
    # Never use validation/holdout observations in the estimates or CVaR scenarios.
    returns = price_frame(payload).iloc[:window['end']+1].pct_change(fill_method=None).iloc[1:]
    if lookback is not None:
        if type(lookback) is not int or not 2 <= lookback <= len(returns):
            raise ProblemError(f'Training lookback must be between 2 and {len(returns)}, or blank for all training rows.')
        returns = returns.iloc[-lookback:]
    values = returns.to_numpy()
    if estimator == 'sample':
        covariance = np.atleast_2d(np.cov(values, rowvar=False, ddof=1))
        shrinkage = None
    elif estimator == 'ledoit-wolf':
        fitted = LedoitWolf(store_precision=False, assume_centered=False).fit(values)
        covariance, shrinkage = fitted.covariance_, float(fitted.shrinkage_)
    else:
        raise ProblemError('Choose sample covariance or Ledoit–Wolf.')
    # Symmetry only removes floating-point antisymmetry; no hidden risk ridge.
    covariance = (covariance+covariance.T)/2
    return {'mu': values.mean(axis=0).tolist(), 'Sigma': covariance.tolist(), 'R': values.tolist(),
            'estimator': estimator, 'shrinkage': shrinkage, 'observations': len(returns),
            'versions':{name:version(name) for name in ('numpy','pandas','scikit-learn')},
            'first_return': str(returns.index[0].date()), 'last_return': str(returns.index[-1].date())}


PORTFOLIO_PRESETS = ['min-variance','mean-variance','risk-cap','signed','cvar', 'return-risk','return-risk-turnover','four-criteria']


def estimates_fingerprint(parameters):
    """Compare numerical estimates, ignoring row order, labels, and 0 versus 0.0."""
    values = []
    for p in parameters:
        if p['name'] not in ('mu','Sigma','R','scenario_count'):
            continue
        array = np.asarray(p['value'],dtype=float)
        # JSON/JavaScript loses the sign of -0.0, which carries no information.
        array = np.where(array==0,0.,array)
        values.append({'name':p['name'],'value':array.tolist()})
    return content_digest(sorted(values,key=lambda p:p['name']))


def problem_from_training(payload, preset='min-variance', estimator='ledoit-wolf', lookback=None):
    """Generate ordinary editable declarations; this creates no special strategy logic."""
    if preset not in PORTFOLIO_PRESETS:
        raise ProblemError('Choose a portfolio example for importing market parameters.')
    spec = get_preset(preset)
    estimate = estimate_training(payload, estimator, lookback)
    n, scenarios = len(payload['symbols']), estimate['observations']
    for variable in spec['variables']:
        if variable['name'] == 'w':
            variable['shape'] = [n]
        if variable['name'] == 'u':
            variable['shape'] = [scenarios]
    for parameter in spec['parameters']:
        name = parameter['name']
        if name in ('mu','Sigma','R'):
            parameter['value'] = deepcopy(estimate[name])
        elif name == 'scenario_count':
            parameter['value'] = scenarios
        elif name == 'w_prev':
            parameter['value'] = [1/n]*n
    return spec, {key:value for key,value in estimate.items() if key not in ('mu','Sigma','R')}, estimates_fingerprint(spec['parameters'])


def estimates_edited(spec):
    binding = spec.get('data')
    if not binding:
        return None
    try:
        return estimates_fingerprint(spec['parameters']) != binding['estimates_digest']
    except (KeyError,TypeError,ValueError):
        return True
