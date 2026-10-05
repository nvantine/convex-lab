# Quant campaign issue register

Campaign: 2026-10-05. Application revision af48aeb. App code was left unchanged
while conducting research. CLI JSON and exact invocation arguments are retained
in ignored .local/quant-campaign-20261005; run links and notes are also saved in
the owner's Research ledger. These records contain no credentials.

## Q01: portfolio source tests cannot be run through their own revision

- Type: application bug. Severity: high for agent usability.
- Reproduce: register strategies.py:target_weights as interface portfolio,
  then run convex-lab tests run REVISION_ID.
- Actual: exit 2, "Portfolio strategies require --dataset."
- Expected: run the source bundle's tests without market data. The tests
  command does not even offer a dataset argument.
- Workaround: register the same source bundle with a research entry point and
  run its tests. Saved suites passed 16, then 17 tests including the final batch.
- Fix idea: apply the dataset requirement only to portfolio backtest execution.

## Q02: fetch input errors use the wrong documented exit code

- Type: application protocol bug. Severity: medium.
- Reproduce: request 101 actual symbols using the default 100-asset setting.
- Actual: failed saved run with exit 1/execution_failed; documentation promises
  exit 2/invalid_input for invalid input.
- Expected: preserve the failed attempt while reporting the validation category.
- The asset cap itself is an expected configurable limit, not a bug. Setting
  LAB_MAX_ASSETS=154 permitted a real 154-asset Yahoo dataset.

## Q03: interior data-gap errors do not identify affected symbols or dates

- Type: usability gap exposed by real provider coverage. Severity: high.
- Reproduce: run_campaign.py fetch; see data-50.json and data-100.json.
- Actual: IEX fetched all symbols, with errors={}, but no dataset was saved.
  The final message says some assets have missing interior prices.
- Expected: symbol/date gap summary and a way to propose explicit exclusions
  or a different window. Repeating resume cannot resolve a coverage gap.
- Workaround: explicitly fetch a separate Yahoo snapshot; never fill prices or
  mix provider prices silently. 50, 100, and 154 assets succeeded with Yahoo.

## Q04: provider-specific ticker spelling and batch failure diagnostics

- Type: provider integration/diagnostic gap. Severity: medium.
- Reproduce: fetch Alpaca symbols MS,BRK-B, then MS alone, over 2023–2026.
- Actual: MS succeeds; BRK-B fails with a generic credential/network message.
  In the initial 154-symbol request, one failed batch reported errors for
  MS, BRK-B, V, MA, and AXP; a smaller cached reproduction retained MS correctly.
- Confirmed cold-cache control: the five-symbol batch, with --no-cache and the
  original 2021–2026 window, fetched zero and marked all five failed. Removing
  BRK-B fetched all four controls successfully. Cache successes can mask this
  batch-wide behavior, so preserve the explicit no-cache reproduction.
- Fix idea: document provider symbol namespaces, preserve safe HTTP categories,
  and retry failed batches per symbol before assigning individual failures.

## Q05: verified_optimal does not verify objective accuracy

- Type: numerical validation/labeling issue. Severity: high.
- Reproduce: native-PSD-solve-500-SCS from the retained invocation manifest.
  Sigma is diagonal with 500 entries linearly spaced 0.00005 to 0.0005.
  Minimize quad_form(w,Sigma), subject to sum(w)=1 and w>=0.
- Known answer: w_i=(1/Sigma_ii)/sum_j(1/Sigma_jj).
- Actual: status optimal and verified_optimal=true, but approximately 32.7%
  relative objective error and 0.00556 maximum weight error. Feasibility passes.
- CLARABEL and OSQP matched the same answer closely. The discrepancy already
  appears at 154/256 assets, and raw default SCS settings are less accurate.
- Fix idea: clarify the label, show objective scaling and optimality residuals,
  offer scaling/solver tolerances, and test small-scale objectives. A feasible
  point plus solver status is not an independent optimality certificate.
- Campaign market policies used CLARABEL. Do not generalize this diagonal test
  into a claim that every SCS problem is inaccurate.

## Q06: native rolling PSD certification can fail at 154 assets

