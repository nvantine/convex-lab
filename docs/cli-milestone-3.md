# CLI milestone 3

core/workflows.py builds deterministic parameter grids and descriptive summaries.
lab/workflows.py runs trials in the foreground, saves every attempted child, and
uses the same backtest services as individual commands. Campaigns rank completed
validation evidence only; a timeout or failed candidate remains visible.

The comparison view now exposes a shared comparison context for CLI and website.
Research metrics carry explicit units, and portfolio paths share a date axis.
Generic research charts remain separate rather than assuming matching semantics.

The owner can save a report and publish selected outputs to a guest gallery.
Guest sessions cannot access source, logs, artifacts, or owner-only run pages.
Reports and notes give the later quant workflow a place to explain findings and
record problems without changing this application's code automatically.

The agent guide documents setup, structured inputs, the SDK, all command groups,
research accounting, holdout use, replay, artifact exports, and limitations.
See cli-development-notes.md for resolved defects and future ideas.

## Final verification

On 2026-10-05:

- uv run pytest -m 'not browser' -q: 320 passed.
- uv run pytest -m browser -q: 11 passed, with real Chromium and an isolated
  Django test server. Screenshots are in screenshots/cli/milestone-1 through
  milestone-3; existing data/backtest comparison screenshots were refreshed.
- Reviewed the owner ledger, source snapshots, failures, mathematics, charts,
  sweep rankings, comparisons, guest gallery, and mobile reports visually.
- manage.py check passed, migrate had no pending migrations, and
  makemigrations --check --dry-run found no model changes.
- uv build --offline produced a wheel/source distribution; the wheel includes
  the console entry point, schema, templates, local assets, and migrations.
- Confirmed all core modules have no Django imports and candidate Git files
  contain no matches for the loaded Django/Alpaca secrets.

Regression checks include signed portfolios, rolling versus fixed allocations,
Python refit budgets, source replay, failed/infeasible replay status, callback
history truncation, artifact checksums, secret redaction, pytest failures, failed
grid trials, different metric units, shared holdout claims, real concurrent CLI
processes, SIGTERM cleanup, and private owner routes for guests.

Tests use synthetic prices and mocked providers. They do not demonstrate live
provider availability or investment performance. One upstream websockets.legacy
deprecation warning remains; it does not affect test results.
