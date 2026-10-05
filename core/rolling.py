"""Historical close-to-close simulation with signed trades and past-only refits.

The edited symbolic problem remains the policy (Boyd §4.4.1); no strategy name
selects hidden constraints. Signals use the preceding close and trade one close
later. This is simulated research, never an account or execution client.
"""

from copy import deepcopy
from time import monotonic
import numpy as np
import pandas as pd
import sklearn
from sklearn.covariance import LedoitWolf
from core.data import content_digest, price_frame, split_windows
from core.evaluation import evaluation_settings, metrics
from core.parser import ProblemError, build_problem, Limits
from core.solve import solve


BINDINGS = (
    "mean_parameter",
    "covariance_parameter",
    "returns_parameter",
    "scenario_count_parameter",
    "previous_weights_parameter",
    "scenario_variable",
)


def rebalance_indices(dates, frequency):
    if frequency not in ("hold", "daily", "weekly", "monthly"):
        raise ProblemError("Choose hold, daily, weekly, or monthly rebalancing.")
    points = [0]
    for i in range(1, len(dates) - 1):  # No new trade at the final marking close.
        previous, current = dates[i - 1], dates[i]
        changed = (
            frequency == "daily"
            or frequency == "weekly"
            and previous.isocalendar()[:2] != current.isocalendar()[:2]
            or frequency == "monthly"
            and (previous.year, previous.month) != (current.year, current.month)
        )
        if changed:
            points.append(i)
    return points


def refit_spec(spec, payload, signal_index, previous_weights, options):
    """Reconstruct the exact problem using only prices through signal_index."""
    lookback = options.get("lookback", 126)
    if type(lookback) is not int or not 2 <= lookback <= signal_index:
        raise ProblemError(
            f"Lookback must be between 2 and {signal_index} past return observations at entry."
        )
    frame = price_frame(payload).iloc[signal_index - lookback : signal_index + 1]
    returns = frame.pct_change(fill_method=None).iloc[1:].to_numpy()
    estimator = options.get("estimator", "ledoit-wolf")
    if estimator == "sample":
        covariance = np.atleast_2d(np.cov(returns, rowvar=False, ddof=1))
    elif estimator == "ledoit-wolf":
        covariance = LedoitWolf(store_precision=False).fit(returns).covariance_
    else:
        raise ProblemError("Choose sample covariance or Ledoit–Wolf.")
    values = {
        "mean_parameter": returns.mean(axis=0).tolist(),
        "covariance_parameter": ((covariance + covariance.T) / 2).tolist(),
        "returns_parameter": returns.tolist(),
        "scenario_count_parameter": lookback,
        "previous_weights_parameter": list(previous_weights),
    }
    changed = deepcopy(spec)
    parameters = {p["name"]: p for p in changed["parameters"]}
    targets = []
    for role, value in values.items():
        name = options.get(role, "")
        if name:
            if name not in parameters:
                raise ProblemError(
                    f"{role}: choose a declared parameter or leave it blank."
                )
            if name in targets:
                raise ProblemError(
                    "Different rolling inputs must map to different parameters."
                )
            targets.append(name)
            parameters[name]["value"] = value
    if not targets:
        raise ProblemError(
            "Rolling optimization needs at least one explicitly mapped market parameter."
        )
    auxiliary = options.get("scenario_variable", "")
    if auxiliary:
        variable = next(
            (v for v in changed["variables"] if v["name"] == auxiliary), None
        )
        if variable is None:
            raise ProblemError(
                "Choose a declared scenario variable, or leave it blank."
            )
        variable["shape"] = [lookback]
    evidence = {
        "lookback": lookback,
        "estimator": estimator,
        "first_return": str(frame.index[1].date()),
        "last_return": str(frame.index[-1].date()),
        "signal_index": signal_index,
        "parameter_digest": content_digest(changed["parameters"]),
        "estimator_versions": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit-learn": sklearn.__version__,
        },
    }
    return changed, evidence


def trade_to_weights(equity, notional, weights, cost_fraction):
    """Solve v + c*sum(abs(v*w-current_notional)) = equity exactly by segments.

    This convex piecewise-linear fee equation includes buys and sells. Choose the
    largest feasible post-cost equity; breakpoints avoid assumptions about leverage.
    """
    weights = np.asarray(weights, dtype=float)
    notional = np.asarray(notional, dtype=float)
    if equity <= 0 or not np.isfinite(equity):
        raise ProblemError("Cannot rebalance nonpositive equity.")
    if not np.isfinite(weights).all():
        raise ProblemError("Rebalance weights must be finite.")
    if cost_fraction == 0:
        return float(equity), weights * equity - notional
    points = [0.0, float(equity)]
    for old, target in zip(notional, weights):
        if target != 0 and 0 < old / target < equity:
            points.append(float(old / target))
    points = sorted(set(points))

    def residual(value):
        return float(
            value + cost_fraction * np.abs(value * weights - notional).sum() - equity
        )

    for i in range(len(points) - 1, 0, -1):
        high, low = points[i], points[i - 1]
        f_high, f_low = residual(high), residual(low)
        if f_high >= 0 and f_low <= 0:
            value = (
                high
                if f_high == 0
                else low
                if f_low == 0
                else low - f_low * (high - low) / (f_high - f_low)
            )
            return float(value), value * weights - notional
    raise ProblemError(
        "Trading costs leave no positive feasible equity for this rebalance."
    )


