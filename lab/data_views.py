"""Small synchronous data/validation flows. Numerical work stays in core/."""
from datetime import date, timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
import numpy as np
import plotly.graph_objects as go
from core.data import aligned_prices, content_digest, price_frame, problem_from_training, split_windows, estimates_edited
from core.evaluation import evaluate_with_benchmark
from core.parser import ProblemError, build_problem
from core.providers import fetch_prices
from lab.forms import DatasetForm, TrainingForm, EvaluationForm
from lab.models import Dataset, Evaluation, Experiment, Problem
from lab.request_limits import SOLVE_SLOTS
from lab.workspaces import scoped, workspace_for

DEFAULT_SYMBOLS = 'SPY, QQQ, IWM, EFA, EEM, AGG, TLT, LQD, HYG, GLD, VNQ, XLE, XLK, XLV, XLF, DBC'
TICKET_SALT = 'convex-lab-final-holdout'


def existing_holdout(request, dataset):
    return scoped(Evaluation, request).filter(dataset_digest=dataset.digest, window='holdout').first()


def data_fingerprint(payload, provenance):
    # Column permutations do not create another final holdout on identical data.
    order = np.argsort(payload['symbols'])
    return content_digest({'source':provenance['provider'], 'adjustment':provenance['adjustment'],
        'feed':provenance['feed'], 'dates':payload['dates'], 'symbols':sorted(payload['symbols']),
        'values':np.asarray(payload['values'])[:,order].tolist()})


@login_required
def datasets(request):
    end = date.today()-timedelta(days=1)
    form = DatasetForm(request.POST if request.method=='POST' else None, initial={
        'name':'Market history', 'source':'alpaca','symbols':DEFAULT_SYMBOLS, 'start':end-timedelta(days=365*5), 'end':end})
    if request.method=='POST' and form.is_valid():
        if not SOLVE_SLOTS.acquire(blocking=False):
            response = render(request,'lab/busy.html',status=503)
            response['Retry-After'] = '3'
            return response
        try:
            values = form.cleaned_data
            frame, provenance = fetch_prices(values['source'],values['symbols'],values['start'],values['end'],settings.LAB_FETCH_SECONDS)
            payload, coverage = aligned_prices(frame,values['symbols'],maximum=settings.LAB_MAX_PRICE_ROWS)
            provenance.update(coverage, requested_start=str(values['start']),requested_end=str(values['end']))
            digest = data_fingerprint(payload,provenance)
            cached = scoped(Dataset,request).filter(digest=digest).first()
            if cached:
                messages.success(request,'Identical cached data reused. The saved asset order and name are shown below.')
                return redirect('dataset',pk=cached.pk)
            dataset = Dataset.objects.create(owner=request.user,workspace=workspace_for(request),name=values['name'],
                source=values['source'],prices=payload,provenance=provenance,digest=digest)
            return redirect('dataset',pk=dataset.pk)
        except ProblemError as error:
            form.add_error(None,str(error))
        finally:
            SOLVE_SLOTS.release()
    return render(request,'lab/datasets.html',{'form':form,'datasets':scoped(Dataset,request),'asset_limit':settings.LAB_MAX_ASSETS})


