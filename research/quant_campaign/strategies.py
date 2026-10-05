"""Past-only research policies; deliberately varied, not investment recommendations.

Convex formulations: Boyd & Vandenberghe §4.4.1, §6.3 and §6.4.
All return/covariance inputs use daily simple returns. No live execution APIs.
"""
from time import perf_counter
import numpy as np
import cvxpy as cp
from sklearn.covariance import LedoitWolf
from sklearn.linear_model import Ridge
from core.research import StrategyDecision


FAMILIES = ["equal", "inverse_vol", "min_variance", "mean_variance",
            "momentum", "trend_cash", "entropy", "cvar", "turnover",
            "signed_momentum", "neutral_reversion", "ridge", "risk_cap"]


def target_weights(context, params, state):
    started = perf_counter()
    r = context.history.pct_change(fill_method=None).iloc[1:].to_numpy()
    n = len(context.symbols)
    family = params.get("family", "min_variance")
    if family not in FAMILIES:
        raise ValueError(f"Unknown research family: {family}")
    sample = np.atleast_2d(np.cov(r, rowvar=False, ddof=1))
    cov = sample if params.get("estimator", "ledoit-wolf") == "sample" else LedoitWolf(store_precision=False).fit(r).covariance_
    cov = (cov+cov.T)/2
    vol = np.sqrt(np.maximum(np.diag(cov), 1e-12))
    mu = r.mean(axis=0)*float(params.get("mean_shrinkage", .2))
    gamma = float(params.get("risk_aversion", 8))
    cap = float(params.get("cap", max(.10, 2/n)))
    short = family in ("signed_momentum", "neutral_reversion") or params.get("shorting", False)
    net = float(params.get("net", 0 if family=="neutral_reversion" else 1))
    gross = float(params.get("gross", 1.0 if net==0 else 1.6))
    status, dcp, residual = "analytic", None, 0.
    if family == "equal":
        weights = np.ones(n)/n
    elif family == "inverse_vol":
        weights = (1/vol)/(1/vol).sum()
    elif family == "trend_cash":
        # Inactive positions become cash; never divide active counts to add risk.
        positive = context.history.iloc[-1].to_numpy() > context.history.iloc[-min(63,len(context.history)):].mean().to_numpy()
        weights = positive.astype(float)/n
    else:
        w = cp.Variable(n)
        constraints = [cp.sum(w)==net, w<=cap]
        constraints += [w>=-cap, cp.norm1(w)<=gross] if short else [w>=0]
        risk = cp.quad_form(w, cp.psd_wrap(cov))
        previous = np.array([context.current_weights[s] for s in context.symbols])
        if family in ("momentum", "signed_momentum", "neutral_reversion"):
            k = min(int(params.get("signal_window", 63)),len(r))
            score = r[-k:].mean(axis=0)/vol
            if family == "neutral_reversion": score = -score
            score = score-score.mean()
            mu = .0005*score/(np.std(score)+1e-12)
        elif family == "ridge":
            # Features at t predict returns at t+1. Everything precedes the signal.
            fitted = Ridge(alpha=float(params.get("alpha", 10))).fit(r[:-1],r[1:])
            mu = fitted.predict(r[-1:].copy())[0]*float(params.get("mean_shrinkage", .2))
        if family == "min_variance":
            objective = cp.Minimize(risk)
        elif family == "entropy":
            objective = cp.Minimize(gamma*risk-float(params.get("entropy", 1e-5))*cp.sum(cp.log(w)))
        elif family == "cvar":
            # Rockafellar–Uryasev sample CVaR: convex epigraph of portfolio losses.
            alpha = float(params.get("confidence", .95))
            z = cp.Variable()
            loss = -r@w
            cvar = z + cp.sum(cp.pos(loss-z))/((1-alpha)*len(r))
            objective = cp.Minimize(cvar-float(params.get("return_reward", 0))*mu@w)
        elif family == "risk_cap":
            reference = float(np.ones(n)@cov@np.ones(n)/n**2)
            constraints.append(risk <= reference*float(params.get("risk_multiple", 1.25)))
            objective = cp.Maximize(mu@w)
        else:
            penalty = float(params.get("turnover_penalty", .0003)) if family=="turnover" else 0.
            objective = cp.Maximize(mu@w-gamma*risk-penalty*cp.norm1(w-previous))
        problem = cp.Problem(objective,constraints)
        dcp = problem.is_dcp()
        if not dcp: raise ValueError("Research objective is not DCP.")
        problem.solve(solver=params.get("solver","CLARABEL"))
        status = problem.status
        if status != "optimal" or w.value is None:
            raise ValueError(f"{family}: no verified optimum ({status})")
        weights = np.asarray(w.value)
        residual = max(float(np.max(np.asarray(c.violation()))) for c in constraints)
        if residual > 2e-5: raise ValueError(f"Constraint residual exceeds tolerance: {residual}")
    if not np.isfinite(weights).all(): raise ValueError("Nonfinite weights")
    return StrategyDecision(dict(zip(context.symbols,weights.tolist())), state, {
        "family":family,"solver_status":status,"dcp":dcp,"constraint_residual":residual,
        "net":float(weights.sum()),"gross":float(np.abs(weights).sum()),
        "max_abs_weight":float(np.max(np.abs(weights))),
        "estimated_daily_variance":float(weights@cov@weights),
        "sample_rank":int(np.linalg.matrix_rank(sample)),
        "assets":n,"observations":len(r),"elapsed_seconds":perf_counter()-started,
        "equations":[r"\max_w\ \hat\mu^\top w-\gamma w^\top\hat\Sigma w",
                     r"\mathbf{1}^\top w=b,\quad \|w\|_1\le G\quad\text{(signed policies)}"]})