def portfolio_path(
    payload,
    weights,
    window="validation",
    options=None,
    spec=None,
    variable="w",
    limits=None,
    seconds=45,
    maximum_refits=300,
    stop_after=None,
    strategy=None,
    artifact_dir=None,
    seed=42,
    windows=None,
):
    options = evaluation_settings(options or {})
    mode = options.get("mode", "fixed")
    frequency = options.get("frequency", "hold")
    if mode not in ("fixed", "rolling"):
        raise ProblemError("Choose original weights or rolling re-optimization.")
    if window not in ("validation", "holdout"):
        raise ProblemError("Choose validation or explicitly confirm the final holdout.")
    weights = np.asarray(weights, dtype=float)
    if weights.shape != (len(payload["symbols"]),) or not np.isfinite(weights).all():
        raise ProblemError("Choose one finite weight per asset.")
    span = (windows or split_windows(payload))[window]
    all_prices = price_frame(payload)
    prices = all_prices.iloc[span["start"] + 1 : span["end"] + 1]
    scheduled = set(rebalance_indices(prices.index, frequency))
    if stop_after is not None:
        prices = prices.iloc[:stop_after]
        scheduled = {i for i in scheduled if i < len(prices)}
    if mode == "rolling" and strategy is None:
        if spec is None or "objective" not in spec:
            raise ProblemError(
                "Rolling optimization needs a saved scalar problem or chosen frontier solution."
            )
        if options.get("scenario_variable") == variable:
            raise ProblemError(
                "The scenario auxiliary cannot be the asset-weight variable."
            )
        if len(scheduled) > maximum_refits:
            raise ProblemError(
                f"This schedule needs {len(scheduled)} solves; the current request limit is {maximum_refits}. Use a less frequent schedule or adjust the owner budget."
            )
    units = np.zeros(len(weights))
    cash = 1.0
    previous_equity = 1.0
    start = monotonic()
    wealths = []
    returns = []
    trades = []
    refits = []
    borrow_total = financing_total = 0.0
    status = "complete"
    warnings = []
    initial_weights = None
    state = None
    rng = np.random.default_rng(seed)
    for i, (day, row) in enumerate(prices.iterrows()):
        target = weights.copy()
        refit_index = None
        if i in scheduled and strategy is not None:
            from pathlib import Path
            from core.research import StrategyContext, StrategyDecision, clean_json
            signal_index = span["start"] + i
            lookback = options.get("lookback", 126)
            if type(lookback) is not int or not 2 <= lookback <= signal_index:
                raise ProblemError("Strategy lookback must fit the available past return observations.")
            history = all_prices.iloc[signal_index-lookback:signal_index+1].copy()
            drifting = units * all_prices.iloc[signal_index].to_numpy() / previous_equity
            context = StrategyContext(history, tuple(payload["symbols"]),
                str(all_prices.index[signal_index].date()),
                dict(zip(payload["symbols"], drifting.tolist())), rng, Path(artifact_dir or "."))
            decision = strategy(context, state)
            if not isinstance(decision, StrategyDecision) or set(decision.weights) != set(payload["symbols"]):
                raise ProblemError("Strategy must return StrategyDecision with one named weight per asset.")
            target = np.asarray([decision.weights[s] for s in payload["symbols"]], dtype=float)
            if target.shape != weights.shape or not np.isfinite(target).all():
                raise ProblemError("Strategy weights must be a finite vector matching the asset order.")
            state = decision.state
            refit_index = len(refits)
            refits.append({"signal_index":signal_index, "signal_date":context.signal_date,
                "trade_date":str(day.date()), "lookback":lookback,
                "history_digest":content_digest(history.to_numpy().tolist()),
                "diagnostics":clean_json(decision.diagnostics)})
        elif i in scheduled and mode == "rolling":
            if monotonic() - start >= seconds:
                status = "budget_exhausted"
                warnings.append(
                    "Rolling solve budget exhausted. The saved result is a partial path."
                )
                break
            signal_index = span["start"] + i
            previous_notional = units * all_prices.iloc[signal_index].to_numpy()
            previous_weights = previous_notional / previous_equity
            try:
                changed, evidence = refit_spec(
                    spec, payload, signal_index, previous_weights, options
                )
                result = solve(
                    build_problem(changed, limits or Limits()),
                    options.get("solver", "CLARABEL"),
                    seconds=min(2, max(0.01, seconds - (monotonic() - start))),
                )
            except ProblemError as error:
                if i == 0:
                    raise
                status = "solver_failed"
                warnings.append(
                    f"Refit for {day.date()} failed: {error}. Stopped before that trade."
                )
                break
            refit_index = len(refits)
            refits.append(
                {
                    **evidence,
                    "previous_weights": previous_weights.tolist(),
                    "trade_date": str(day.date()),
                    "result": result,
                }
            )
            if (
                not result.get("verified_optimal")
                or variable not in result["variables"]
            ):
                if i == 0:
                    raise ProblemError(
                        f"The first rolling problem did not produce a verified optimum ({result['status']}). No evaluation was saved."
                    )
                status = "solver_failed"
                warnings.append(
                    f"Refit for {day.date()} failed ({result['status']}); stopped before that trade."
                )
                break
            target = np.asarray(result["variables"][variable], dtype=float)
            if target.shape != weights.shape:
                raise ProblemError("Rolling solution must keep one weight per asset.")
        prior_cash = cash
        prior_borrow, prior_financing = borrow_total, financing_total
        if i:
            days = (day - prices.index[i - 1]).days
            prior = units * prices.iloc[i - 1].to_numpy()
            borrow = float(
                -np.minimum(prior, 0).sum() * options["borrow_rate"] * days / 365
            )
            financing = float(max(-cash, 0) * options["financing_rate"] * days / 365)
            cash -= borrow + financing
            borrow_total += borrow
            financing_total += financing
        notional = units * row.to_numpy()
        equity = float(notional.sum() + cash)
        if i in scheduled and equity > 0:
            try:
                after, deltas = trade_to_weights(
                    equity, notional, target, options["cost_bps"] / 10000
                )
            except ProblemError:
                if not wealths:
                    raise
                cash = prior_cash
                borrow_total = prior_borrow
                financing_total = prior_financing
                status = "trading_cost_failure"
                warnings.append(
                    "Trading costs prevent the next rebalance; stopped before that close."
                )
                break
            units = after * target / row.to_numpy()
            cash = float(after * (1 - target.sum()))
            trades.append(
                {
                    "date": str(day.date()),
                    "signal_date": payload["dates"][span["start"] + i]
                    if mode == "rolling" or strategy is not None
                    else None,
                    "weights": target.tolist(),
                    "units": units.tolist(),
                    "dollar_trades": deltas.tolist(),
                    "pre_equity": equity,
                    "post_equity": after,
                    "cost": float(equity - after),
                    "turnover": float(np.abs(deltas).sum() / equity),
                    "refit_index": refit_index,
                }
            )
            equity = after
            if initial_weights is None:
                initial_weights = target.copy()
        if not np.isfinite(equity):
            raise ProblemError("Exposure produced nonfinite equity.")
        wealths.append(equity)
        returns.append(equity / previous_equity - 1)
        if equity <= 0:
            status = "nonpositive_equity"
            warnings.append("Equity became nonpositive; evaluation stopped.")
            break
        previous_equity = equity
    if not wealths:
        raise ProblemError(
            "No evaluation dates completed. Reduce workload or correct the first rolling problem."
        )
    dates = prices.index[: len(wealths)]
    if len(wealths) < 60:
        warnings.append(
            "Fewer than 60 evaluation observations: annualized metrics can be unstable."
        )
    initial_weights = initial_weights if initial_weights is not None else weights
    summary = metrics(returns, wealths, dates, options["risk_free_rate"])
    summary["turnover"] = sum(t["turnover"] for t in trades)
    return {
        "status": status,
        "dates": dates.strftime("%Y-%m-%d").tolist(),
        "wealth": wealths,
        "returns": returns,
        "drawdown": (
            np.asarray(wealths) / np.maximum.accumulate(np.r_[1.0, wealths])[1:] - 1
        ).tolist(),
        "metrics": summary,
        "settings": options,
        "initial_weights": initial_weights.tolist(),
        "net_exposure": float(initial_weights.sum()),
        "gross_exposure": float(np.abs(initial_weights).sum()),
        "initial_cash_fraction": float(1 - initial_weights.sum()),
        "entry_cost": trades[0]["cost"] if trades else 0.0,
        "trading_cost": sum(t["cost"] for t in trades),
        "borrow_cost": borrow_total,
        "financing_cost": financing_total,
        "ending_cash": cash,
        "window": span,
        "warnings": warnings,
        "trades": trades,
        "refits": refits,
        "elapsed_seconds": monotonic() - start,
        "timing": "Signals use prices through the preceding close; simulated trades occur at the following close. Costs apply to every buy and sell. No new trade at the final marking close.",
    }


def evaluate_portfolios(
    payload,
    weights,
    window,
    options,
    spec,
    variable,
    limits,
    seconds=45,
    maximum_refits=300,
):
    chosen = portfolio_path(
        payload,
        weights,
        window,
        options,
        spec,
        variable,
        limits,
        seconds,
        maximum_refits,
    )
    benchmark = portfolio_path(
        payload,
        [1 / len(weights)] * len(weights),
        window,
        {**options, "mode": "fixed"},
        stop_after=len(chosen["wealth"]),
    )
    return {"portfolio": chosen, "equal_weight": benchmark}
