"""Request coordination only; the math lives in core/."""
import hashlib
import json
from types import SimpleNamespace

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
from core.solve import accepted_solution, solve
from core.pareto import run_frontier
from core.charts import frontier_charts
from lab.forms import ProblemForm, initial_from_spec
from lab.models import Experiment, Problem, Evaluation, Dataset
from core.data import estimates_edited
from lab.request_limits import SOLVE_SLOTS
from lab.workspaces import scoped, workspace_for, request_scope, ensure_guest_datasets
from lab import services



limits = services.limits

@login_required
def home(request):
    ensure_guest_datasets(request)
    return render(request, "lab/home.html", {"problems": scoped(Problem, request),
                  "experiments": scoped(Experiment, request), "evaluations": scoped(Evaluation, request), "is_guest": not request.user.is_staff})


@login_required
def editor(request, pk=None):
    draft = get_object_or_404(scoped(Problem, request), pk=pk) if pk else None
    preset = request.GET.get("preset", "min-variance")
    if preset not in PRESETS:
        return HttpResponse("Unknown preset.", status=404)
    name = draft.name if draft else PRESETS[preset][0]
    spec = draft.spec if draft else get_preset(preset)
    form = ProblemForm(request.POST if request.method == "POST" else None, initial=initial_from_spec(name, spec, limits=limits()))
    preview = None
    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action", "preview")
        if action not in {"preview", "save", "solve", "to_latex", "to_expression"}:
            form.add_error(None, "Unknown action.")
        else:
            try:
                spec = form.specification(limits())
                if draft and draft.spec.get('data'):
                    spec['data'] = draft.spec['data']
                built = build_problem(spec, limits())
                preview = built.preview()
                if action in {'to_latex', 'to_expression'}:
                    language = 'latex' if action == 'to_latex' else 'expression'
                    initial = initial_from_spec(form.cleaned_data['name'], spec, language, limits())
                    for field in ('solver', 'method', 'samples', 'normalize', 'primary', 'weights', 'epsilon', 'scales', 'seed'):
                        initial[field] = form.cleaned_data[field]
                    form = ProblemForm(initial=initial)
                elif action == "solve" and not preview["is_dcp"]:
                    form.add_error(None, "DCP rules failed. See the explanation below; no solve was attempted.")
                elif action == "solve":
                    if not SOLVE_SLOTS.acquire(blocking=False):
                        response = render(request, "lab/busy.html", status=503)
                        response["Retry-After"] = "3"
                        return response
                    try:
                        experiment = services.solve_problem(request_scope(request), form.cleaned_data["name"],
                            spec, form.cleaned_data["solver"], form.frontier_options(), draft)
                    finally:
                        SOLVE_SLOTS.release()
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
                  "presets": [(key, value[0]) for key, value in PRESETS.items()],
                  "max_samples": settings.LAB_MAX_FRONTIER_SAMPLES, "data_binding": spec.get("data"), "estimates_edited": estimates_edited(spec)})


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
    if experiment.kind == 'frontier':
        return render(request, 'lab/frontier.html', {'experiment': experiment,
            'preview': build_problem(experiment.spec, limits()).preview(), 'charts': frontier_charts(experiment.result)})
    return render_solution(request, experiment)


def render_solution(request, experiment, point=None):
    # Re-render frozen mathematics, never re-solve or mutate its historical evidence.
    preview = build_problem(experiment.spec, limits()).preview()
    variables = []
    for declaration in preview["declarations"]:
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
    selection = experiment.result.get('selection')
    criterion_rows = []
    if selection:
        generator = selection['generator']
        for i, criterion in enumerate(experiment.result.get('criteria', [])):
            item = {**criterion, 'value': selection['values'][i]}
            if generator['method'] == 'weighted':
                item['weight'] = generator['weights'][i]
            if generator['method'] == 'epsilon':
                item['bound'] = generator['epsilon'][i]
                item['primary'] = i == generator['primary']
            criterion_rows.append(item)
    # Display constraint mathematics from the same frozen parsed specification.
    experiment.result = {**experiment.result, 'constraints': [
        {**evidence, 'latex': constraint['latex']}
        for evidence, constraint in zip(experiment.result['constraints'], preview['constraints'])]}
    return render(request, "lab/result.html", {"experiment": experiment, "preview": preview, "point": point,
                                               "can_evaluate": accepted_solution(experiment.result),
                                               "variables": variables, "criterion_rows": criterion_rows, "estimates_edited": estimates_edited(experiment.spec)})


@login_required
def point_detail(request, pk, index):
    parent = get_object_or_404(scoped(Experiment, request), pk=pk, kind='frontier')
    point = next((p for p in parent.result['points'] if p['id'] == index), None)
    if point is None:
        return HttpResponse('Unknown sampled point.', status=404)
    experiment = SimpleNamespace(pk=parent.pk, name=f'{parent.name} · point {index}',
        spec=point['solved_spec'], result={**point['result'], 'selection': point, 'criteria': parent.result['criteria']},
        preview=point['preview'], digest=parent.digest, created_at=parent.created_at, parent=parent)
    return render_solution(request, experiment, point)


@login_required
@require_POST
def choose(request, pk):
    parent = get_object_or_404(scoped(Experiment, request), pk=pk, kind='frontier')
    try:
        index = int(request.POST.get('point_index', ''))
    except ValueError:
        return HttpResponse('Choose a valid point.', status=400)
    point = next((p for p in parent.result['points'] if p['id'] == index), None)
    if point is None or not accepted_solution(point['result']):
        return HttpResponse('Choose a verified sampled point.', status=400)
    child = services.choose_point(request_scope(request), parent, index)
    return redirect('result', pk=child.pk)
