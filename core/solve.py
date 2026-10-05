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


def accepted_solution(result):
    """Treat older SCS records without the objective-scale check as unreviewed."""
    return bool(result.get("verified_optimal")) and (
        result.get("solver") != "SCS" or result.get("relative_duality_gap") is not None
        and result["relative_duality_gap"] <= 0.01
    )


def plain(value):
    if value is None:
        return None
    array = np.asarray(value, dtype=float)
    return array.tolist() if np.isfinite(array).all() else None


def solve(built, solver="CLARABEL", seconds=2):
    """Use native solver budgets; canonicalization is not a hard time limit."""
    if solver not in SOLVERS or solver not in cp.installed_solvers():
        raise ProblemError("Choose an installed solver: CLARABEL, OSQP, or SCS.")
    if built.criteria:
        raise ProblemError('Use Pareto sampling for a multicriterion problem.')
    if not built.problem.is_dcp():
        raise ProblemError("DCP rules failed. Inspect the explanation and reformulate before solving.")
    options = {
        "CLARABEL": {"time_limit": seconds, "max_threads": 1, "tol_gap_abs": 1e-8, "tol_gap_rel": 1e-8, "tol_feas": 1e-9},
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
    # SCS uses absolute tolerances. A tiny portfolio variance can satisfy its
    # default gap tolerance while having a large error relative to the objective.
    # Report its primal/dual gap on the objective's own scale (Boyd §5.5).
    stats = getattr(built.problem, "solver_stats", None)
    extra = getattr(stats, "extra_stats", None)
    info = extra.get("info", {}) if solver == "SCS" and isinstance(extra, dict) else {}
    primal = info.get("pobj") if isinstance(info, dict) else None
    dual = info.get("dobj") if isinstance(info, dict) else None
    relative_gap = None
    if primal is not None and dual is not None and np.isfinite([primal, dual]).all():
        relative_gap = float(abs(primal - dual) / max(abs(primal), abs(dual), 1e-12))
    gap_checked = solver != "SCS" or relative_gap is not None and relative_gap <= 0.01
    accepted = status == cp.OPTIMAL and max_violation is not None and max_violation <= 1e-5 and gap_checked
    warnings_list = [str(w.message) for w in captured]
    if solver == "SCS" and status == cp.OPTIMAL and not gap_checked:
        warnings_list.append("SCS objective-scale duality gap exceeds 1% or is unavailable. Try CLARABEL or rescale the objective.")
    return {
        "status": status, "optimal_value": plain(built.problem.value),
        "variables": {name: plain(var.value) if has_solution else None for name, var in built.variables.items()},
        "constraints": [{"number": i + 1, "source": c["source"], "latex": c["latex"],
                         "dual": plain(c["value"].dual_value) if has_solution else None,
                         "violation": violations[i] if has_solution else None} for i, c in enumerate(built.constraints)],
        "max_violation": max_violation,
        # Legacy JSON key: accepted by these checks, not an independent proof.
        "verified_optimal": accepted,
        "relative_duality_gap": relative_gap,
        "accuracy_check": "SCS objective-scale duality gap <= 1%" if solver == "SCS" else "solver status and constraint feasibility; objective accuracy not independently certified",
        "elapsed_seconds": time.perf_counter() - started,
        "solver": solver, "solver_options": options,
        "warnings": warnings_list,
        "runtime": {"python": platform.python_version(), "cvxpy": cp.__version__, "numpy": np.__version__},
    }
