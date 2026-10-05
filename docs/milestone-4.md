# Milestone 4: batches, historical trading, comparisons, server demo

## What to click

1. **Datasets** → choose Alpaca or yfinance → enter actual tickers, dates, and
   **Symbols per batch** (1–5). Up to 100 assets are supported by default.
2. **Fetch & save dataset** opens a progress page immediately. It sends one
   asynchronous browser request per batch and saves successful symbols locally.
   Pause after the current batch, close the page, or return via **Datasets** to
   resume. Completion opens the dataset automatically, without a manual reload.
3. Failed symbols are listed individually. **Retry failed symbols one at a time**
   keeps successful prices. Excluding failures requires an explicit checkbox;
   no asset is silently removed and no provider is silently substituted.
4. Create a training problem and solve it. On the result click
   **Evaluate historical portfolio**. The default is **Rolling re-optimization**
   with **Monthly** rebalancing and 126 past return observations per refit.
5. Choose daily, weekly, monthly, or hold after entry. Rolling re-solves your
   exact edited objective and constraints. **Restore original weights** trades
   back to the saved vector on the same schedule. Hold after entry makes only
   the initial allocation (rolling still computes that initial vector).
6. Map which named parameters should receive mean, covariance, return scenarios,
   scenario count, or prior-close drifting weights. Conventional names are
   preselected only when present. Other constants stay exactly as you defined
   them. You may use your own names, expressions, and constraints. CVaR examples
   can resize their scenario auxiliary `u` to the chosen lookback.
7. **Evaluate validation & save** displays equity, drawdown, metrics, every
   simulated trade and fee, and links to each re-solve's mathematics and duals.
   Change assumptions and save another validation result. The original is frozen.
8. **Compare** → select up to six records. Inspect the metrics table and flagged
   differences. Equity/drawdown share their date axis, so zooming either updates
   both; expand the chart to inspect it. Compatible decision vectors overlay too.
   Saved frontiers can be compared by status, sample count, definitions, solver,
   and seed; inspect their full Pareto views on their individual result pages.
9. Final holdout still requires a separate signed confirmation and is opened once
   per identical data fingerprint in your workspace. Comparisons never open it.

**Daily refresh:** the owner can watch universes and schedule the bounded
`refresh_datasets` command after market close; follow [server-demo.md](server-demo.md).
The checkbox records a preference; it does not install a timer on your laptop.

## Fetching and local storage

The old request gave an entire universe a 20-second shared timeout, while Yahoo
requests were sequential. That could fail large universes. The new default gives
**each batch** 60 cooperative seconds, with a 10-second limit per network request.
Small batches, durable successes, and explicit retries make recovery manageable;
provider rate limits and access restrictions can still prevent a download.

Recent symbol caches are reused only for the same provider, requested date range,
owner, and workspace. The default age is 24 hours, measured from each symbol's
actual fetch timestamp. Reusing it does not renew its age. A forced refresh fetches
adjusted history again, rather than appending prices with potentially different
split/dividend adjustment scales. Every finished dataset is an immutable snapshot;
old experiments retain their data. This stores full snapshots, not a central
incremental bar warehouse. Dates stop at a completed day, conservatively after
17:00 New York time with weekend rollback. No exchange calendar is implemented.

A short database lease protects each request against double clicks, two tabs,
and the refresh command. Network work holds no database transaction. The browser
sequences batches; no general background worker or queue is required. The optional
server timer runs the same service and saves batches even without an open page.

## Trading methodology

For a trade at close `t`, estimates use only prices through close `t−1`; the
lookback contains that many past close-to-close returns. Monthly and weekly trades
use the first available close of a new calendar month / ISO week. Daily trades
use every following close. There is no new trade at the final marking close.
The first entry is at the first evaluation close; no earlier holding earns that
first interval. The starting capital is 1.

For pre-trade equity `E`, current signed asset notionals `n`, target weights `w`,
and cost fraction `c`, post-cost equity `v` solves

```math
v + c\sum_i |v w_i - n_i| = E.
```

The implementation solves this piecewise-linear equation exactly by its
breakpoints, choosing the largest feasible root. This includes both buys and
sells, including shorts. New adjusted-price units are `v*w/P_t`; cash is
`v*(1−sum(w))`. Borrow and negative-cash financing use prior-close notionals and
calendar days / 365. Positive cash earns zero. The ledger stores dates, weights,
units, signed dollar trades, pre/post equity, fees, and turnover. Turnover is gross
traded notional / pre-trade equity, summed across executed trades (not annualized).
The equal-weight comparator restores equal weights on the same dates with the
same costs, but does not solve another optimization problem.

