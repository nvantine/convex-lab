"""Readable owner research evidence and frozen local artifacts."""
from pathlib import Path
import hashlib
import plotly.graph_objects as go
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from lab.models import ResearchRun, StrategyRevision
from lab.workspaces import scoped


@login_required
def research_index(request):
    return render(request, "lab/research.html", {"runs":scoped(ResearchRun, request).select_related("revision"),
                                               "strategies":scoped(StrategyRevision, request)})


def report_charts(run):
    charts = [{"key":f"research-chart-{i}", "figure":c["figure"]} for i,c in enumerate(run.result.get("charts", []))]
    if run.result.get("portfolio"):
        for key, title in (("wealth", "Equity · initial capital = 1"), ("drawdown", "Drawdown")):
            fig = go.Figure()
            for field, label in (("portfolio", run.name), ("equal_weight", "Equal weight")):
                path = run.result[field]
                fig.add_trace(go.Scatter(x=path["dates"], y=path[key], name=label))
            fig.update_layout(title=title, template="plotly_white", height=400,
                              legend={"orientation":"h"}, margin=dict(l=55,r=25,t=60,b=95))
            charts.append({"key":f"research-{key}", "figure":fig.to_plotly_json()})
    return charts


@login_required
def research_run(request, pk):
    run = get_object_or_404(scoped(ResearchRun, request), pk=pk)
    return render(request, "lab/research_run.html", {"run":run, "charts":report_charts(run),
        "metrics":run.result.get("metrics", {}), "tables":run.result.get("tables", []),
        "children":scoped(ResearchRun, request).filter(parent=run), "public":False})


@login_required
def run_status(request, pk):
    run = get_object_or_404(scoped(ResearchRun, request), pk=pk)
    return JsonResponse({"id":str(run.pk), "status":run.status, "finished":run.finished_at is not None})


@login_required
def strategy_revision(request, pk):
    revision = get_object_or_404(scoped(StrategyRevision, request), pk=pk)
    return render(request, "lab/strategy.html", {"revision":revision, "runs":scoped(ResearchRun, request).filter(revision=revision)})


@login_required
def artifact(request, pk, index):
    run = get_object_or_404(scoped(ResearchRun, request), pk=pk)
    if not 0 <= index < len(run.artifacts): raise Http404()
    item = run.artifacts[index]
    root = settings.LAB_ARTIFACT_ROOT / str(run.pk)
    path = (root / item["path"]).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file(): raise Http404()
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        return JsonResponse({"error":"Artifact differs from its saved checksum."}, status=409)
    # Always download: do not execute or embed user-produced HTML/model files.
    return FileResponse(path.open("rb"), as_attachment=True, filename=path.name)
