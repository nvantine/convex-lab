"""Small public SDK for trusted local Python research. No Django imports.

Python strategies are not DCP-certified. App-managed historical timing remains
the same as the symbolic portfolio engine (Boyd & Vandenberghe §4.4.1).
"""
from dataclasses import dataclass, field
from pathlib import Path
import json
import numpy as np
import pandas as pd
from plotly.utils import PlotlyJSONEncoder
from core.parser import ProblemError


@dataclass
class StrategyContext:
    history: pd.DataFrame
    symbols: tuple[str, ...]
    signal_date: str
    current_weights: dict[str, float]
    rng: np.random.Generator
    artifact_dir: Path


@dataclass
class ResearchContext:
    prices: pd.DataFrame | None
    training: pd.DataFrame | None
    symbols: tuple[str, ...]
    window: str
    rng: np.random.Generator
    artifact_dir: Path


@dataclass
class StrategyDecision:
    weights: dict[str, float]
    state: object = None
    diagnostics: dict = field(default_factory=dict)


@dataclass
class ResearchResult:
    metrics: dict = field(default_factory=dict)
    tables: list = field(default_factory=list)
    charts: list = field(default_factory=list)
    text: str = ""
    equations: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)


def clean_json(value):
    """Convert NumPy/Plotly values, then reject nonfinite JSON evidence."""
    encoded = json.dumps(value, default=PlotlyJSONEncoder().default, allow_nan=False)
    return json.loads(encoded)


def result_payload(result):
    if not isinstance(result, ResearchResult):
        raise ProblemError("Research entry point must return core.research.ResearchResult.")
    payload = clean_json(vars(result))
    for name, metric in payload["metrics"].items():
        if not isinstance(name, str) or not isinstance(metric, dict):
            raise ProblemError("Each metric needs an object with value, unit, and optional direction.")
        value = metric.get("value")
        if value is not None and (type(value) not in (float, int) or not np.isfinite(value)):
            raise ProblemError("Metric values must be finite numbers or null.")
        if not isinstance(metric.get("unit"), str) or metric.get("direction", "none") not in ("minimize", "maximize", "none"):
            raise ProblemError("Metrics require a unit and a valid direction.")
    for table in payload["tables"]:
        if not isinstance(table, dict) or not isinstance(table.get("columns"), list) or not isinstance(table.get("rows"), list):
            raise ProblemError("Tables require columns and rows lists.")
        if any(not isinstance(row, list) or len(row) != len(table["columns"]) for row in table["rows"]):
            raise ProblemError("Each table row must match its columns.")
    import plotly.graph_objects as go
    for chart in payload["charts"]:
        if not isinstance(chart, dict) or "figure" not in chart:
            raise ProblemError("Charts require a figure containing Plotly JSON.")
        go.Figure(chart["figure"])  # Validate; never accept executable HTML.
    if not isinstance(payload["text"], str) or any(not isinstance(x, str) for x in payload["equations"] + payload["artifacts"]):
        raise ProblemError("Report text, equations, and artifact paths must be strings.")
    return {"schema_version": 1, "provenance": "script-reported", **payload}


def portfolio_report(result):
    """Use the same canonical path and metric units for both kinds of strategy."""
    path = result["portfolio"]
    units = {"total_return": "fraction", "cagr": "annual fraction", "volatility": "annual fraction",
             "sharpe": "ratio", "max_drawdown": "fraction", "turnover": "multiple"}
    metrics = {k: {"value": v, "unit": units.get(k, "number"),
                   "direction": "minimize" if k in ("volatility", "max_drawdown", "turnover") else "maximize"}
               for k, v in path["metrics"].items()}
    return {"schema_version": 1, "provenance": "app-managed backtest", "metrics": metrics,
            "tables": [], "charts": [], "text": "", "equations": [], "artifacts": [], **clean_json(result)}
