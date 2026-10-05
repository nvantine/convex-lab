# Convex Lab instructions

Build a small, understandable learning app. Follow the user's approved plan;
complete milestones in small commits. The latest user request authorizes finishing
all remaining approved milestones in this turn. Use uv for Python,
environments, dependencies, and tests. Make small conventional commits and
report git status/log, verification, screenshots, and limitations.

`core/` is pure Python with no Django imports. `lab/` is the single custom Django
app. Interpret whitelisted AST nodes explicitly; never use eval/exec in the
symbolic parser or hide constraints outside the editable specification.
The approved CLI plan allows trusted local Python files and packages through
an explicit research SDK. Keep that execution separate from the web parser;
do not execute Python uploaded through website forms.
Math rendering and solver construction must share the parsed expressions.

No trading/accounts/positions endpoints. The approved CLI shares the owner's
workspace with Django and supports saved research and tests. The earlier user
request adds resumable browser batch fetching, an optional scheduled Django data
refresh command, and historical rolling re-optimization/rebalancing. Keep solves
synchronous and avoid a general worker/queue. Preserve immutable experiments and per-session guest
workspaces. Scope private record lookups and mutations by user AND workspace;
the read-only gallery exposes only explicitly published report outputs.
Solves run outside database transactions using fresh CVXPY objects.

For agent research, read docs/cli-agent-guide.md and use the CLI's JSON protocol.
Save source revisions, tests, runs, reports, and findings through those commands
so the owner can inspect them on the website. Use validation for exploration;
final holdout use requires explicit confirmation and remains recorded on failure.
Record reproducible bugs and future ideas in run notes and
docs/cli-development-notes.md. Do not silently change research code or assumptions.

Never print or commit secrets, private databases, or real account passwords.
Use ignored .env/.local files and placeholder examples. Verify current official
library APIs when adding functionality. Reference book sections in math comments;
do not commit copyrighted books or claim to have read entire books from excerpts.

Run unit and Django tests, manage.py check, and real Playwright tests for each
milestone. Save screenshots and inspect them visually; fix math, charts, overflow,
console errors, and error-path bugs. Browser fixtures use synthetic data and an
isolated test database. Explain each group of files in plain English.
