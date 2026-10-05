"""Deterministic research grids and descriptive summaries, with no Django.

Multiple trials are evidence of exploration, not independent confirmations.
Seed variation is displayed as a sample distribution, not a confidence interval.
"""
from itertools import product
from math import prod
from copy import deepcopy
import numpy as np
from core.parser import ProblemError
from core.research import clean_json


def grid_trials(grid, seeds, maximum=100):
    if not isinstance(grid, dict):
        raise ProblemError("Grid must be a JSON object of field names to candidate lists.")
    names = sorted(grid)
    for name, values in grid.items():
        prefix, separator, key = name.partition(".")
        if prefix not in ("params", "options", "parameters") or not separator or not key:
            raise ProblemError("Grid fields must start with params., options., or parameters.")
        if not isinstance(values, list) or not values:
            raise ProblemError("Each grid field needs a nonempty list of candidates.")
        clean_json(values)
    if not isinstance(seeds, list) or not seeds or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds):
        raise ProblemError("Seeds must be a nonempty JSON list of integers in 0..2^32-1.")
    if len(set(seeds)) != len(seeds): raise ProblemError("Seed list must not contain duplicates.")
    count = prod(len(v) for v in grid.values()) * len(seeds)
    if type(maximum) is not int or maximum < 1 or count > maximum:
        raise ProblemError(f"Grid needs {count} trials; --max-trials is {maximum}.")
    for combination in product(*(grid[name] for name in names)):
        settings = dict(zip(names, combination))
        for seed in seeds:
            yield {"changes":deepcopy(settings), "seed":seed}


def apply_trial(base, trial):
    changed = deepcopy(base)
    for field, value in trial["changes"].items():
        prefix, name = field.split(".", 1)
        if prefix == "parameters":
            parameter = next((p for p in changed["spec"]["parameters"] if p["name"] == name), None)
            if parameter is None: raise ProblemError(f"No symbolic parameter named {name}.")
            parameter["value"] = value
        else:
            changed.setdefault(prefix, {})[name] = value
    return changed


def summarize_trials(trials, metric, direction):
    valid = []
    units = set()
    for trial in trials:
        item = trial["result"].get("metrics", {}).get(metric)
        if trial["status"] != "complete" or not item or item.get("value") is None:
            continue
        units.add(item["unit"])
        valid.append({**trial, "score":item["value"]})
    if len(units) > 1:
        raise ProblemError("Ranking metric units differ between trials.")
    valid.sort(key=lambda t:t["score"], reverse=direction == "maximize")
    values = np.array([t["score"] for t in valid])
    summary = {"metric":metric, "direction":direction, "unit":next(iter(units), ""),
               "attempted":len(trials), "ranked":len(valid),
               "failed_or_excluded":len(trials)-len(valid),
               "best_run_id":valid[0]["id"] if valid else None,
               "minimum":float(values.min()) if len(values) else None,
               "maximum":float(values.max()) if len(values) else None,
               "median":float(np.median(values)) if len(values) else None}
    rows = [[t["id"],t["status"],t["seed"],t.get("changes",{}),
             t["result"].get("metrics",{}).get(metric,{}).get("value")] for t in trials]
    charts = []
    if valid:
        import plotly.graph_objects as go
        figure = go.Figure(go.Box(y=values.tolist(), boxpoints="all", name=metric,
            customdata=[t["id"] for t in valid], hovertemplate="%{y}<br>Run: %{customdata}<extra></extra>"))
        figure.update_layout(title=f"All completed trials · {metric}", yaxis_title=summary["unit"])
        charts.append({"figure":figure.to_plotly_json()})
        fields = sorted({k for t in valid for k in t.get("changes",{})})
        if len(fields) == 2:
            # Aggregate seeds per grid cell, with an explicit median label.
            labels = [[repr(t["changes"][field]) for t in valid] for field in fields]
            axes = [list(dict.fromkeys(repr(t["changes"][field]) for t in trials if field in t.get("changes",{})))
                    for field in fields]
            z = [[float(np.median([t["score"] for i,t in enumerate(valid) if labels[0][i]==x and labels[1][i]==y]))
                  if any(labels[0][i]==x and labels[1][i]==y for i in range(len(valid))) else None
                  for x in axes[0]] for y in axes[1]]
            figure = go.Figure(go.Heatmap(x=axes[0],y=axes[1],z=z,colorbar={"title":metric}))
            figure.update_layout(title=f"Median across seeds · {metric}", xaxis_title=fields[0], yaxis_title=fields[1])
            charts.append({"figure":figure.to_plotly_json()})
    return clean_json({"schema_version":1,"provenance":"validation sweep", "summary":summary,
        "metrics":{"trials_attempted":{"value":len(trials),"unit":"count","direction":"none"},
                   "trials_ranked":{"value":len(valid),"unit":"count","direction":"none"}},
        "text":"Rankings use completed validation trials only. Exploring many variants can overfit validation. Seed variation is descriptive, not an independent confidence interval.",
        "equations":[], "charts":charts,
        "tables":[{"title":"Every attempted trial", "columns":["Run ID","Status","Seed","Changed settings",metric],"rows":rows}]})
