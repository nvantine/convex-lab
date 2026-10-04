# Milestone 1 screenshots

Captured by `uv run pytest -q -m browser` using the downloaded Playwright
Chromium 153.0.8010.12. All inputs are synthetic test fixtures; no credentials or
market data appear in these files. The browser test uses a temporary database.

1. Login form.
2. Empty guest workspace.
3. Editable declarations and rendered minimum-variance problem.
4. Known-answer result with math beside numerical values.
5. Expanded Plotly chart.
6. Non-DCP objective and rule explanation.
7. Invalid syntax.
8. Infeasible problem: no solution or shadow prices.
9. Missing named parameter.
10. Parameter promoted into a decision variable.
11. CVaR editor at mobile width.
12. Minimum-variance result at mobile width.
13. Saved experiments at mobile width.

Visual review checked math, charts, constraint numbering, error messages, readable
forms/tables, and page overflow. Review led to a two-column result layout on wide
screens, compact numeric displays with full precision retained, and horizontal
scrolling for wide mobile tables. It also identified infeasibility certificates
being shown as shadow prices; those are now hidden and covered by a regression test.

The tests also check every preset, declaration editing, JSON errors, cloning,
logout, JavaScript console errors, local-only page assets, and five simultaneous
guest browsers with separate records and denied cross-workspace access.