- Type: numerical robustness bug. Severity: high.
- Reproduce: create mean-variance or signed from the 154-asset Yahoo dataset,
  solve, then weekly rolling backtest with lookback 126 and costs 10 bps.
  See real-native-backtest-154-mean-variance.json and the saved failed run.
- Actual: CVXPY ARPACK PSD-certification exception on a covariance matrix.
  The same campaign's custom callback using an explicitly certified covariance
  and psd_wrap passed large-universe trials.
- This can depend on the particular refit matrix and ARPACK initialization;
  retain data fingerprint, source problem, and full traceback when reproducing.
  Repeating the same mean-variance command failed again, and signed failed with
  the same certification exception: three retained failed attempts.
- Fix idea: validate covariance numerically, retain its PSD provenance across
  canonicalization, and avoid unnecessary stochastic certification. Do not
  indiscriminately psd_wrap arbitrary user matrices.

## Q07: unexpected rolling exceptions discard earlier successful path evidence

- Type: application evidence loss. Severity: medium/high.
- Same reproduction as Q06. The failed native attempt records its message and
  invocation but has no evaluation containing the preceding successful refits.
- Expected: failed refit index/date plus the saved partial path and diagnostics.
- Fix idea: distinguish solver/input errors from unexpected numerical failures
  and preserve progress in both cases, without fabricating later prices/trades.

## Q08: agents cannot discover configured workload limits from capabilities

- Type: interface discovery gap. Severity: medium.
- Reproduce: run capabilities and doctor (retained snapshots).
- Actual: commands/atoms/solvers/schema are exposed, but asset, parameter,
  variable, frontier, row, and refit limits are absent. A research client must
  read app source or probe errors to discover the current configuration.
- Fix idea: include effective limits and distinguish website and CLI budgets.

## Q09: one comparison is limited to six records

- Type: expected UI budget, practical workflow limitation for this campaign.
- Thirteen strategy families cannot all use the native side-by-side selector.
- Workaround: save an aggregate research report containing all families and
  plots; group native comparisons into smaller selections.
- Fix idea: add campaign-aware summary/filtering, not an unbounded HTML table.

## Q10: campaign runs have indistinguishable names in the ledger

- Type: research-navigation gap. Severity: medium.
- Reproduce: sweep the same revision over several datasets, then open Research.
- Actual: parents all say policy · sweep and children repeat trial N; dataset,
  family, schedule, and lookback are absent from the index. Runs are correctly
  scoped and retained, but hundreds of records are difficult to browse.
- Workaround: aggregate reports and uniquely named final source revisions.
- Fix idea: a run label/tag option, dataset/parameters in ledger summaries,
  filters, and pagination. Keep immutable source/results separate from labels.

## Q11: the regression suite assumes the user's CLI site uses port 8000

- Type: test-isolation bug. Severity: medium.
- Reproduce: configure CLI site URL http://127.0.0.1:8020, then run
  uv run pytest -m 'not browser' -q.
- Actual: 319 pass, one fails in test_cli_problem_solve_visible_on_site,
  which parses a URL using split("8000")[1]. The CLI-produced result is valid;
  the test raises IndexError before requesting its page.
- Expected: parse the URL path and isolate local CLI configuration in fixtures.
- The actual owner configuration was preserved; it was not changed to hide
  this failure. No application fix was made during the quant campaign.

## Q12: the owner ledger eagerly loads large research results and source bundles

- Type: application scalability issue. Severity: high for repeated campaigns.
- Reproduce: populate this campaign, then render /research/ as its owner using
  review_ui.py. The page has no pagination and queries all result/config fields
  while joining source revisions, although the table shows only small summaries.
- Observed GET-view render: about 3.96 seconds. The review process's cumulative
  peak RSS rose from roughly 308 MiB after the native result to 1,361 MiB after
  the ledger. This is a component measurement, not a multi-user load test.
- 676 sweep trials plus other research grew SQLite to about 418 MiB and saved
  research artifacts to about 983 MiB before final annotations. Disk growth is
  expected evidence retention, but an unbounded ledger should not load it all.
