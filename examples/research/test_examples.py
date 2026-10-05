"""Tests that can themselves be saved with: convex-lab tests run REVISION_ID."""
import numpy as np
from pathlib import Path
import pandas as pd
from core.research import StrategyContext, ResearchContext
from min_variance import target_weights
from simulation import run


def test_min_variance_weights():
    rng = np.random.default_rng(12)
    prices = pd.DataFrame(100*np.cumprod(1+rng.normal(0,.01,(40,2)), axis=0),
                          columns=["SPY","AGG"], index=pd.bdate_range("2020-01-01", periods=40))
    context = StrategyContext(prices, ("SPY","AGG"), "2020-02-25", {"SPY":0,"AGG":0}, rng, Path("."))
    decision = target_weights(context, {}, None)
    assert abs(sum(decision.weights.values())-1) < 1e-6
    assert min(decision.weights.values()) >= -1e-6


def test_simulation_seed(tmp_path):
    def context():
        return ResearchContext(None,None,(),"validation",np.random.default_rng(42),tmp_path)
    assert run(context(), {"count":30}).metrics == run(context(), {"count":30}).metrics
