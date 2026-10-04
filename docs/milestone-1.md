# Milestone 1: following one solve

## What the files do

The **core** is a small mathematical interpreter. `presets.py` holds examples as
ordinary dictionaries. `parser.py` creates fresh variables and parameters,
interprets each expression, and builds both the optimization problem and the
LaTeX representation. DCP diagnostics explain which expression or constraint
cannot be certified by the composition rules. `solve.py` chooses the requested
solver and extracts numerical values, residuals, status, and duals.

The **Django app** stores an editable `Problem` and an immutable `Experiment`.
`forms.py` collects declarations and expressions; `views.py` calls the core and
saves the returned evidence. `workspaces.py` prevents shared guest credentials
from becoming shared mutable data. Templates show the same preview on the editor
and the result. JavaScript improves the declaration form, renders local KaTeX,
and draws/expands local Plotly charts; it implements no optimization mathematics.

The **configuration** supplies authentication, sessions, SQLite, private secrets,
and adjustable workload budgets. The **tests** check mathematical known answers,
invalid specifications, status handling, saved evidence, access boundaries, and
real browser interactions.

## The mathematical examples

For minimum variance with covariance diag(a,b) and weights summing to one,
substitute w2=1-w1. Differentiate a*w1²+b*(1-w1)² to get w1=b/(a+b).
For a=.01,b=.04, the result is (.8,.2) and variance .008. This is the analytic
answer used in tests, independent of CVXPY.

A cap w1≤.6 binds at (.6,.4). Its multiplier measures how much the minimized
objective decreases if the cap is relaxed slightly. For a constraint g(x)≤b,
locally dv/db=-lambda for minimization; reverse the objective-value interpretation
for maximization. Equality multipliers can be positive or negative.
See Boyd & Vandenberghe §§4.4.1, 5.6.

For least squares, compare against NumPy's independent `lstsq` result. The SOCP
example minimizes t subject to ||x||₂≤t and x=(3,4), so its optimum is exactly 5.
Regularized least squares adds a penalty on coefficient size (Boyd §6.3).

CVaR uses t + sum(u)/(N*(1-alpha)), with u≥0 and u≥loss-t. The example uses four
synthetic return scenarios and alpha=.95. If you change the rows in R, update N;
if you change alpha, choose 0<alpha<1. The generic editor allows other values,
but then the expression may no longer represent the stated statistical CVaR.
See Rockafellar & Uryasev, *Optimization of Conditional Value-at-Risk* (2000).

## Limits to remember

DCP is a sufficient certificate, not a complete convexity oracle. For example,
`x*x` fails the multiplication rule, whereas `square(x)` is recognized.
Parameter domains are assertions checked against supplied values; `free` does
not certify a nonnegative multiplier simply because its current value is 2.
Declare `nonneg` if that sign is part of your mathematical assumption.

Variable domains become numbered explicit constraints so their duals are visible.
We do not duplicate those constraints with hidden CVXPY attributes; duplicate
constraints can split multipliers and confuse sensitivity interpretation.

The editor accepts continuous real scalar/vector/matrix variables. It accepts a
small atom vocabulary and does not run arbitrary Python. This protects the server;
all variables, parameter values, dimensions, expressions, and feasible-set
constraints within that vocabulary remain editable. Future atoms can be added
with explicit parser/rendering rules and tests.

Solver time limits cover numerical execution, not a strict end-to-end request
kill. Compilation adds time. Capacity is limited to five active solves in one
process. Neither an inaccurate status nor an exhausted budget is described as a
verified optimum. Generic large problems require discussion before increasing
budgets or introducing infrastructure.

Historical data, signed cash/carry evaluation, holdout access, Pareto exploration,
and result comparisons are not part of this milestone.
