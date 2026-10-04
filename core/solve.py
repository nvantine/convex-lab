"""Solve a fresh compiled problem and return plain, JSON-compatible evidence.

Dual interpretation: Boyd & Vandenberghe §§5.1, 5.6. A dual describes local
sensitivity of this particular objective, not an unconditional asset price.
"""
import platform
import time
import warnings

import cvxpy as cp
import numpy as np

from core.parser import ProblemError

SOLVERS = ("CLARABEL", "OSQP", "SCS")


def plain(value):
    if value is None:
        return None
    array = np.asarray(value, dtype=float)
    return array.tolist() if np.isfinite(array).all() else None


def solve(built, solver="CLARABEL", seconds=2):
    """Use native solver budgets; canonicalization is not a hard time limit."""
    if solver not in SOLVERS or solver not in cp.installed_solvers():
        raise ProblemError("Choose an installed solver: CLARABEL, OSQP, or SCS.")
    if not built.problem.is_dcp():
        raise ProblemError("DCP rules failed. Inspect the explanation and reformulate before solving.")
    options = {
        "CLARABEL": {"time_limit": seconds, "max_threads": 1},
        "OSQP": {"time_limit": seconds, "eps_abs": 1e-7, "eps_rel": 1e-7},
        "SCS": {"time_limit_secs": seconds, "eps_abs": 1e-6, "eps_rel": 1e-6},
    }[solver]
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        try:
            built.problem.solve(solver=solver, verbose=False, ignore_dpp=True, **options)
        except cp.error.SolverError as error:
            raise ProblemError(f"{solver} could not solve this problem. It may be incompatible or have reached a numerical/time limit. Choose another solver. {error}") from None
    status = built.problem.status
    has_solution = status in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE)
    violations = [plain(c["value"].violation()) for c in built.constraints] if has_solution else []
    max_violation = max((float(np.max(v)) for v in violations if v is not None), default=0.0) if has_solution else None
    return {
        "status": status, "optimal_value": plain(built.problem.value),
        "variables": {name: plain(var.value) for name, var in built.variables.items()},
        "constraints": [{"number": i + 1, "source": c["source"], "latex": c["latex"],
                         "dual": plain(c["value"].dual_value),
                         "violation": violations[i] if has_solution else None} for i, c in enumerate(built.constraints)],
        "max_violation": max_violation,
        "verified_optimal": status == cp.OPTIMAL and max_violation is not None and max_violation <= 1e-5,
        "elapsed_seconds": time.perf_counter() - started,
        "solver": solver, "solver_options": options,
        "warnings": [str(w.message) for w in captured],
        "runtime": {"python": platform.python_version(), "cvxpy": cp.__version__, "numpy": np.__version__},
    }
