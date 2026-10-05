# CLI milestone 2

The pure SDK in core/research.py describes callback inputs and typed results.
The existing portfolio engine calls Python strategies at the same past-close
signal points used by symbolic refits. Negative weights retain cash, costs,
short-borrow, and financing accounting.

core/research_worker.py imports one frozen local revision in a child process.
lab/research.py handles persistence, source bundles, subprocess lifetime,
checksum manifests, redacted logs, replay, and pytest evidence. Source snapshots
exclude hidden directories, environment files, and generated run artifacts.

Two new models preserve source revisions and run evidence. Failed and interrupted
attempts remain visible. A unique holdout reservation is acquired before code
runs; website evaluations use the same reservation. A data migration imports
older final evaluations into that ledger.

lab/research_views.py and its small templates display runs and source revisions.
Report pages reuse local Plotly and KaTeX, update while running, and download
artifacts only after verifying their checksum.

Examples cover a CVXPY allocation, a lagged Ridge forecast producing signed or
long-only weights, and a seeded simulation. Normal Python dependencies are
managed with uv. This local process execution is not a security sandbox.

API references checked during implementation:

- https://www.cvxpy.org/tutorial/intro/index.html
- https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html
- https://docs.python.org/3.13/library/subprocess.html
- https://docs.pytest.org/en/stable/how-to/output.html
