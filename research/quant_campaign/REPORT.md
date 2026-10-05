# Quant CLI campaign · 2026-10-05

676 validation sweep trials: 664 completed candidates ranked, 12 deliberate infeasible cases excluded. 104 frozen final candidates completed across eight datasets. Selection used validation only; freeze SHA256 a21fbbc1a979df4347de9df320e2df347de27f005fc6d8507f1ca7d71302f7a4. The primary table shows the validation champion, not the best strategy retrospectively selected on final data. All models, including disappointing models, remain in the full comparison. Main universes share 2025-10-03 to 2026-10-02 final dates; long/new-listing windows differ and are not pooled. 1/104 exploratory 21-day block-bootstrap intervals for annual mean excess over matched equal weights had a positive lower endpoint. These are NOT adjusted for multiple comparisons and overlapping universes are not independent. Costs were 10bps, annual short borrow 3%, negative-cash financing 5%, cash yield/risk-free assumption zero. No account execution, margin/locate simulation, options, or proof of future profitability. Smaller datasets use adjusted IEX; larger datasets use adjusted Yahoo because IEX coverage blocked saving. Current symbols introduce survivorship/selection bias. Numerical stress solved 1000-variable structured synthetic QPs and 500-asset native dense-matrix inputs; 154 assets is demonstrated real-data capacity, not a hard hardware limit. Confirmed problems: portfolio tests require unavailable dataset input, invalid fetch exit code, unlocalized data gaps, provider diagnostics, SCS accuracy labeling, repeated native ARPACK failures/partial-evidence loss, discovery/navigation limits, and a port-dependent test. App code was not changed. Regression: 319 passed, one test failed because it splits a configured 8020 URL on literal 8000; source model suites passed 16 and 17 tests. See the reproducible issue register in research/quant_campaign/ISSUES.md.

## Validation-selected primary outcomes

| Universe | Selected family | Validation Sharpe | Final CAGR | Final Sharpe | Drawdown | Equal CAGR | SPY CAGR |
|---|---|---:|---:|---:|---:|---:|---:|
| 5 | trend_cash | 2.29 | 4.3% | 0.58 | 5.2% | 7.1% | 16.2% |
| 10 | turnover | 1.95 | 3.4% | 0.41 | 6.3% | 8.8% | 16.2% |
| 20 | risk_cap | 1.16 | 14.0% | 1.00 | 8.9% | 13.1% | 16.2% |
| 50 | mean_variance | 1.97 | 10.8% | 1.34 | 6.3% | 14.2% | 16.2% |
| 100 | turnover | 1.92 | 12.1% | 1.37 | 6.5% | 20.3% | 16.2% |
| 154 | min_variance | 1.94 | 2.2% | 1.10 | 1.6% | 17.8% | 16.2% |
| long-window | trend_cash | 0.64 | 10.4% | 1.24 | 10.2% | 15.9% | 20.1% |
| new-listing | signed_momentum | 2.89 | -0.1% | 0.05 | 9.3% | 13.0% | 34.7% |

## Family summaries for the six main universes

| Family | Median final CAGR | Median Sharpe | Positive mean excess | Positive exploratory lower interval |
|---|---:|---:|---:|---:|
| equal | 13.7% | 1.44 | 0/6 | 0/6 |
| inverse_vol | 8.3% | 1.15 | 0/6 | 0/6 |
| min_variance | 1.9% | 0.90 | 0/6 | 0/6 |
| mean_variance | 10.2% | 1.26 | 0/6 | 0/6 |
| momentum | 9.9% | 0.75 | 1/6 | 0/6 |
| trend_cash | 9.2% | 1.09 | 0/6 | 0/6 |
| entropy | 8.3% | 1.19 | 0/6 | 0/6 |
| cvar | 3.9% | 1.40 | 0/6 | 0/6 |
| turnover | 7.1% | 1.02 | 0/6 | 0/6 |
| signed_momentum | 14.4% | 1.21 | 4/6 | 0/6 |
| neutral_reversion | -5.9% | -0.29 | 0/6 | 0/6 |
| ridge | 10.6% | 1.23 | 0/6 | 0/6 |
| risk_cap | 23.0% | 1.12 | 6/6 | 1/6 |

## Review in the app

- Summary: http://127.0.0.1:8020/research/082587a9-fbf0-4be0-9989-d3a573bdd108/
- 5: http://127.0.0.1:8020/research/b10f658f-52ca-4908-872f-ec59c302a13d/
- 10: http://127.0.0.1:8020/research/f613a5f3-670f-4d66-afef-9f5ceb36d730/
- 20: http://127.0.0.1:8020/research/e4c1c974-820d-4487-8135-6c21e1f7404d/
- 50: http://127.0.0.1:8020/research/69bee1ce-6132-40f7-877e-9d12db0b0483/
- 100: http://127.0.0.1:8020/research/a3b1c24c-d170-457e-9ca4-4bd6ddc408ca/
- 154: http://127.0.0.1:8020/research/03e0e9f7-1cbf-4687-9f3f-d9ded76064d1/
- long-window: http://127.0.0.1:8020/research/fe1d5de2-b359-49f5-8ed8-41b4a891d91d/
- new-listing: http://127.0.0.1:8020/research/cd92acea-f960-4c78-adf9-05cbd9c248f8/

## Reproducibility

- [Issue register](ISSUES.md)
- [Driver and universe](run_campaign.py)
- [Policies](strategies.py)
- [Selection and holdout protocol](finalize.py)
- Private command JSON, freeze, artifacts, and raw evidence remain under .local and the owner database. Do not rerun final phases against an already-opened dataset.

## Verified library references

- [CVXPY solver settings](https://www.cvxpy.org/tutorial/solvers/index.html)
- [Ledoit–Wolf API](https://scikit-learn.org/stable/modules/generated/sklearn.covariance.LedoitWolf.html)
- [Ridge API](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html)
- [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbarsingle-1)

## Final review links

- Conclusions: http://127.0.0.1:8020/research/4547429a-010b-4d94-8af8-4cc3d0215277/
- Fifteen findings: http://127.0.0.1:8020/research/b86562a1-64d7-4df0-9271-644d41c483ce/
- Saved regression artifacts: http://127.0.0.1:8020/research/c15a9e31-6728-49bc-8430-1bdd52ca6e83/
