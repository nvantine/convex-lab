# Research interpretation

What generalized and what did not

Seven of eight validation-selected dataset champions earned less than equal weights in the final window. This is the primary selection result. Selecting the best final family now would be a second use of the holdout. We did not change models afterward.

Across the six comparable one-year universes, equal weight's median CAGR was 13.7%. Minimum variance's median was 1.9%, with a 154-asset result of 2.2% CAGR, 2.0% annual volatility and 1.6% maximum drawdown. That objective minimizes estimated risk; it never promises an 8% return. It tends to favor cash-like/bond assets. Low return alone is not solver failure.

Mean-variance reached 17.1% CAGR, Sharpe 1.93 and 4.8% drawdown on 154 assets, versus equal weight at 17.8%, Sharpe 1.54 and 6.4% drawdown. It exchanged some return for lower realized risk in this window. This was not the model selected as that dataset's overall validation champion.

The risk-cap family had positive mean excess over matched equal weights in all six main universes. Its median final CAGR was 23.0%. On 100 assets it achieved 41.2% CAGR, Sharpe 2.08 and 7.3% drawdown; trade-average large exposures included MU, USO and XLE. On 154 assets a hold-after-entry policy returned 52.7% CAGR but had 32.7% volatility and 19.5% drawdown, worse risk than equal weights. The cap limits estimated covariance risk at optimization time; drift and regime changes can defeat a realized-risk interpretation. These exposures are plausible descriptions, not causal proof of skill.

Signed momentum had positive mean excess in four of six main universes. On ten assets it returned 18.4% CAGR with Sharpe 1.58, versus equal weight at 8.8% CAGR. Average gross exposure was about 1.54 and borrowing cost was about 0.9% of initial equity. The newer-listing universe's validation-selected signed momentum instead ended slightly negative on final data. Long/short flexibility was useful in some windows and costly in others; there is no locate, liquidity, options or margin simulation.

CVaR on twenty assets achieved 10.8% CAGR, Sharpe 1.77 and 3.8% drawdown, versus equal weight at 13.1% CAGR and 5.4% drawdown. Bond-heavy allocations reduced tail loss in this example. Sample CVaR concerns the estimated historical tail, not a guarantee about future losses.

Dollar-neutral reversion lost money in the main-window median: -5.9% CAGR and negative Sharpe. The chosen signal did not show reliable reversal after costs and borrowing. Ridge's median CAGR was 10.6%, with no positive excess in the six main universes. Strong regularization/shrunk forecasts often resemble a conservative historical-mean policy; this experiment does not establish that all prediction models are ineffective.

Cost and timing checks show why maximally frequent trading is not automatically better. The saved cost curves charge 0, 10, 50 and 100 bps on traded notional. Turnover penalties discourage movement; they also change which forecasts are acted on. Daily, weekly, monthly and hold schedules were compared before final selection. Position and gross limits constrain target weights at a trade, not every intraday or drifting portfolio state.

Uncertainty and limitations

Only one of 104 exploratory block-bootstrap intervals for annual mean excess over equal weights had a positive lower endpoint. They use dependent observations, overlapping universes, and no multiplicity adjustment. An apparent winner is a lead for a fresh future test, not established alpha. The main final interval is one year, the longer-history final interval is about three years, and the newer-listing final interval is about six months. Do not pool their CAGR/Sharpe as independent replicates. The mixed universe contains current survivors and many correlated or overlapping ETFs; more symbols does not necessarily add independent bets.

Application limits and defects

Real data and custom rolling models worked at 154 assets. Synthetic structured QPs worked at 1,000 variables. Native dense matrix inputs were tested at 500 assets; 708 hit the configured parameter-entry budget. These are demonstrated operating points, not the physical maximum. Native weekly mean-variance/signed at 154 assets repeatedly hit ARPACK covariance certification errors and lost partial evaluation evidence. SCS produced an objectively inaccurate native 500-asset solution despite the verified flag. The portfolio-revision test command was blocked by a nonexistent dataset option. Details, original commands, expected failures and proposed fixes are in the issue register.

The high-demand UI review found an owner-ledger scaling issue: roughly four seconds to render and a process peak near 1.3 GiB after loading the unpaginated ledger. Original aggregate report text overflowed on mobile because of an unbroken hash, and long plot titles clipped. This conclusions report groups that displayed hash and shortens titles as a presentation workaround; the old report remains a reproduction case. All eleven existing live-server browser tests passed; the unit suite had 319 passes and one port-dependent test failure. Source suites passed 16 and 17 tests.

[Open conclusions in the app](http://127.0.0.1:8020/research/4547429a-010b-4d94-8af8-4cc3d0215277/)

## Final QA additions

The isolated, saved regression suite had 318 passing tests and two failing tests: the same port assumption, plus a concurrency test that hardcodes the database basename despite a supported custom isolated path. JUnit and logs are saved in the Quant QA report. A further CLI protocol issue was reproduced while annotating failures: notes were saved successfully but returned ok=false/exit 1 based on the old run status. This can cause agents to retry successful mutations. The final issue register has 15 findings; older report versions remain frozen.
