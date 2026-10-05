# CLI for agents and humans

## Start here

Run the CLI in the same checkout as Django. It shares SQLite and your staff
user's existing notebook. Django need not be running for CLI computations.
Start the website when you want to inspect the results.

    cd ~/Projects/convex-lab
    uv sync --dev
    uv run manage.py migrate
    uv run convex-lab config YOUR_STAFF_USERNAME --site-url http://127.0.0.1:8020
    uv run convex-lab doctor
    uv run convex-lab whoami
    uv run convex-lab capabilities
    uv run manage.py runserver 127.0.0.1:8020

Use your existing superuser username in config. Config writes ignored
.local/cli.json, containing only owner and website URL. An agent running locally
does not need your website password. This is a trusted local interface; normal
website login and independent guest sessions continue to apply.

For a server agent, use the same commands inside its server checkout. From
another machine, invoke them over SSH:

    ssh YOUR_SERVER 'cd ~/Projects/convex-lab && uv run convex-lab runs list'

There is no separate agent environment, HTTP API, socket, scheduler, or worker.
Use uv for dependencies; add a needed modeling library deliberately with uv add.

## Command protocol

JSON is the default. Every response has schema_version, ok, and data or error.
Progress goes to stderr. Python prints go into saved logs, never into CLI JSON.
Use --human before the command to pretty-print. --owner before the command
overrides local configuration.

Exit codes: 0 complete; 1 failed/partial execution; 2 invalid input or already
opened holdout; 3 retryable database error; 130 interruption. For unsuccessful
research, inspect its saved run ID and error; use runs show ID --logs.
Execution errors include error.run_id and error.run_url when a run was saved.
A running response from an idempotent retry means the original process is still
working: inspect that run instead of starting another.

    uv run convex-lab --human runs list
    uv run convex-lab runs show RUN_ID --logs
    uv run convex-lab --idempotency-key research-001 research run REVISION_ID

Object arguments --params, --options, and --grid accept inline JSON, @filename,
or - for stdin. Symbolic --file accepts a filename or -. For an entire
invocation, --input accepts JSON with an argv array:

    {"argv": ["research", "run", "REVISION_ID", "--params", "@parameters.json"]}

    uv run convex-lab --input invocation.json

The capabilities response includes supported commands, atoms, solvers, exit
codes, and the [ResearchResult JSON schema](../core/research.schema.json).

## Data and symbolic problems

Both providers use historical adjusted daily prices only. Existing Alpaca
credentials remain private and are loaded as before; doctor reports a boolean.
Alpaca uses explicit IEX/all adjustments. Yahoo is an explicit alternative.

    uv run convex-lab datasets fetch --source alpaca --symbols SPY,AGG,QQQ --start 2021-01-01 --end 2026-10-02 --name "Research prices"
    uv run convex-lab datasets list
    uv run convex-lab datasets status FETCH_ID
    uv run convex-lab datasets resume FETCH_ID --retry-errors
    uv run convex-lab datasets resume FETCH_ID --save-available
    uv run convex-lab datasets refresh FETCH_ID

Fetches use batches of at most five, keep successes, and return partial status
when a complete aligned dataset could not be saved. A refresh creates another
frozen snapshot; it never changes old evaluations. --refresh-daily opts a fetch
into the existing after-close refresh command, if you schedule that command.

    uv run convex-lab problems create --dataset DATASET_ID --template min-variance --name "Training problem"
    uv run convex-lab problems check PROBLEM_ID
    uv run convex-lab solve PROBLEM_ID
    uv run convex-lab backtest EXPERIMENT_ID --dataset DATASET_ID --options '{"frequency":"weekly","lookback":126,"cost_bps":10}'

Training imports estimate parameters only from the first 60% of returns.
Symbolic backtests default to monthly rolling re-optimization. Use options
mode=fixed to restore the original weights instead.