@login_required
def dataset_detail(request,pk):
    dataset = get_object_or_404(scoped(Dataset,request),pk=pk)
    windows = split_windows(dataset.prices)
    form = TrainingForm(request.POST if request.method=='POST' else None, initial={'preset':'min-variance','estimator':'ledoit-wolf'})
    if request.method=='POST' and form.is_valid():
        try:
            from lab.views import limits
            spec, estimate, digest = problem_from_training(dataset.prices,**form.cleaned_data)
            spec['data'] = {'dataset_id':str(dataset.pk),'dataset_digest':dataset.digest,'symbols':dataset.prices['symbols'],
                'estimation':estimate,'estimates_digest':digest}
            build_problem(spec,limits())
            draft = Problem.objects.create(owner=request.user,workspace=workspace_for(request),name=(dataset.name+' · '+form.cleaned_data['preset'])[:120],spec=spec)
            return redirect('edit',pk=draft.pk)
        except ProblemError as error:
            form.add_error(None,str(error))
    # The holdout's prices are not embedded in HTML, Plotly, tables, or JSON.
    visible = price_frame(dataset.prices).iloc[:windows['validation']['end']+1]
    figure = go.Figure()
    for symbol in visible:
        figure.add_trace(go.Scatter(x=visible.index.strftime('%Y-%m-%d').tolist(), y=(visible[symbol]/visible[symbol].iloc[0]).tolist(),name=symbol))
    figure.add_vline(x=dataset.prices['dates'][windows['train']['end']],line_dash='dash')
    figure.update_layout(title='Training and validation',template='plotly_white',height=430,
                         xaxis_title='Date',yaxis_title='Adjusted-price ratio',margin=dict(l=50,r=20,t=55,b=90),
                         legend=dict(orientation='h',x=0,y=-.25))
    return render(request,'lab/dataset.html',{'dataset':dataset,'windows':windows,'form':form,'chart':figure.to_plotly_json(),
        'holdout':existing_holdout(request,dataset)})


def usable_variables(experiment):
    if experiment.kind=='frontier' or not experiment.result.get('verified_optimal'):
        return []
    return [name for name,value in experiment.result['variables'].items() if value is not None and np.asarray(value).ndim==1]


def evaluation_inputs(experiment,dataset,variable):
    names = usable_variables(experiment)
    if variable not in names:
        raise ProblemError('Choose a decision vector from a verified optimum. Save a frontier point as the chosen solution first.')
    binding = experiment.spec.get('data')
    if binding and (binding['dataset_digest']!=dataset.digest or binding['symbols']!=dataset.prices['symbols']):
        raise ProblemError('This solution was bound to a different data snapshot or asset order. Create an editable problem from this dataset before solving.')
    weights = experiment.result['variables'][variable]
    if len(weights)!=len(dataset.prices['symbols']):
        raise ProblemError('Decision vector length must match the dataset asset count. Entries follow the displayed asset order.')
    return weights


def provenance_notice(experiment):
    edited = estimates_edited(experiment.spec)
    if edited is None:
        return 'No imported training estimates are attached: these weights are a manually defined portfolio experiment.'
    if edited:
        return 'Imported training parameters were edited. Their original estimation provenance no longer certifies the current parameter values.'
    return 'Imported estimates and scenarios are unchanged and use training observations only.'


def save_evaluation(request,experiment,dataset,variable,window,options):
    if window=='holdout':
        existing = existing_holdout(request,dataset)
        if existing:
            return existing
    weights = evaluation_inputs(experiment,dataset,variable)
    result = evaluate_with_benchmark(dataset.prices,weights,window,options)
    result['provenance_notice'] = provenance_notice(experiment)
    result['runtime'] = experiment.result.get('runtime',{})
    defaults = {'owner':request.user,'workspace':workspace_for(request),'experiment':experiment,'dataset':dataset,
        'dataset_digest':dataset.digest,'variable':variable,'window':window,'result':result,
        'digest':content_digest({'experiment':experiment.digest,'dataset':dataset.digest,'variable':variable,'window':window,'options':options})}
    if window=='holdout':
        # Numerical work finished before get_or_create's short DB transaction.
        saved,_ = Evaluation.objects.get_or_create(owner=request.user,workspace=workspace_for(request),
            dataset_digest=dataset.digest,window='holdout',defaults={k:v for k,v in defaults.items()
            if k not in ('owner','workspace','dataset_digest','window')})
        return saved
    return Evaluation.objects.create(**defaults)


