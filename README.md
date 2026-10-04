# Convex Lab

An editable convex optimization notebook. Every example is a symbolic problem:
variables, named constants, an objective, and constraints. The same parsed
expressions produce the CVXPY problem and its displayed KaTeX mathematics.

**Milestone 1:** problem editor, nine examples, DCP explanations, CLARABEL/OSQP/SCS,
immutable saved experiments, duals, local charts, and isolated guest workspaces.
Pareto exploration, market datasets, historical evaluation, and comparisons are
later milestones. There are no trading endpoints, jobs, workers, or CLI.

## Run locally with uv

From `~/Projects/convex-lab`:

```bash
uv sync --locked
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py create_guest
uv run python manage.py runserver 127.0.0.1:8020
```

Open http://127.0.0.1:8020 and log in. The guest has already been created on this
laptop; its credentials are in `.local/guest-login.txt`. Open that file locally.
The command never prints the password and rerunning it does not reset it.
`.local/`, `.env`, databases, and secrets are ignored by Git.

No API keys are needed in this milestone. The development secret is generated in
`.local/django-secret`. For your future server, set a new private secret,
`DJANGO_DEBUG=false`, explicit allowed hosts, and HTTPS; do not use runserver for
hosting. Server setup is a later milestone.

## Try the editor

1. Load **Minimum variance**. The two variance values are 0.01 and 0.04.
2. Inspect the numbered constraints: allocations sum to 1 and are nonnegative.
3. Solve. The known answer is approximately `[0.8, 0.2]`, with variance `0.008`.
4. Clone the result. Add `w[0] <= 0.6`, check the math, then solve again.
5. Look at that cap's dual: it describes the local benefit of relaxing the cap.
6. Try a signed portfolio, least squares, a linear program, SOCP, or CVaR.

All example data are synthetic teaching values, not investment recommendations.
Means/covariances in portfolio examples are daily quantities. Promoting a
parameter to a variable is supported; some promotions introduce bilinear terms
and will fail the DCP check. Failure to recognize DCP does not prove nonconvexity.

## Code map

- `core/parser.py`: explicit AST interpreter, declarations, shapes, domain checks,
  math rendering, and DCP diagnostics. No eval/exec or Django imports.
- `core/solve.py`: fresh CVXPY solves, native solver budgets, residuals, duals,
  status, and runtime provenance. Compilation is outside the native time limit.
- `core/presets.py`: ordinary editable problem definitions.
- `lab/`: forms and views coordinate requests; models store drafts/snapshots.
  Templates use one base and a shared math partial; JavaScript uses the DOM only.
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

Up to five numerical solves run at once in one web process. Extra requests receive
a retry message, never a queue. Each solve has new CVXPY objects, and solving is
outside database transactions. SQLite uses WAL and a 30-second busy timeout.
Capacity tests use independent sessions. This is a small single-process demo,
not a benchmark of production traffic or arbitrary large optimization problems.

The owner can adjust `LAB_MAX_VARIABLE_ENTRIES` (5000),
`LAB_MAX_PARAMETER_ENTRIES` (100000), `LAB_MAX_AST_NODES` (500), and
`LAB_SOLVE_SECONDS` (2) in `.env`. These limit workload, not portfolio strategies.

## Tests and screenshots

```bash
uv run pytest -q
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run playwright install chromium
uv run pytest -q -m browser
```

Browser tests use a temporary database and synthetic examples, with no market API
calls or credentials. Screenshots are saved under `screenshots/milestone-1/`.
Milestone 1 verification: 80 unit/Django tests plus 2 real Chromium browser tests
passed; Django checks and migration consistency checks passed. Five guest
browser contexts solved simultaneously and could not open one another's results.
See [the short code/math walkthrough](docs/milestone-1.md).
For an existing Chromium-based browser, optionally set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE=/path/to/browser` before the browser test command.

`uv.lock` is canonical; `requirements.txt` is its pinned export (including dev tools).
To refresh the export after an intentional dependency change:

```bash
uv export --no-emit-project --no-hashes --format requirements-txt --output-file requirements.txt
```
