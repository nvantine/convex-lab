# Quant campaign archive

This is a research/stress campaign against application commit af48aeb. It did
not modify application code or connect to execution/account endpoints.

## Results to read first

- [Report and selection outcomes](REPORT.md)
- [Interpretation, risks and model explanations](ANALYSIS.md)
- [Every application finding and reproduction](ISSUES.md)
- [Frozen pre-final choices](frozen_protocol.json)
- [CLI invocation archive](invocations.json)
- Screenshots: ../../screenshots/quant-campaign/

The owner website retains all research, source revisions, unsuccessful attempts,
trial tables, native solver evidence, final equity curves, trades, diagnostics,
and artifact manifests. The conclusions report is linked from ANALYSIS.md.
Market prices and private logs/databases are not committed.

## What was tested

Eight real datasets: 5, 10, 20, 50, 100 and 154 assets over a five-year requested
history, five assets over a longer history, and six assets including a newer ETF.
Actual aligned dates and providers are recorded. No missing prices were filled.

There were 676 sweep trials, including 12 intentionally infeasible cases; 664
completed candidates were ranked. The matrix covered hold/monthly/weekly/daily
trading, 21/63/126/252-day lookbacks, sample/Ledoit–Wolf covariance, 0/10/50/100 bps
costs, multiple prediction penalties and risk aversions, position caps, and signed
gross exposure 1/1.6/3. More extreme exposure and invalid input probes were separate.
Native real-data problems/frontiers and synthetic known-answer solver tests
were also executed. See the invocation archive for all additional cases.

Thirteen model families:

| Family | Intent and assumptions |
|---|---|
| equal | Baseline without expected-return estimation. |
| inverse_vol | Weight inversely to past volatility; ignores correlations. |
| min_variance | Minimize estimated daily variance under budget/caps. |
| mean_variance | Reward shrunk historical mean, penalize variance. |
| momentum | Cross-sectional trailing signal with a quadratic risk penalty. |
| trend_cash | Equal slices only where the price is above its past mean; rest cash. |
| entropy | Variance penalty plus a log-weight diversification incentive. |
| cvar | Minimize sample 95% tail loss; no return reward by default. |
| turnover | Mean-variance with a penalty on changing drifting weights. |
| signed_momentum | Momentum with negative weights, net one, gross/caps. |
| neutral_reversion | Negative trailing signal, net zero and gross one. |
| ridge | Lagged returns predict the next return, regularized and shrunk. |
| risk_cap | Maximize estimated mean under an estimated-variance ceiling. |

Analytic baselines have their own explicit policies; optimizer caps do not
silently transform equal weight, inverse volatility or trend allocations.
Forecast parameters are daily, costs are bps on traded notional, borrowing and
financing are annual fractions. Signals precede trades by one close. Constraint
checks apply to target allocations, not continuously drifting holdings.

## Final protocol

Before accessing final results, one candidate for each family and dataset was
selected by validation Sharpe and frozen: 104 candidates. Cost/gross stress
cases were not used to choose the final policies. The unchanged freeze file's
SHA256 is a21fbbc1a979df4347de9df320e2df347de27f005fc6d8507f1ca7d71302f7a4.

Each dataset's final window was opened once through the CLI's explicit flags.
batch.py ran all frozen candidates together, including poor ones. It computed
matched equal-weight references and 21-observation circular block-bootstrap
intervals (1,000 samples). These are exploratory and not multiplicity-adjusted.
No model/hyperparameter edits followed final results. Later changes concern
reporting and reproduction tools only.

## Reproduce safely

Use uv and the configured staff owner. Existing results can be inspected with
convex-lab runs show ID --logs or exported to a fresh directory with runs export.
The invocation archive removes idempotency flags so an explicit validation
reproduction creates a new attempt. Paths and record IDs refer to this checkout;
fresh databases must create their own data/revisions first. Source registration
freezes code; editing a file does not change an old source revision.

run_campaign.py implements registration, Alpaca fetching, and the main
validation stages. Supplemental commands are retained in invocations.json and
the private JSON evidence. finalize.py freezes choices and executes final
batches. summarize.py derives tables from checksum-verified final artifacts.
review_ui.py reviews scoped GET HTML and local browser assets without passwords.

Do not replay final commands to pretend a window is untouched. The application
rejects another opening of the same fingerprint. A genuinely new future study
needs a new campaign name/output directory and a fresh future evaluation period.
Refreshed historical provider data can differ after corporate-action corrections;
the original frozen snapshots and hashes are the reference for this study.

## Verification and author corrections

Registered source suites: 16 then 17 passing tests, including a two-asset closed
form, all-family constraints, permutation equivariance, impossible-cap rejection,
and the final batch on synthetic data. Independent SLSQP/solver/conditioning
checks are saved in the capacity report.

Existing application unit suite: 319 passed and one port-dependent test failed.
The saved isolated regression used a different test database basename and had
318 passes/two failures; the extra failure is another hardcoded test assumption.
Existing real-server Playwright suite: 11 passed. Read-only large-report review:
valid charts/KaTeX and recorded original mobile overflow/ledger-memory findings.
These failures were reported, not hidden by changing app code or configuration.

The final issue register contains 15 findings. While adding annotations, another
protocol defect appeared: notes on failed/partial runs are saved but return a
failure exit status. The read-back verification and original mutation responses
are preserved. Fifteen findings are also saved as a separate website report.

## Next development priorities

1. Numerical provenance/accuracy and partial refit evidence (Q05–Q07).
2. Portfolio test execution and metadata action outcomes (Q01/Q14).
3. Paginated lightweight ledger queries and useful campaign labels (Q10/Q12).
4. Symbol/date gap diagnostics and per-symbol failed-batch fallback (Q03/Q04).
5. Configurable-path tests, discoverable limits, responsive report rendering.

Next research should pre-register fewer policies, use nested chronological
validation, test realized rather than only estimated risk, and reserve a genuinely
new future window. Do not search these opened final intervals for another winner.

The first native synthetic input used lowercase psd; the app correctly rejected
it and the author corrected PSD. The first browser harness queried synchronous
Django from Playwright's async loop; rendering was moved before browser startup.
Neither is attributed to the application. All original CLI attempts are retained.
