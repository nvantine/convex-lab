"""Read-only comparison of scoped snapshots: selecting never opens a holdout."""

from uuid import UUID
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from core.comparison import comparison_rows, experiment_metadata, evaluation_metadata
from lab.models import Experiment, Evaluation
from lab.workspaces import scoped


@login_required
def compare(request):
    selections = [("experiment", Experiment), ("evaluation", Evaluation)]
    if sum(len(request.GET.getlist(name)) for name, model in selections) > 6:
        return HttpResponse(
            "Choose at most six frozen records for a readable comparison.", status=400
        )
    records = []
    experiments = []
    evaluations = []
    try:
        for name, model in selections:
            for value in dict.fromkeys(request.GET.getlist(name)):
                pk = UUID(value)
                item = get_object_or_404(scoped(model, request), pk=pk)
                if name == "experiment":
                    metadata = experiment_metadata(
                        item.spec,
                        {
                            **item.result,
                            "settings": item.parent.result.get("settings", {}),
                        }
                        if item.parent_id
                        else item.result,
                    )
                    metrics = {
                        "Status": item.result["status"],
                        "Objective value": item.result.get("optimal_value"),
                        "Nondominated samples": len(item.result.get("points", []))
                        if item.kind == "frontier"
                        else None,
                    }
                    experiments.append(item)
                    link = "result"
                else:
                    metadata = evaluation_metadata(
                        item.dataset.prices,
                        item.dataset_digest,
                        item.window,
                        item.variable,
                        item.result,
                    )
                    metadata.update(
                        {
                            "Saved problem · " + k: v
                            for k, v in experiment_metadata(
                                item.experiment.spec,
                                {
                                    **item.experiment.result,
                                    "settings": item.experiment.parent.result.get(
                                        "settings", {}
                                    ),
                                }
                                if item.experiment.parent_id
                                else item.experiment.result,
                            ).items()
                        }
                    )
                    metrics = {
                        "Status": item.result["portfolio"]["status"],
                        **item.result["portfolio"]["metrics"],
                    }
                    evaluations.append(item)
                    link = "evaluation"
                records.append(
                    {
                        "name": item.name
                        if name == "experiment"
                        else item.experiment.name + " · " + item.get_window_display(),
                        "pk": item.pk,
                        "link": link,
                        "metadata": metadata,
                        "metrics": metrics,
                        "summary": item.result["portfolio"]["settings"].get(
                            "mode", "fixed"
                        )
                        + " / "
                        + item.result["portfolio"]["settings"].get("frequency", "hold")
                        if name == "evaluation"
                        else item.kind,
                    }
                )
    except ValueError:
        return HttpResponse("Select valid saved record IDs.", status=400)
    rows = comparison_rows(records)
    metric_names = list(dict.fromkeys(k for r in records for k in r["metrics"]))
    metric_rows = [
        {"name": name, "values": [r["metrics"].get(name) for r in records]}
        for name in metric_names
    ]
    charts = []
    if evaluations:
        figure = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.1,
            subplot_titles=("Equity · initial capital = 1", "Drawdown"),
        )
        for i, item in enumerate(evaluations):
            series = item.result["portfolio"]
            label = f"{i + 1}. {item.experiment.name[:24]} · {series['settings'].get('mode', 'fixed')}/{series['settings'].get('frequency', 'hold')}"
            for row, key in [(1, "wealth"), (2, "drawdown")]:
                figure.add_trace(
                    go.Scatter(
                        x=series["dates"],
                        y=series[key],
                        name=label,
                        legendgroup=str(i),
                        showlegend=row == 1,
                        line={
                            "color": [
                                "#174ea6",
                                "#b46022",
                                "#245a3e",
                                "#873e9d",
                                "#a12039",
                                "#52606f",
                            ][i]
                        },
                    ),
                    row=row,
                    col=1,
                )
        figure.update_layout(
            height=700,
            template="plotly_white",
            hovermode="x unified",
            legend={"orientation": "h", "y": -0.15},
            margin=dict(l=55, r=25, t=65, b=120),
        )
        charts.append({"key": "compare-history", "figure": figure.to_plotly_json()})
    if len(experiments) > 1:
        # Only overlay vectors when their names, shapes, AND bound asset order agree.
        first = experiments[0]
        labels = first.spec.get("data", {}).get("symbols")
        variables = first.result.get("variables", {})
        for name, value in variables.items():
            if value is None or np.asarray(value).ndim != 1:
                continue
            compatible = all(
                e.result.get("variables", {}).get(name) is not None
                and np.asarray(e.result["variables"][name]).shape
                == np.asarray(value).shape
                and e.spec.get("data", {}).get("symbols") == labels
                for e in experiments
            )
            if compatible:
                figure = go.Figure()
                for i, e in enumerate(experiments):
                    figure.add_trace(
                        go.Bar(
                            x=labels or [str(j) for j in range(len(value))],
                            y=e.result["variables"][name],
                            name=f"{i + 1}. {e.name}",
                        )
                    )
                figure.update_layout(
                    title=f"Decision vector: {name}",
                    barmode="group",
                    template="plotly_white",
                    height=400,
                    margin=dict(l=50, r=20, t=55, b=90),
                    legend=dict(orientation="h", y=-0.2),
                )
                charts.append(
                    {"key": "compare-" + name, "figure": figure.to_plotly_json()}
                )
    return render(
        request,
        "lab/compare.html",
        {
            "experiments": scoped(Experiment, request).only("id", "name", "created_at"),
            "evaluations": scoped(Evaluation, request)
            .select_related("experiment", "dataset")
            .defer(
                "result",
                "experiment__result",
                "experiment__spec",
                "experiment__preview",
                "dataset__prices",
            ),
            "selected_experiments": {e.pk for e in experiments},
            "selected_evaluations": {e.pk for e in evaluations},
            "records": records,
            "rows": rows,
            "metrics": metric_rows,
            "charts": charts,
            "differences": [r["name"] for r in rows if r["different"]],
        },
    )
