"""Editable CVXPY example: Boyd & Vandenberghe §4.4.1."""
import cvxpy as cp
from sklearn.covariance import LedoitWolf
from core.research import StrategyDecision


def target_weights(context, params, state):
    returns = context.history.pct_change(fill_method=None).iloc[1:].to_numpy()
    covariance = LedoitWolf().fit(returns).covariance_
    w = cp.Variable(len(context.symbols))
    constraints = [cp.sum(w) == params.get("net_exposure", 1.0)]
    # These are example policy choices, visible here and editable in your code.
    if not params.get("shorting", False): constraints.append(w >= 0)
    if "cap" in params: constraints.append(w <= params["cap"])
    problem = cp.Problem(cp.Minimize(cp.quad_form(w, covariance)), constraints)
    problem.solve(solver="CLARABEL")
    if problem.status != "optimal": raise ValueError(f"Optimization failed: {problem.status}")
    return StrategyDecision(dict(zip(context.symbols, w.value.tolist())), diagnostics={
        "solver_status":problem.status, "objective":problem.value, "is_dcp":problem.is_dcp(),
        "duals":[c.dual_value for c in constraints], "equations":[r"\min_w w^\top\Sigma w"]})
