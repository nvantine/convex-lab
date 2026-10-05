# Convex Lab

An editable convex optimization notebook. Every example is a symbolic problem:
variables, named constants, an objective, and constraints. The same parsed
expressions produce the CVXPY problem and its displayed KaTeX mathematics.

**Milestones 1–4:** editable LaTeX/expression problems, DCP explanations, 13
examples, solver evidence/duals, Pareto exploration, chosen solutions, isolated
guest workspaces, resumable Alpaca/yfinance batches with local caching, signed
historical rebalancing and rolling re-optimization, saved-result comparisons,
and a concrete server demo guide. Historical market data only; no trading
endpoints, general job queue, or background worker. The research CLI adds
trusted local Python workflows, saved tests, sweeps, and selected guest reports.

## Run locally with uv

From `~/Projects/convex-lab`:

```bash
uv sync --locked
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py create_guest
uv run python manage.py runserver 127.0.0.1:8020
```

Open http://127.0.0.1:8020 and log in. `create_guest` writes credentials to `.local/guest-login.txt`; open that file
locally. On this development laptop the guest has already been created.
The command never prints the password and rerunning it does not reset it.
`.local/`, `.env`, databases, and secrets are ignored by Git.

Synthetic examples need no API keys. Alpaca reuses the existing private
`../portfolio-lab/.env` by default; choosing yfinance requires no keys.
See [credential setup and the data walkthrough](docs/milestone-3.md).
The development secret is generated in
`.local/django-secret`. For your future server, set a new private secret,
`DJANGO_DEBUG=false`, explicit allowed hosts, and HTTPS; do not use runserver for
hosting. Follow [the server demo guide](docs/server-demo.md).

## Try the editor

1. Load **Minimum variance**. The two variance values are 0.01 and 0.04.
2. Inspect the numbered constraints: allocations sum to 1 and are nonnegative.
3. Solve. The known answer is approximately `[0.8, 0.2]`, with variance `0.008`.
4. Clone the result. Click the constraint equation and add `w_0 \le 0.6`,
   check the math, then solve again.
5. Look at that cap's dual: it describes the local benefit of relaxing the cap.
6. Try a signed portfolio, least squares, a linear program, SOCP, or CVaR.

All example data are synthetic teaching values, not investment recommendations.
Means/covariances in portfolio examples are daily quantities. Promoting a
parameter to a variable is supported; some promotions introduce bilinear terms
and will fail the DCP check. Failure to recognize DCP does not prove nonconvexity.

## Explore tradeoffs

Load **Return and risk frontier**, **Return, risk and turnover**, **Return, risk,
turnover and concentration**, or **Least-squares fit and regularization**.
Choose weighted sum or epsilon constraints. Each criterion has its own editable
expression and direction; you may add your own criteria. Click a plotted point,
inspect its mathematics and variables, then save it as the chosen solution.
Ranges describe sampled nondominated values; anchors optimize each criterion
alone. Interpolated lines/surfaces do not represent additional solved problems.

LaTeX editing behaves like a small equation editor: click to see source, type to
preview, click elsewhere to render. Switch to expression syntax with a button;
expressions can embed `latex(r"\mu^{\top}w")`. Only the documented mathematical
subset is supported, with explicit errors for unsupported notation.
See [the input reference and Pareto walkthrough](docs/milestone-2.md).

## Use historical data

Open **Datasets**, choose Alpaca or yfinance, enter actual ticker symbols, and
fetch a date window. The completed request opens a frozen snapshot. Create an
editable portfolio problem from training estimates; choose sample or Ledoit–Wolf
covariance and an optional lookback. Every equation and constant stays editable.
Displays use the minimum grouping needed to preserve mathematical meaning.

Solve, then **Evaluate historical portfolio**. The default **Rolling
re-optimization** re-solves your exact edited problem on a monthly schedule using
126 preceding return observations. Choose daily, weekly, monthly, or hold after
entry, and map which parameters to update. **Restore original weights** supports
trading back to the saved allocation instead. Signed portfolios include explicit
short-borrow, negative-cash financing, and transaction costs on every trade.
Inspect the trade ledger and each re-solve's math and duals. Adjusted prices
approximate total-return exposure; no real trading takes place.

Fetch up to 100 actual stock/ETF tickers in batches of 1–5. The progress page
saves successes locally, supports pause/resume and individual retries, and opens
the completed dataset automatically. Daily owner refresh uses an optional
[after-close server timer](docs/server-demo.md). **Compare** saved experiments
and evaluations using a metrics table, flagged assumptions, and linked equity /
drawdown charts. See [the current walkthrough and methodology](docs/milestone-4.md).

The split is chronological 60/20/20. Training alone estimates parameters;
validation supports exploration. Final prices are hidden until an explicit
confirmation saves one frozen holdout evaluation per identical data fingerprint.
See [current assumptions, accounting, and limitations](docs/milestone-4.md).

## Agent and research CLI

The CLI shares your staff user's notebook with the website. It supports historical
data, symbolic solves/frontiers, trusted local Python strategies and research
scripts, signed portfolio backtests, parameter sweeps, saved pytest evidence,
comparisons, reports, and selected guest publication.

    uv run convex-lab config YOUR_STAFF_USERNAME --site-url http://127.0.0.1:8020
    uv run convex-lab doctor
    uv run convex-lab capabilities
    uv run convex-lab runs list

Follow the [CLI agent guide](docs/cli-agent-guide.md) for the full workflow and SDK.
Successful, partial, and failed research appears under **Research**. Selected
reports appear under **Gallery**. CLI execution is foreground and local; server
agents use the same checkout/database, and remote callers can invoke it over SSH.
There are no account/order integrations or Python upload forms.

