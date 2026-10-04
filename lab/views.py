"""Request coordination only; the math lives in core/."""
import hashlib
import json
from threading import BoundedSemaphore

import numpy as np
import plotly.graph_objects as go
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.parser import Limits, ProblemError, build_problem
from core.presets import PRESETS, get_preset
from core.solve import solve
from lab.forms import ProblemForm, initial_from_spec
from lab.models import Experiment, Problem
from lab.workspaces import scoped, workspace_for

# One process, five active numerical requests. No queued/background work.
SOLVE_SLOTS = BoundedSemaphore(5)


def limits():
    return Limits(variable_entries=settings.LAB_MAX_VARIABLE_ENTRIES,
                  parameter_entries=settings.LAB_MAX_PARAMETER_ENTRIES, ast_nodes=settings.LAB_MAX_AST_NODES)


@login_required
def home(request):
    return render(request, "lab/home.html", {"problems": scoped(Problem, request),
                  "experiments": scoped(Experiment, request), "is_guest": not request.user.is_staff})


@login_required
def editor(request, pk=None):
    draft = get_object_or_404(scoped(Problem, request), pk=pk) if pk else None
    preset = request.GET.get("preset", "min-variance")
    if preset not in PRESETS:
        return HttpResponse("Unknown preset.", status=404)
    name = draft.name if draft else PRESETS[preset][0]
    spec = draft.spec if draft else get_preset(preset)
    form = ProblemForm(request.POST if request.method == "POST" else None, initial=initial_from_spec(name, spec))
    preview = None
    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action", "preview")
        if action not in {"preview", "save", "solve"}:
            form.add_error(None, "Unknown action.")
        else:
            try:
                spec = form.specification()
                built = build_problem(spec, limits())
                preview = built.preview()
                if action == "solve" and not preview["is_dcp"]:
                    form.add_error(None, "DCP rules failed. See the explanation below; no solve was attempted.")
                elif action == "solve":
                    if not SOLVE_SLOTS.acquire(blocking=False):
                        response = render(request, "lab/busy.html", status=503)
                        response["Retry-After"] = "3"
                        return response
                    try:
                        result = solve(built, form.cleaned_data["solver"], seconds=settings.LAB_SOLVE_SECONDS)
                    finally:
                        SOLVE_SLOTS.release()
                    # Solve before database writes, never inside a transaction.
                    if draft is None:
                        draft = Problem(owner=request.user, workspace=workspace_for(request))
                    draft.name, draft.spec = form.cleaned_data["name"], spec
                    draft.save()
                    digest = hashlib.sha256(json.dumps({"spec": spec, "solver": result["solver"],
                        "options": result["solver_options"]}, sort_keys=True, allow_nan=False).encode()).hexdigest()
                    experiment = Experiment.objects.create(owner=request.user, workspace=workspace_for(request),
                        problem=draft, name=draft.name, spec=spec, preview=preview, result=result, digest=digest)
                    return redirect("result", pk=experiment.pk)
                elif action == "save":
                    if draft is None:
                        draft = Problem(owner=request.user, workspace=workspace_for(request))
                    draft.name, draft.spec = form.cleaned_data["name"], spec
                    draft.save()
                    messages.success(request, "Draft saved. Solving it will create a separate frozen experiment.")
                    return redirect("edit", pk=draft.pk)
            except ProblemError as error:
                form.add_error(None, str(error))
    elif request.method == "GET":
        try:
            preview = build_problem(spec, limits()).preview()
        except ProblemError as error:
            form.add_error(None, str(error))
    return render(request, "lab/editor.html", {"form": form, "preview": preview, "draft": draft,
                  "presets": [(key, value[0]) for key, value in PRESETS.items()]})


@login_required
@require_POST
def clone(request, pk):
    original = get_object_or_404(scoped(Experiment, request), pk=pk)
    draft = Problem.objects.create(owner=request.user, workspace=workspace_for(request),
                                   name=(original.name + " (copy)")[:120], spec=original.spec)
    return redirect("edit", pk=draft.pk)


@login_required
def result(request, pk):
    experiment = get_object_or_404(scoped(Experiment, request), pk=pk)
    variables = []
    for declaration in experiment.preview["declarations"]:
        if declaration["kind"] != "variable":
            continue
        value = experiment.result["variables"].get(declaration["name"])
        if value is None:
            entries, chart = [], None
        else:
            array = np.asarray(value)
            entries = [{"index": str(index) if index else "scalar", "value": float(array[index])}
                       for index in np.ndindex(array.shape)]
            chart = None
            if array.ndim == 1:
                figure = go.Figure(go.Bar(x=[str(i) for i in range(len(array))], y=array.tolist()))
                figure.update_layout(title=declaration["meaning"] or declaration["name"],
                    xaxis_title="Zero-based index", yaxis_title=declaration["units"] or "Value",
                    margin=dict(l=50, r=20, t=60, b=45), height=320, template="plotly_white")
                chart = figure.to_plotly_json()
        variables.append({**declaration, "entries": entries, "chart": chart})
    return render(request, "lab/result.html", {"experiment": experiment, "preview": experiment.preview,
                                               "variables": variables})