- Fix idea: paginate, select/defer bulky JSON/source fields, add campaign filters,
  and measure query/memory budgets. Archive only with explicit retention policy.

## Q13: aggregate reports overflow on mobile and long chart titles are clipped

- Type: presentation issue. Severity: medium.
- Reproduce: summary run 082587a9-fbf0-4be0-9989-d3a573bdd108 at 390px viewport.
  The findings contain a 64-character freeze hash. Document width is 548px.
  .report-text does not wrap that unbroken token. Plot widths themselves fit.
- Long Plotly titles are also clipped at this width. No KaTeX or JavaScript
  errors were found; the 154-asset final report and 500-variable result render.
- Dense multi-universe category labels are also difficult to read in these
  figures. This is partly report-author layout: use short display labels and
  a universe filter or small multiples, preserving full labels in hover/tables.
- Evidence: screenshots/quant-campaign/summary-mobile.png and the retained
  overflow-diagnostics.json. The report is immutable and remains as a testcase.
- Report-author workaround: group the displayed hash and shorten plot titles in
  the conclusions report, without changing data, models, or final outcomes.
- Fix idea: wrap report tokens safely and put responsive titles outside plots.

## Q14: successful annotations inherit the failed/partial target's exit status

- Type: CLI action/result protocol bug. Severity: high for agent workflows.
- Reproduce: notes add a failed or partial run ID with a new finding, then
  inspect runs show ID. Retained cases: note-Q02/Q03/Q04/Q06/Q07.
- Actual: the annotation is saved, but response ok=false and exit code 1 because
  the target run has failed/partial status. There is no action error. The same
  generic status handling affects reading failed records and other metadata
  operations. Agents may retry a successful mutation and duplicate notes.
- Expected: distinguish command success from the research record's status;
  preserve both fields. Validate by checking the note after the response.

## Q15: a concurrency test hardcodes the test database basename

- Type: test-isolation/configuration bug. Severity: medium.
- Reproduce: the saved regression.py research entry uses an isolated
  LAB_TEST_DATABASE_PATH ending isolated-test.sqlite3, then runs the suite.
- Actual: test_two_cli_processes_share_atomic_holdout asserts the filename
  must literally be test.sqlite3 and fails before exercising the concurrency.
  Saved suite: 318 passed, two failures (this case and Q11), zero errors.
- The ordinary checkout suite had 319 passes and only Q11. Actual campaign
  writes and final reservations succeeded; this is not evidence of a new
  production holdout race. Both JUnit and raw logs are saved as artifacts.
- Expected: compare the configured safe isolated database path, not one name.
- The recorded script returns a research report containing pytest_exit_code=1
  and failures=2; its script-complete status is not a claim the suite passed.

## Research harness corrections (not application bugs)

- Initial synthetic native input used lowercase psd. The app correctly rejected
  it; corrected to the documented PSD domain. Both invocations are retained.
- A first UI harness queried Django after starting Playwright's async loop.
  Django correctly rejected synchronous ORM work there; rendering was moved
  before browser startup. This did not touch application code or final results.

## Expected limits and research caveats

- Native dense covariance at 708 assets exceeds the default 500,000 parameter
  entries. A 500-asset native diagonal-covariance problem succeeds. A structured
  diagonal objective can avoid a dense matrix; synthetic QPs solved 1,000 assets.
- Negative costs, unsupported quarterly schedules, oversized lookbacks,
  impossible caps, and a one-refit budget are rejected and recorded. These are
  deliberate probes, not bugs. Caps of 1% cannot fund a five-asset long portfolio.
- The final holdout supports one opening per data fingerprint. The campaign
  freezes every final candidate and evaluates them together in one research
  batch per dataset, rather than circumventing that rule.
- Current surviving symbols and IEX/Yahoo differences limit interpretation.
  More data/symbols are not independent evidence. One-year validation supports
  exploration, not a profitability guarantee. Cost/cap baselines have different
  economic exposure and must be compared with their actual assumptions.
- Large campaigns duplicate price inputs, source snapshots, runtime metadata,
  and trade histories. Measure disk growth and add explicit archive tooling.
- Research scripts report their own result semantics. A script finishing
  successfully does not certify every nested model or authored equation.