The final holdout now records one opening before execution, including failures
and explicit exports, across website and CLI. Source revisions and completed
results remain frozen. [Development notes](docs/cli-development-notes.md) describe
limitations and follow-up ideas.

## Code map

- `core/parser.py`: explicit AST interpreter, declarations, shapes, domain checks,
  math rendering, and DCP diagnostics. No eval/exec or Django imports.
- `core/solve.py`: fresh CVXPY solves, native solver budgets, residuals, duals,
  status, and runtime provenance. Compilation is outside the native time limit.
- `core/latex_input.py`, `notation.py`, `input.py`: safe LaTeX conversion and
  standard mathematical notation, shared with the original expression interpreter.
- `core/pareto.py`, `charts.py`: anchors, scalarization, epsilon constraints,
  tie-breaking, numerical dominance, and views of saved samples.
- `core/presets.py`: ordinary editable problem definitions.
- `core/providers.py`, `data.py`: historical clients, immutable price payloads,
  chronological windows, and training estimates without Django imports.
- `core/evaluation.py`, `rolling.py`: metrics, signed units, exact trade fees,
  schedules, past-only refits, and historical ledgers.
- `core/comparison.py`, `lab/comparison_views.py`: differences and linked charts.
- `lab/fetching.py`, `refresh_datasets`: durable batches, cache and daily refresh.
- `lab/`: forms and views coordinate requests; models store drafts/snapshots.
  `data_views.py` handles the new data/evaluation flows. Models store mutable drafts/fetch progress and frozen numerical evidence.
  Templates use one base and a shared math partial; JavaScript uses the DOM only.
- `core/research.py`, `research_worker.py`, `workflows.py`: typed Python research
  inputs/results, foreground execution, parameter grids, and summaries without Django.
- `lab/cli.py`, `services.py`, `research.py`, `workflows.py`: structured commands,
  shared web operations, versioned source, saved evidence, and campaign coordination.
  Seven custom models total, including the new source revisions and research ledger.
- `config/`: standard Django configuration, routing, and private local settings.
- `tests/`: analytic math tests, Django requests, and real-browser interactions.

Explicit variable-domain constraints are numbered and expose dual values.
Minimize must use convex expressions; maximize must use concave expressions.
Equality constraints must be affine; inequalities must compare convex ≤ concave.
References: [CVXPY DCP](https://www.cvxpy.org/tutorial/dcp/index.html),
[solver support](https://www.cvxpy.org/tutorial/solvers/index.html),
Boyd & Vandenberghe, *Convex Optimization*, §§3.2, 4.2, 4.4, 5.6, 6.3.

## Guests and concurrency

The guest username is shared, but each browser login receives a separate workspace.
Logout ends access to that workspace; logging back in starts a new one. Owner
work persists between browsers. All reads, edits, and clones are scoped on the
server. Guest accounts cannot access Django admin.

Up to five solves or data fetches run at once in one web process. Extra requests receive
a retry message, never a queue. Each solve has new CVXPY objects, and solving is
outside database transactions. SQLite uses WAL and a 30-second busy timeout.
Capacity tests use independent sessions. This is a small single-process demo,
not a benchmark of production traffic or arbitrary large optimization problems.
yfinance fetches are serialized because of the library's shared cookie/session
state; a concurrent request receives a retry message rather than waiting in a queue.

The owner can adjust `LAB_MAX_VARIABLE_ENTRIES` (5000),
`LAB_MAX_PARAMETER_ENTRIES` (500000), `LAB_MAX_AST_NODES` (500), and
`LAB_SOLVE_SECONDS` (2), `LAB_MAX_CRITERIA` (8), `LAB_MAX_FRONTIER_SAMPLES` (50),
and `LAB_FRONTIER_SECONDS` (20), `LAB_MAX_ASSETS` (100), `LAB_MAX_PRICE_ROWS` (5000),
and `LAB_FETCH_SECONDS` (60 per batch), `LAB_CACHE_HOURS` (24),
`LAB_EVALUATION_SECONDS` (45), and `LAB_MAX_REFITS` (300) in `.env`. Restart after changes. These limit
request workload. `LAB_MAX_REQUEST_BYTES` (12000000) allows editable large scenario
arrays. The sweep budget checks between solves; compilation can add time.

## Tests and screenshots

```bash
uv run pytest -q
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run playwright install chromium
uv run pytest -q -m browser
```

Browser tests use a temporary database and synthetic examples, with no market API
calls or credentials. Fourteen new reviewed screenshots are in `screenshots/milestone-4/`; earlier
milestone screenshots are retained as historical records.
Regression-only images go into ignored `.local/browser-regression/` and
`.local/browser-regression-m2/`. Run `uv run pytest -m '' -q` for the complete
serial suite; do not run two Django test processes against the same test database.
Milestone 4 verification: 291 total tests (including 8 Chromium workflows)
passed; Django checks and migration consistency checks passed. Five guest
browser contexts solved simultaneously and could not open one another's results.
Live historical checks for both Alpaca and yfinance returned 1256 price dates
for each of five ETFs over five years. Unit tests cover provider failures without network calls.
See [the short code/math walkthrough](docs/milestone-1.md).
For an existing Chromium-based browser, optionally set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE=/path/to/browser` before the browser test command.

`uv.lock` is canonical; `requirements.txt` is its pinned export (including dev tools).
To refresh the export after an intentional dependency change:

```bash
uv export --no-emit-project --no-hashes --format requirements-txt --output-file requirements.txt
```