@login_required
def evaluation_setup(request,pk):
    experiment = get_object_or_404(scoped(Experiment,request),pk=pk)
    variables = usable_variables(experiment)
    if not variables:
        return HttpResponse('Evaluation needs a verified optimum with a decision vector. For a frontier, save a chosen solution first.',status=400)
    binding = experiment.spec.get('data',{})
    form = EvaluationForm(request.POST if request.method=='POST' else None,datasets=scoped(Dataset,request),variables=variables,
        initial={'dataset':binding.get('dataset_id'),'variable':'w' if 'w' in variables else variables[0]})
    if request.method=='POST' and form.is_valid():
        try:
            dataset,variable = form.cleaned_data['dataset'],form.cleaned_data['variable']
            weights = evaluation_inputs(experiment,dataset,variable)
            action = request.POST.get('action','validation')
            if action=='review_holdout':
                existing = existing_holdout(request,dataset)
                if existing:
                    messages.info(request,'The final holdout for this data snapshot has already been opened. Returning its frozen result.')
                    return redirect('evaluation',pk=existing.pk)
                ticket = signing.dumps({'experiment':str(experiment.pk),'dataset':str(dataset.pk),'variable':variable,
                    'options':form.options(),'workspace':str(workspace_for(request))},salt=TICKET_SALT)
                return render(request,'lab/confirm_holdout.html',{'experiment':experiment,'dataset':dataset,
                    'weights':list(zip(dataset.prices['symbols'],weights)),'window':split_windows(dataset.prices)['holdout'],
                    'ticket':ticket,'options':form.options(),'notice':provenance_notice(experiment)})
            if action!='validation':
                raise ProblemError('Choose validation or review the final holdout first.')
            saved = save_evaluation(request,experiment,dataset,variable,'validation',form.options())
            return redirect('evaluation',pk=saved.pk)
        except ProblemError as error:
            form.add_error(None,str(error))
    return render(request,'lab/evaluation_setup.html',{'form':form,'experiment':experiment,'notice':provenance_notice(experiment),
        'has_datasets':scoped(Dataset,request).exists()})


@login_required
@require_POST
def confirm_holdout(request):
    if request.POST.get('confirm')!='on':
        return HttpResponse('Explicit confirmation is required to open the final holdout.',status=400)
    try:
        ticket = signing.loads(request.POST.get('ticket',''),salt=TICKET_SALT,max_age=600)
        if ticket['workspace']!=str(workspace_for(request)):
            return HttpResponse('This confirmation belongs to another workspace.',status=404)
    except signing.BadSignature:
        return HttpResponse('Confirmation expired or is invalid. Review the final holdout again.',status=400)
    experiment = get_object_or_404(scoped(Experiment,request),pk=ticket['experiment'])
    dataset = get_object_or_404(scoped(Dataset,request),pk=ticket['dataset'])
    try:
        saved = save_evaluation(request,experiment,dataset,ticket['variable'],'holdout',ticket['options'])
    except ProblemError as error:
        return render(request,'lab/evaluation_error.html',{'error':str(error),'experiment':experiment},status=400)
    return redirect('evaluation',pk=saved.pk)


@login_required
def evaluation_detail(request,pk):
    evaluation = get_object_or_404(scoped(Evaluation,request),pk=pk)
    figures = []
    for key,title in [('wealth','Equity · initial capital = 1'), ('drawdown','Drawdown from prior peak')]:
        figure = go.Figure()
        for name,label in [('portfolio','Chosen portfolio'), ('equal_weight','Equal weight')]:
            series = evaluation.result[name]
            figure.add_trace(go.Scatter(x=series['dates'],y=series[key],name=label))
        figure.update_layout(title=title,template='plotly_white',height=400,margin=dict(l=50,r=20,t=60,b=90),
                             legend=dict(orientation='h',x=0,y=-.2))
        figures.append({'key':key,'figure':figure.to_plotly_json()})
    rows = [{'name':name,'portfolio':value,'benchmark':evaluation.result['equal_weight']['metrics'][name]}
            for name,value in evaluation.result['portfolio']['metrics'].items()]
    allocations = list(zip(evaluation.dataset.prices['symbols'],evaluation.result['portfolio']['initial_weights']))
    return render(request,'lab/evaluation.html',{'evaluation':evaluation,'charts':figures,'metrics':rows,'allocations':allocations})
