"""A deliberately simple lagged-return model; an example, not a performance claim."""
import numpy as np
from sklearn.linear_model import Ridge
from core.research import StrategyDecision


def target_weights(context, params, state):
    returns = context.history.pct_change(fill_method=None).iloc[1:].to_numpy()
    if len(returns) < 3: raise ValueError("Need at least three past returns.")
    # Each feature vector is paired with the NEXT return already observed.
    # Ridge minimizes squared prediction error plus alpha times squared coefficients.
    model = Ridge(alpha=params.get("alpha", 1.0))
    model.fit(returns[:-1], returns[1:])
    predicted = model.predict(returns[-1:])[0]
    scores = predicted if params.get("shorting", False) else np.maximum(predicted, 0)
    gross = params.get("gross_exposure", 1.0)
    weights = gross * scores / np.abs(scores).sum() if np.abs(scores).sum() > 1e-12 else np.zeros(len(scores))
    # State is an ordinary Python object: agents can retain fitted models.
    return StrategyDecision(dict(zip(context.symbols, weights.tolist())), state=model,
                            diagnostics={"predicted_daily_returns":predicted.tolist()})