To start without data, use problems create --preset min-variance --name NAME.
Presets prints the catalog; presets NAME prints its editable specification.
Problems can be updated, cloned, shown, or checked; existing experiments freeze
their own specification. --file problem.json --language latex accepts the
existing mathematical LaTeX subset. The website shows the resulting mathematics.

For multiple criteria, use frontier PROBLEM_ID --options '{"samples":10}',
then choose EXPERIMENT_ID --point POINT_ID. Backtest a saved chosen point.
Its frozen tie-breaking constraints remain part of the policy.

## Write your own Python

Registration does not execute code. Register a file, or a directory to include
helper modules, tests, and dependency manifests. Hidden files, environment files,
generated artifacts, and symlinks are excluded. Binary inputs are external
dependencies; copy needed evidence into the artifact directory yourself.

    uv run convex-lab strategies register examples/research --entry-point min_variance.py:target_weights --interface portfolio --name "Editable CVXPY allocation"
    uv run convex-lab tests run REVISION_ID
    uv run convex-lab backtest REVISION_ID --dataset DATASET_ID --params '{"shorting":true}' --options '{"frequency":"weekly","lookback":126,"cost_bps":10}'

Changing local code does not change a registered revision. Register again to
create a new source snapshot and checksum.

### Portfolio callback

    from core.research import StrategyDecision

    def target_weights(context, params, state):
        weights = {symbol: 1 / len(context.symbols) for symbol in context.symbols}
        return StrategyDecision(weights, state, {"explanation": "Equal weights"})

context contains:

- history: an ordered pandas price frame ending at the signal close;
  lookback counts return observations, so the frame has lookback + 1 prices.
- symbols: the exact dataset column order.
- signal_date and current_weights: prior-close information.
- rng: a seeded NumPy generator shared across this run's callbacks.
- artifact_dir: a directory for model files and other evidence.
- options: the actual rebalance and cost assumptions used by this backtest.

state can be any ordinary Python object, including a fitted model. It survives
between callbacks within that process. Persist a model file explicitly if you
want it available afterward; website views never load model artifacts.

Every weight must be finite, keyed by the dataset's exact symbols. Negative
weights are allowed. There is no implicit long-only constraint, cap, or
sum-to-one constraint. Cash is 1 minus the sum of weights. The engine handles
the same transaction costs, borrowing, and financing as symbolic evaluations.
Signals use a preceding close and trade at the next close. Daily, weekly,
monthly, and hold-after-entry schedules are available.
Python portfolios default to rolling mode: call the model at each rebalance.
Choose options mode=fixed to fit once and restore that initial allocation on
later rebalances instead.
The backtest --max-refits budget applies to both Python and symbolic rolling
policies; it defaults to 10,000 for this local CLI.

Examples include CVXPY minimum variance and lagged Ridge predictions. They are
small illustrations, not claims of profitable strategies. Agent-written Python
can implement other models without fitting a fixed strategy catalog.

### Standalone research

    from core.research import ResearchResult

    def run(context, params):
        score = float(context.rng.normal())
        return ResearchResult(
            metrics={"score": {"value": score, "unit": "ratio", "direction": "none"}},
            text="Explain what was measured and its limitations.",
            equations=[r"x^2"],
        )

    uv run convex-lab strategies register examples/research --entry-point simulation.py:run --interface research --name "Simulation"
    uv run convex-lab research run REVISION_ID --params '{"count":1000}' --seed 42

Research context provides prices through the selected window, training prices,
symbols, window, rng, and artifact_dir. Data is optional for pure simulations.
Unlike the portfolio callback, a research script can inspect the entire chosen
validation window; its results are labeled script-reported.

ResearchResult accepts scalar metrics with explicit units, tables with columns
and equal-length rows, Plotly figure JSON, text, LaTeX equations, and relative
artifact filenames. Author-supplied equations describe the model; they do not
automatically certify DCP. No executable HTML is accepted as a chart.

