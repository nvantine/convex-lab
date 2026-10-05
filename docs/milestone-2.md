# Milestone 2: equations and Pareto exploration

## Try it

1. Start the app with `uv run python manage.py runserver 127.0.0.1:8020`.
2. Load **Return and risk frontier**. The input mode defaults to LaTeX.
3. Click an equation to edit its source. While you type, its rendered preview
   appears below. Click elsewhere to fold the source back into mathematics.
4. Check math & DCP. This checks the actual meaning and curvature of the inputs;
   live typesetting alone does not establish a valid optimization problem.
5. Solve & save experiment. Inspect ranges, anchors, and the sample table.
6. Click a point in the chart. Inspect its decision variables, weight vector or
   epsilon bounds, actual solved mathematics, and constraint duals.
7. Save as chosen solution. This creates an immutable snapshot linked to the
   frontier. Repeating this action for the same point returns the same snapshot.
8. Try the epsilon method, return/risk/turnover (3 criteria), four criteria, and
   least-squares tradeoffs. Every criterion and declaration remains editable.

## What each file does

- `core/latex_input.py` converts a finite mathematical LaTeX vocabulary into the
  existing whitelisted expression AST. It does not evaluate Python or run TeX.
- `core/notation.py` writes standard mathematics: quadratic forms, sums, norms,
  transposes, and Greek symbols. It uses compiled shapes to distinguish matrix
  Frobenius norms from spectral norms.
- `core/input.py` converts editable notations. Forms save both canonical solver
  expressions and original input source, so reopening a draft retains what you
  typed. Switching notation explicitly converts the current unsaved problem.
- `core/parser.py` validates declarations, every criterion, and every constraint,
  then builds fresh CVXPY objects and matching math. No Django imports.
- `core/pareto.py` computes anchors, normalization, weighted sums or epsilon
  subproblems, positive tie-breaking, and numerical dominance filtering.
- `core/charts.py` draws views of the saved samples. It performs no optimization.
- `lab/forms.py` collects editable criteria and sampling settings. `views.py`
  calls the pure core, stores results, and scopes inspection/selection by owner
  and workspace. No new custom Django app or queue was added.
- `lab/models.py` still has two models. Experiments now distinguish a single
  solve, a frontier, and a chosen point. A database uniqueness constraint prevents
  duplicate chosen snapshots for a given parent and point.
- `lab/templates/lab/` displays the same math on the editor and results. The
  frontier template adds plots, sample/range tables, and explanations. The small
  DOM script handles clicking to edit equations and clicking to inspect points.
- `tests/` covers known answers, parser safety, failed DCP rules, infeasible or
  unbounded anchors, normalization, dominance, partial sweeps, record isolation,
  every view, and actual browser workflows. Screenshots are in
  `screenshots/milestone-2/`; milestone 1 screenshots remain historical records.

## Supported LaTeX input

Declare every identifier first. Single letters work directly; Greek commands
match Greek-named declarations (`\mu`, `\Sigma`). `\lambda` uses the identifier
`lam` because `lambda` is a Python keyword. Other names use
`\mathrm{risk\_aversion}` or `\mathrm{w\_prev}`. Bold wrappers are allowed.

| Mathematics | LaTeX source | Meaning |
| --- | --- | --- |
| Quadratic form | `w^{\top}\Sigma w` | Recognized `quad_form`, not an uncertified bilinear expression |
| Linear return | `\mu^{\top}w` | Vector inner product |
| Budget | `\sum_i w_i = 1` | Full vector sum equals one |
| Leverage bound | `\|w\|_1 \le 1.5` | Sum of absolute signed allocations |
| Squared error | `\|Ax-b\|_2^2` | Sum of squared residuals |
| Frobenius penalty | `\|X\|_F^2` | Sum of squared matrix entries |
| Fraction | `\frac{1}{2}\|x\|_2^2` | Scalar scaling |
| Positive part | `\max\{x,0\}` | Elementwise maximum with zero |
| Component | `w_0`, `X_{0,1}` | Literal zero-based indexing |
| Slice | `w_{0:2}`, `X_{:,0}` | Literal array slice |
| Elementwise product | `x\odot y` | Product by component; DCP still applies |

Arithmetic, parentheses, equality and non-strict inequalities, transpose, squares,
absolute values, norms (1, 2, infinity, F), full sums/maxima, numeric powers,
`bmatrix` stacks, and the documented row/column reductions are supported.
General TeX macros, arbitrary functions, integrals, bounded sums, strict
inequalities, unknown symbols, and implicit vector products without transpose
are rejected. Rendering in KaTeX is broader than this solver language.
This is deliberately an explicit mathematical parser, not an arbitrary-LaTeX
understanding system. Use expression input when its literal array or atom syntax
is clearer. Shape/type/DCP checks follow conversion in either input mode.

Expression mode also supports literal LaTeX inside atom calls:

```python
quad_form(w, latex(r"\Sigma")) - latex(r"\mu^{\top}w")
```

