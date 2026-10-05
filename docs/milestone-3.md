# Milestone 3: historical data and fixed holdings

## Try it

1. Run `uv sync --locked`, `uv run python manage.py migrate`, then
   `uv run python manage.py runserver 127.0.0.1:8020`.
2. Log in and open **Datasets**. Choose Alpaca or yfinance, type actual stock or
   ETF symbols (start with `SPY, AGG`), and choose completed-day dates.
3. **Fetch & save dataset** opens the saved snapshot when the request finishes.
   Errors appear on the form. There is no background job to monitor.
4. Inspect the chronological windows. Price charts stop at validation; holdout
   prices and returns are not sent to the browser.
5. Choose a starting example, covariance estimator, and optional training
   lookback. **Create editable problem** imports training-only daily estimates.
6. Inspect the mathematics, edit any declarations or equations, then solve.
   Risk aversion and risk caps still use daily quantities; presets are starting
   examples, not calibrated investment policies. A frontier needs a saved chosen
   point before evaluation.
7. **Evaluate fixed holdings** chooses a weight vector, dataset, entry costs,
   short borrow rate, financing rate, and Sharpe risk-free rate.
8. **Evaluate validation & save** compares your fixed holdings with equal weight.
   Repeat with other portfolios or assumptions. Each result stays frozen.
9. Once selection is finished, **Review final holdout…** shows the exact weights
   and assumptions without computing the result. Cancel to keep it hidden.
   Check the confirmation and open it to save one final result for that data
   fingerprint. Later requests return that result.

## Credentials

You do not enter keys in a web form or chat. This laptop already has a working
Alpaca historical connection: SPY returned 60 adjusted IEX daily prices for
2025-01-02 through 2025-03-31 during verification.
yfinance also returned 60 SPY daily price dates over the same window.

If `.env` does not exist, copy `.env.example` to `.env`. Use either:

- `ALPACA_ENV_FILE=../portfolio-lab/.env` to reuse the existing private file;
  the path is relative to the convex-lab directory, not your shell directory.
- `ALPACA_API_KEY=your-local-key` and `ALPACA_SECRET_KEY=your-local-secret` in
  convex-lab's private `.env`. A complete environment pair takes precedence.

Only the two Alpaca values are read from the external file; its Django secret
and other settings are not imported. Missing or partial pairs produce friendly
errors. Restart the server after editing settings. Choosing yfinance needs no
Alpaca keys. Credentials are never stored with datasets or experiments.

## Files and storage

| File | Purpose |
| --- | --- |
| `core/notation.py`, `parser.py` | Parenthesize according to mathematical precedence: `muᵀw − λwᵀΣw` stays uncluttered; grouped sums, nested powers, and transposes keep necessary grouping. |
| `core/providers.py` | Historical daily prices, explicit provider settings, private credentials, transport timeouts, sanitized errors. No Django or trading imports. |
| `core/data.py` | Align positive prices, split observations, compute training-only mean/sample or Ledoit–Wolf covariance, and create ordinary editable specifications. |
| `core/evaluation.py` | Pure signed fixed-holdings accounting, explicit costs and carry, metrics, and an equal-weight benchmark. |
| `lab/data_views.py`, `forms.py` | Small synchronous fetch, import, evaluate, and final-confirmation flows. All records are scoped to user and workspace. |
| `lab/models.py`, migration `0003` | Add immutable `Dataset` and `Evaluation` beside existing `Problem` and `Experiment`; four custom models in one Django app. |
| `lab/request_limits.py` | Shared five-request capacity gate for fetches and solves in a single process; busy requests retry. |
| `lab/templates/lab/` | Provider choice, window chart, evaluation settings/results, and concrete holdout confirmation. Same base template and local Plotly. |
| `tests/test_data.py`, `test_evaluation.py`, `test_providers.py` | Training leakage, estimator contracts, accounting known answers, missing data, and mocked historical client contracts. |
| `tests/test_data_views.py`, `test_browser_data.py` | Every new view, snapshots, workspace isolation, holdout gating, and real browser workflows. |

## Numerical choices

The dataset stores the aligned adjusted closing prices, symbol order, provider
settings/version, dates, coverage, and a content fingerprint. Identical fetched
data reuse the existing snapshot, including its saved name and symbol order.
The fingerprint sorts columns so reordering symbols cannot reset the final gate.
Changing the provider or revised historical prices does create a different
fingerprint. This gate prevents accidental reuse; it cannot establish scientific
independence of overlapping or retrospectively selected windows.

Unequal listing histories are trimmed at the shared boundaries. Interior gaps,
missing assets, nonpositive prices, and duplicate dates are rejected clearly.
Prices are never filled. Dates on which every asset is absent are omitted; the
app does not validate an exchange calendar. Use assets quoted in one currency;
currency conversion and currency validation are not implemented.