## Sweeps and robustness

    uv run convex-lab sweep REVISION_ID --dataset DATASET_ID --grid '{"params.alpha":[0.1,1,10],"options.cost_bps":[0,10,30]}' --seeds '[42,43,44]' --metric sharpe --direction maximize --options '{"frequency":"weekly","lookback":126}'

For symbolic problems, use parameters.PARAMETER_NAME instead of params.NAME.
For standalone scripts, use their metric name, such as sample_mean. Two grid
dimensions produce a heatmap of medians across seeds. Every attempt is retained,
including failed candidates, along with the number planned/not started.
Trials run serially; default maximum is 100 and can be changed with --max-trials.
--timeout is the total campaign budget, not a separate budget for every trial.

Ranking uses completed validation trials with matching units. Failed and partial
trials remain in the table but do not compete for best result. Many trials can
overfit validation. Repeating deterministic CVXPY allocations with different
seeds provides no independent robustness evidence.

## Holdout, comparisons, and sharing

The chronological split stays 60/20/20. By default, exports and research do not
include final prices. Final use requires both flags:

    uv run convex-lab backtest REVISION_ID --dataset DATASET_ID --window holdout --confirm-holdout

The website and CLI reserve one opening per owner/workspace/data fingerprint,
before executing research or exporting final data. Failed final attempts remain
recorded; the window is no longer untouched. Sweeps always use validation.
These are research-protocol checks; arbitrary trusted Python can read local
files independently, so this does not claim to sandbox it or prove absence of
look-ahead bias.

    uv run convex-lab compare RUN_ID_1 RUN_ID_2
    uv run convex-lab report RUN_ID_1 RUN_ID_2 --title "Agent findings" --text "Describe the experiment and conclusions."
    uv run convex-lab notes add RUN_ID --kind idea --text "Investigate this limitation next."
    uv run convex-lab publish REPORT_RUN_ID
    uv run convex-lab unpublish REPORT_RUN_ID

Compare returns a website URL, metrics with units, differences, and charts.
Portfolio comparisons share a date axis. Other research charts are displayed
individually, because arbitrary chart axes cannot safely be assumed equivalent.
Report saves a human-facing summary and can also write Markdown with --output.

Your Research tab shows all owner CLI runs. Only selected publications appear in
Gallery for logged-in guests. Publication shares report text, metrics, equations,
charts, and tables; review their content before publishing. Private source,
logs, artifacts, annotations, and owner-only links are excluded.

## Reproduce and diagnose

    uv run convex-lab runs show RUN_ID --logs
    uv run convex-lab runs replay RUN_ID
    uv run convex-lab runs export RUN_ID --output /tmp/convex-lab-run-export
    uv run convex-lab runs recover RUN_ID

Runs record parameters, seeds, data fingerprints, frozen source, installed package
versions, application code digest, and Git commit. Replay supports Python runs,
pytest runs, symbolic solves/frontiers, and saved symbolic validation backtests.
It refuses holdout replays and detects runtime/code changes. Restore versions
or deliberately pass --allow-version-mismatch to acknowledge the difference.
Data operations, reports, and entire campaigns are repeated using their saved
configuration; a campaign's individual trials can be replayed.

Default custom-run timeout is ten minutes and is configurable up to one day.
Timeout, Ctrl-C, or SIGTERM stops the child process group and retains diagnostic evidence.
recover marks a run interrupted only when its recorded local process has ended;
it never silently starts the code again.

pytest executes the frozen source bundle with a per-run test database. Its
JUnit summary, individual failures, and output logs are saved. --pytest-args
accepts a JSON array, for example ["-q","-k","weights"]. This command tests your
registered bundle; the application suite remains uv run pytest.

Artifacts live under ignored .local/research/RUN_ID. Export copies only files
matching the manifest checksum into a new directory. Known loaded secrets are
redacted from captured text. Keep external model dependencies and data sources
documented: arbitrary external I/O and different hardware can defeat exact
reproduction even with matching seeds.