Sample covariance uses `ddof=1`; Ledoit–Wolf uses its fitted shrinkage covariance.
Each re-solve records its exact past window, parameter fingerprint, estimator
versions, solver evidence, decision variables, duals, and violations. Its math page
reconstructs the parameters from the immutable dataset/spec and checks the
fingerprint before rendering. Full repeated covariance/scenario arrays are not
saved for every refit. Restore recorded dependencies if reconstruction differs.

This is an adjusted-price simulation, **not actual Alpaca trades**. It omits
market impact, margin calls, borrow availability, currency conversion, taxes,
raw share counts, and exit liquidation. Fixed cost rates/fees are assumptions.
Past-only refitting may use earlier validation/holdout observations as time moves
forward; policy, mappings and hyperparameters are fixed before that window starts.
It does not retune them after looking at its future performance.

A chosen Pareto point uses its frozen scalarization and tie constraints literally.
A training-optimum tie bound may be infeasible with new estimates; clone and edit
it before evaluation if your intended rolling policy needs different constraints.
No constraints are secretly removed to make a refit succeed.

A request allows 300 refits and a 45-second cooperative budget by default. The
owner can change these in `.env`. First-solve failures save no evaluation. A later
failure or exhausted budget saves a prominently marked partial path; its benchmark
covers the same completed dates. A saved partial final result still spends the
holdout. Compilation/estimation can exceed the native solver time limit; these
limits are not hard termination guarantees. Revisions/overlapping refreshed
snapshots do not provide independent unseen holdouts.

## File map

- `core/rolling.py`: pure causal refits, calendar schedules, self-financing trade
  fees and signed historical paths. `evaluation.py` retains the original tested
  fixed-holdings arithmetic and shared metric functions.
- `lab/fetching.py`: one batch, private cache reuse, short leases, and finalization;
  `FetchRequest`/migration 0004 save mutable progress, alongside frozen datasets.
- `lab/data_views.py`, `forms.py`: progress endpoints, explicit recovery controls,
  evaluation policies, signed holdout confirmation, and refit inspection.
- `core/comparison.py`, `lab/comparison_views.py`: compare stored evidence and build
  linked charts; selecting records performs no solve or provider request.
- `lab/templates/lab/`, `lab.js`: semantic forms, KaTeX, chart dialog, and the small
  asynchronous fetch loop. No CDN, JavaScript framework, or build step.
- `refresh_datasets.py`, `deploy/`, `server-demo.md`: optional daily refresh and
  concrete one-process Gunicorn/Caddy examples for your future server.
- `tests/test_fetching.py`, `test_rolling.py`, `test_comparison*.py`, and browser
  tests: offline known-answer/accounting/causality/isolation/error-path checks.

Math references remain Boyd & Vandenberghe §§4.4.1, 4.7, 5.6; the rolling timing
and transaction-cost simulation are app methodology, not a claim of an investment
model prescribed by those sections.

## Verification

The complete suite passed **291 tests**, including 8 Chromium workflows.
All 14 new screenshots were inspected; the review improved mobile comparison
spacing, labels, guest controls, saved-solve wording, and preserving zoom in expanded charts. Screenshots are in
`screenshots/milestone-4/`; prior milestone images remain historical.

Live read-only checks fetched SPY, QQQ, IWM, AGG, and GLD over five years from both
providers (1256 closes each). Alpaca completed in 1.12 seconds; Yahoo in 2.96 seconds
in that check. The reported Alpaca access failure could not be reproduced; tests
cover access-denied, rate-limit, missing-symbol, timeout and recovery paths.
An offline 100-symbol request was verified as twenty 5-symbol batches. A synthetic
100-asset monthly evaluation completed 13 refits in about 0.64 seconds here; this
is not a speed guarantee for arbitrary user expressions or future network calls.

Verified official APIs:
[Alpaca historical client](https://alpaca.markets/sdks/python/api_reference/data/stock/historical.html),
[yfinance download](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html),
[CVXPY solver options](https://www.cvxpy.org/tutorial/solvers/index.html),
[Plotly shared-axis subplots](https://plotly.com/python/subplots/),
[Plotly graph data/layout access](https://plotly.com/javascript/plotlyjs-function-reference/).
Hosting references and limitations are in [server-demo.md](server-demo.md).
