"""Read-only comparison of scoped snapshots: selecting never opens a holdout."""

from uuid import UUID
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from core.comparison import comparison_rows, experiment_metadata, evaluation_metadata
from lab.models import Experiment, Evaluation, ResearchRun
from lab.workspaces import scoped, request_scope


@login_required
def compare(request):
    selection = {name: request.GET.getlist(name) for name in ("experiment", "evaluation", "run")}
    try:
        context = comparison_context(request_scope(request), selection)
    except ValueError as error:
        return HttpResponse(str(error), status=400)
    return render(request, "lab/compare.html", context)


def comparison_context(scope, selection):
    """The same frozen comparison for website forms, CLI JSON, and saved reports."""
    selections = [("experiment", Experiment), ("evaluation", Evaluation), ("run", ResearchRun)]
    if sum(len(selection.get(name, [])) for name, model in selections) > 6:
        raise ValueError("Choose at most six frozen records for a readable comparison.")
    records = []
    experiments = []
    evaluations = []
    runs = []
    try:
        for name, model in selections:
            for value in dict.fromkeys(selection.get(name, [])):
                pk = UUID(value)
                item = get_object_or_404(scope.query(model), pk=pk)
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
                elif name == "evaluation":
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
                        **{metric_label(k, portfolio_units(k)):v for k,v in item.result["portfolio"]["metrics"].items()},
                    }
                    evaluations.append(item)
                    link = "evaluation"
                else:
                    metadata = {
                        "Data fingerprint":item.dataset_digest or None,
                        "Asset order":item.dataset.prices["symbols"] if item.dataset_id else None,
                        "Window":item.window, "Source revision":item.revision.digest if item.revision_id else None,
                        "Parameters":item.config.get("params",{}), "Seed":item.config.get("seed"),
                        "Runtime":research_environment(item.runtime), "Evidence":item.result.get("provenance"),
                        "Metric units":{k:v["unit"] for k,v in item.result.get("metrics",{}).items()},
                    }
                    if item.result.get("portfolio") and item.dataset_id:
                        metadata.update(evaluation_metadata(item.dataset.prices,item.dataset_digest,item.window,
                            item.config.get("variable","Python weights"),item.result))
                        metadata["Seed"]=item.config.get("seed")
                        metadata["Runtime"]=research_environment(item.runtime)
                    if item.experiment_id:
                        source_result=item.experiment.result
                        if item.experiment.parent_id:
                            source_result={**source_result,"settings":item.experiment.parent.result.get("settings",{})}
                        source_metadata=experiment_metadata(item.experiment.spec,source_result)
                        if item.result.get("portfolio"):
                            metadata.update({"Saved problem · "+k:v for k,v in source_metadata.items()})
                        else:
                            metadata.update(source_metadata)
                    elif item.config.get("spec"):
                        metadata.update(experiment_metadata(item.config["spec"],{}))
                    if item.kind=="sweep":
                        metadata.update({"Campaign grid":item.config.get("grid"),
                            "Campaign seeds":item.config.get("seeds"), "Ranking metric":item.result.get("summary",{}).get("metric")})
                    if item.kind=="report":
                        metadata["Selected records"]=item.config.get("selection")
                    metrics = {"Status":item.status,
                        **{metric_label(k,v["unit"]):v["value"] for k,v in item.result.get("metrics",{}).items()}}
                    runs.append(item)
                    link = "research_run"
                records.append(
                    {
                        "name": item.name
                        if name == "experiment"
                        else item.experiment.name + " · " + item.get_window_display() if name == "evaluation" else item.name,
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
        raise ValueError("Select valid saved record IDs.")
    rows = comparison_rows(records)
    metric_names = list(dict.fromkeys(k for r in records for k in r["metrics"]))
    metric_rows = [
        {"name": name, "values": [r["metrics"].get(name) for r in records]}
        for name in metric_names
    ]
    charts = []
    histories = [(item.pk,item.experiment.name,item.result["portfolio"]) for item in evaluations]
    histories += [(item.pk,item.name,item.result["portfolio"]) for item in runs if item.result.get("portfolio")]
    if histories:
        figure = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.1,
            subplot_titles=("Equity · initial capital = 1", "Drawdown"),
        )
        for i, (pk, name, series) in enumerate(histories):
            label = f"{i + 1}. {name[:24]} · {series['settings'].get('mode', 'fixed')}/{series['settings'].get('frequency', 'hold')}"
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
    from copy import deepcopy
    for run in runs:
        if run.result.get("portfolio"): continue
        for index, item in enumerate(run.result.get("charts", [])):
            figure = deepcopy(item["figure"])
            layout = figure.setdefault("layout",{})
            original = layout.get("title",{})
            title = original.get("text","") if isinstance(original,dict) else original
            layout["title"] = {"text":f"{run.name} · {title}"}
            charts.append({"key":f"compare-run-{run.pk}-{index}","figure":figure})
    return {
            "experiments": scope.query(Experiment).only("id", "name", "created_at"),
            "evaluations": scope.query(Evaluation)
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
            "runs":scope.query(ResearchRun).only("id","name","kind","status","created_at"),
            "selected_runs":{r.pk for r in runs},
            "records": records,
            "rows": rows,
            "metrics": metric_rows,
            "charts": charts,
            "differences": [r["name"] for r in rows if r["different"]],
        }


def metric_label(name, unit):
    return f"{name} [{unit}]"


def portfolio_units(name):
    return {"total_return":"fraction","cagr":"annual fraction","volatility":"annual fraction",
            "sharpe":"ratio","max_drawdown":"fraction","turnover":"multiple"}.get(name,"number")


def research_environment(runtime):
    return {k:v for k,v in runtime.items() if k not in
            ("pid","child_pid","process_started","child_started","host")}
