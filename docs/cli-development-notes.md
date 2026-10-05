# CLI development notes

Use notes add RUN_ID --kind bug|idea|finding --text TEXT to attach observations
to real evidence. Follow-up implementation should cite the run and reproduce
the problem before changing the math.

## Resolved during implementation

- Website and CLI duplicated orchestration: extracted shared services.
- Failed Python attempts disappeared: added durable terminal run evidence.
- Two processes could inspect final data before one saved it: added a unique
  holdout reservation before execution and a real concurrent-process test.
- Registering a directory could re-register generated test/artifact files:
  excluded the configured artifact root as well as hidden/cache directories.
- Finishing a run could overwrite an annotation added while it ran: update
  result fields separately from annotations.
- Mobile charts cropped after a viewport change: observe container widths and
  resize the actual Plotly figure; browser tests check SVG width and screenshots.
- Equal metric names with different units looked comparable: separate rows by
  metric name and unit, and flag differing provenance.
- Python callbacks ignored fixed mode: fit once for fixed allocations, re-fit
  at every scheduled rebalance in rolling mode, and honor the CLI refit budget.
- Native replays could label infeasible/partial results complete: use the same
  outcome accounting as original commands. Execution errors now expose saved
  run links as structured fields.
- The quant campaign's 500-asset SCS result had a large known-answer error
  despite optimal status and feasible constraints. New SCS solves also check
  its reported primal/dual gap relative to the objective scale, and expose the
  gap and limitation on the result page. This is a diagnostic, not an
  independent optimality proof. Older immutable SCS results are marked as such.
- Native rolling quadratic problems at 154 assets hit CVXPY's repeated ARPACK
  PSD certification. The parser now preserves the declared PSD parameter's
  checked domain during quadratic canonicalization. A read-only replay of the
  real 154-asset validation data completed 53 weekly refits after this change.
- Unexpected late numerical refit errors now return a partial path with its
  completed trades, refits, and failing signal/trade date. The evaluation page
  names the stopped refit, and the equal-weight comparator ends on the same day.
- CLI metadata actions now report their own success separately from a saved
  run's failed or partial status. Portfolio source tests run without a dataset.
  Two test fixtures now honor configured site URLs and isolated test DB paths.

## Deliberate limitations and later improvements

- SQLite supports modest concurrency. Short writes and bounded retries handle
  a few agent processes, not a large cluster. Measure contention before changing
  databases.
- Foreground execution has a wall-time budget, not a memory quota or general
  scheduler. Very expensive custom code should use explicit workload budgets.
- Saved artifacts accumulate. Add retention/archive tooling after measuring
  actual disk use; do not silently delete research evidence.
- Seeds cannot make nondeterministic hardware, external I/O, or changing remote
  services reproducible. Capture dependencies as explicit model artifacts.
- Grid search is exploratory. Add nested walk-forward selection and formal
  multiple-testing analysis if the later quant workflow needs those methods.
- Built-in Monte Carlo and bootstrap workflows are deferred. Standalone Python
  research already supports such simulations, with author-reported assumptions.
- Python can contain any mathematics. Only the symbolic CVXPY route provides
  app-checked DCP explanations; Python equations and diagnostics are authored.
- Model artifacts are downloadable evidence, not an automatic model registry
  or website inference service.
