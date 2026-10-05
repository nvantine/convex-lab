"""A standalone reproducible simulation, intentionally separate from real backtests."""
import plotly.graph_objects as go
from core.research import ResearchResult


def run(context, params):
    count = int(params.get("count", 1000))
    if count < 2: raise ValueError("count must be at least 2.")
    values = context.rng.normal(params.get("mean", 0), params.get("sigma", 1), count)
    path = context.artifact_dir / "samples.json"
    import json
    path.write_text(json.dumps(values.tolist()))
    figure = go.Figure(go.Histogram(x=values.tolist(), name="Simulated samples"))
    figure.update_layout(title="Normal simulation", xaxis_title="Value", yaxis_title="Count")
    return ResearchResult(
        metrics={"sample_mean":{"value":float(values.mean()), "unit":"number", "direction":"none"},
                 "sample_std":{"value":float(values.std(ddof=1)), "unit":"number", "direction":"none"}},
        charts=[{"figure":figure.to_plotly_json()}],
        equations=[r"X_i \sim \mathcal{N}(\mu,\sigma^2)"],
        text="Independent normal samples. This illustration does not model market returns.",
        artifacts=["samples.json"])