Only a literal string is accepted by `latex(...)`; it is parsed by the same
subset and whitelist. It is never executed. All mathematical displays use
standard notation regardless of input mode. Existing snapshots are re-rendered
from their frozen specifications without re-solving or changing saved evidence.

## The mathematics

For every criterion, define a minimization-oriented function `g_i`: use `f_i`
for a minimization and `-f_i` for a maximization. Convex multicriterion problems
have convex `g_i` and a convex feasible set. See Boyd & Vandenberghe §§4.7.3–4.7.4;
least-squares tradeoffs are the application in §6.3.

**Weighted sum:** minimize the sum of `a_i*(g_i-z_i)/s_i`, where `a_i>=0`.
The default `z_i` is the single-criterion oriented optimum. The default `s_i`
is the spread from that ideal to the worst oriented value among anchor solutions.
These are anchor-based scales, not the exact global nadir. A near-zero anchor
spread uses scale 1 and is recorded as such; this does not certify a criterion
is constant. Users may disable normalization or supply positive scales.

**Epsilon constraints:** minimize the primary criterion, subject to upper bounds
on other minimization-oriented criteria. In raw units, a maximized return uses
`return >= epsilon`, whereas minimized risk uses `risk <= epsilon`. Incompatible
bounds can be infeasible; those attempts are logged and skipped, not disguised
as results. The anchors are included separately from epsilon-generated points.

Strictly positive weighted sums give Pareto solutions when solved globally,
including for nonconvex problems. Convex problems support every Pareto point with
some nonnegative weights; nonconvex fronts can contain unsupported points.
Zero weights may produce weakly efficient ties. A finite sample of weights never
recovers a complete frontier, even in the convex case. The convex set in the
supporting-hyperplane argument is the upper image, not necessarily the raw image
of the criterion map.

For anchors, zero-weight sums, and epsilon solves, the app minimizes a positive
secondary sum within an explicit primary-optimum bound. Numerical slack starts
at `1e-8 * max(1, abs(primary optimum))`, increasing by factors of ten up to
`1e-5` if the tighter solve is not verified. Every attempt and the actual slack
are saved. The resulting point need not attain the primary optimum exactly;
range tables therefore report the single-criterion optimum separately.
No inaccurate result is presented as a verified optimum.

Secondary constraint duals refer to the secondary objective, including its
primary-optimum bound. Primary evidence is saved separately. Inspecting a point
shows both problems and identifies which one produced the displayed duals.

**Dominance:** compare every oriented criterion after anchor-based scaling.
Tolerance is `1e-6` in those scaled units; equivalent points are deduplicated.
The reported samples are nondominated among computed candidates. This numerical
filter is not a proof of mathematical Pareto optimality or full frontier coverage.

2D shading marks points dominated by displayed samples. Dotted connecting segments
and the optional 3D mesh interpolate visually; points between samples were not
solved and should not be assumed feasible. Above three criteria, parallel
coordinates and a pairwise matrix complement the 3D projection with the fourth
criterion as color. Projections can hide dominance in undisplayed dimensions;
the table and filtering always use all criteria.

## Budgets and verification

Default: 20 requested candidates in the form, at most 50 per request, at most 8
criteria, a 20-second sweep budget, and a 2-second native budget per numerical
solve. Anchors count toward the candidate budget; tie-breaking can make multiple
solver calls. Duplicate or infeasible candidates reduce the displayed count.

The owner can change `LAB_MAX_FRONTIER_SAMPLES`, `LAB_MAX_CRITERIA`,
`LAB_FRONTIER_SECONDS`, and `LAB_SOLVE_SECONDS` in a private `.env` and restart.
There are no strategy restrictions within the editable language. These caps bound
request workload. The total budget is cooperative between solves; compilation
and a solver stopping late mean it is not a hard wall-clock deadline. If anchors
cannot finish, the form reports an error; otherwise completed points are retained
as an explicitly incomplete experiment when the budget ends. No background work.

On this laptop, the four-criterion synthetic preset with 50 candidates completed
in about 0.4 seconds (weighted) and 0.6 seconds (epsilon). This measures those
small teaching examples, not arbitrary larger problems or hosting capacity.

Library APIs checked against official documentation:
[CVXPY DCP](https://www.cvxpy.org/tutorial/dcp/index.html),
[problem API](https://www.cvxpy.org/api_reference/cvxpy.problems.html),
[KaTeX rendering](https://katex.org/docs/api.html),
[Plotly events](https://plotly.com/javascript/plotlyjs-events/),
[parallel coordinates](https://plotly.com/python/parallel-coordinates-plot/),
[scatterplot matrices](https://plotly.com/python/splom/),
[3D mesh](https://plotly.com/python/3d-mesh/), and
[Django constraints](https://docs.djangoproject.com/en/6.1/ref/models/constraints/).
Book references were checked from the corresponding sections of the local Boyd
PDF; the copyrighted PDF is not in this repository.

Stop here for review. Historical data and fixed-holdings evaluation are milestone 3;
comparisons and hosting documentation are milestone 4.