Split the `n−1` close-to-close return observations: first floor(0.6(n−1)) for
training, next through floor(0.8(n−1)) for validation, remaining for final holdout.
The return intervals do not overlap. Import uses only training prices and returns:
arithmetic daily mean, sample covariance with `ddof=1` or Ledoit–Wolf shrinkage,
and training returns as CVaR scenarios. The optional lookback truncates training
only. Covariance is symmetrized for numerical roundoff; no hidden ridge is added.
Imported arrays remain editable; changes produce a provenance notice.

Evaluation enters at the **first close within the selected evaluation window**,
not the preceding close. It earns subsequent close-to-close returns, so a window
of N price dates has N−1 return intervals plus its initial entry-cost observation.
It holds fixed adjusted-price units without refits or rebalances. These units
approximate total-return exposure and are not literal shares or a margin account.

For weights `w`, gross exposure `G=sum(abs(w))`, and entry cost fraction `c`,
post-cost equity is `V=1/(1+cG)`. Units are `V*w/P_entry`, cash is
`V*(1−sum(w))`, and the entry fee is `1−V`. Negative units are shorts; negative
cash represents borrowing. The core imposes no additional exposure or budget
constraints: these belong in your editable optimization problem.

Each subsequent interval charges short borrow on prior-close short notional and
financing on prior cash debt, using calendar days / 365. Rates are constant annual
fractions. Positive cash earns zero. Entry costs apply to both buys and shorts;
there is no exit trade, exit fee, market impact, borrow-availability model, or
margin-call simulation. Nonpositive equity stops the path without clipping the
loss, and CAGR becomes unavailable. The equal-weight benchmark uses the same
entry cost and metric assumptions, holding fixed units too.

Total return and drawdown include entry costs. CAGR uses actual elapsed calendar
years (365.25 days). Volatility is sample standard deviation times sqrt(252);
Sharpe uses mean periodic excess return divided by that standard deviation times
sqrt(252), with daily risk-free fraction `(1+r_f)^(1/252)−1`. These annualization
assumptions approximate trading-day spacing. Short-window values are unstable.
Undefined ratios or overflowing CAGR are reported as unavailable.

## Synchronous budgets

Defaults: 20 assets, 5000 shared price dates, 20-second cooperative fetch budget,
10-second per-network-request timeout, five shared request slots. The owner can
change `LAB_MAX_ASSETS`, `LAB_MAX_PRICE_ROWS`, and `LAB_FETCH_SECONDS` in `.env`
and restart. These bound workload, not mathematical strategy choices.

The pinned Alpaca SDK lacks a public timeout argument. The small adapter uses
its inspected Requests `_session` and disables `_retry` sleeps; tests check this
compatibility. yfinance uses its public custom-session hook and sequential
downloads, with a remaining-time budget per request. Its shared cookie/session
state means only one yfinance fetch runs per process; another gets a retry message.
These budgets are cooperative, not hard wall-clock termination. Parsing,
estimation, rendering, and socket behavior can add time. Larger workloads need
discussion before changing this synchronous design. No workers or queues.

## Verification and sources

Run `uv run pytest -m '' -q` to include unit, Django, and Chromium tests in one
serial run. Do not run separate test processes simultaneously against the same
configured SQLite test file. Screenshots are in `screenshots/milestone-3/`;
historical milestone images remain unchanged.
Verification: 232 unit/Django tests and 6 browser tests passed; Django checks,
migration application, and migration consistency passed. All 15 milestone
screenshots were reviewed, including mobile pages and expanded charts. The
review caught and fixed clipped mobile chart titles, cramped legends, and
equivalent-number formatting that incorrectly flagged training estimates as edited.

Official APIs verified for this implementation:
[Alpaca historical client](https://alpaca.markets/sdks/python/api_reference/data/stock/historical.html),
[daily request](https://alpaca.markets/sdks/python/api_reference/data/stock/requests.html),
[feed and adjustment enums](https://alpaca.markets/sdks/python/api_reference/data/enums.html),
[yfinance download](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html),
[Ledoit–Wolf](https://scikit-learn.org/stable/modules/generated/sklearn.covariance.LedoitWolf.html),
[pandas fractional changes](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.pct_change.html),
[Requests transport](https://requests.readthedocs.io/en/latest/api/#requests.adapters.HTTPAdapter.send),
[curl-cffi session](https://curl-cffi.readthedocs.io/en/latest/api.html), and
[Django signing](https://docs.djangoproject.com/en/6.1/topics/signing/),
[Plotly window marker](https://plotly.com/python/horizontal-vertical-shapes/), and
[Plotly legends](https://plotly.com/python/legend/).
Portfolio specifications retain the quadratic-program formulation of Boyd &
Vandenberghe §4.4.1; their constraints remain explicit and editable.

Stop for review here. Comparisons and server-demo setup are milestone 4.
