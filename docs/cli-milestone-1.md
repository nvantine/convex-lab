# CLI milestone 1

lab/services.py coordinates problem creation, solving, frontier choices, and
historical evaluations. Both the website and CLI call it; the numerical work
still lives in pure core/ functions.

lab/workspaces.py provides an explicit owner/workspace pair. A staff user's CLI
results belong to the same notebook as their website results.

lab/cli.py provides structured commands and JSON responses. Configure with
uv run convex-lab config YOUR_STAFF_USERNAME, then inspect the command help.

Tests exercise saved results, scope checks, DCP errors, training-only estimates,
backtests, and mocked resumable market-data fetching. Custom Python and the
durable research ledger follow in milestone 2.
