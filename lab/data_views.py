"""Small synchronous data/validation flows. Numerical work stays in core/."""
from datetime import date, timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.utils import timezone
import numpy as np
import plotly.graph_objects as go
from core.data import aligned_prices, content_digest, price_frame, problem_from_training, split_windows, estimates_edited
from core.rolling import evaluate_portfolios, rebalance_indices, refit_spec
from core.parser import ProblemError, build_problem
from core.providers import fetch_prices, last_completed_day
from lab.forms import DatasetForm, TrainingForm, EvaluationForm
from lab.models import Dataset, Evaluation, Experiment, Problem, FetchRequest, ResearchRun
from lab import fetching
from lab.request_limits import SOLVE_SLOTS
from lab.workspaces import scoped, workspace_for, request_scope
from lab import services

DEFAULT_SYMBOLS = 'SPY, QQQ, IWM, EFA, EEM, AGG, TLT, LQD, HYG, GLD, VNQ, XLE, XLK, XLV, XLF, DBC'
TICKET_SALT = 'convex-lab-final-holdout'


def existing_holdout(request, dataset):
    return scoped(Evaluation, request).filter(dataset_digest=dataset.digest, window='holdout').first()


def holdout_opening(request, dataset):
    return scoped(ResearchRun, request).filter(dataset_digest=dataset.digest, holdout_claim=True).first()


def data_fingerprint(payload, provenance):
    # Column permutations do not create another final holdout on identical data.
    order = np.argsort(payload['symbols'])
    return content_digest({'source':provenance['provider'], 'adjustment':provenance['adjustment'],
        'feed':provenance['feed'], 'dates':payload['dates'], 'symbols':sorted(payload['symbols']),
        'values':np.asarray(payload['values'])[:,order].tolist()})


@login_required
def datasets(request):
    end = last_completed_day()
    form = DatasetForm(request.POST if request.method=='POST' else None, initial={
        'name':'Market history', 'source':'alpaca','symbols':DEFAULT_SYMBOLS, 'start':end-timedelta(days=365*5), 'end':end})
    if not request.user.is_staff:
        form.fields['refresh_daily'].disabled=True
        form.initial['refresh_daily']=False
    if request.method=='POST' and form.is_valid():
        if request.POST.get('action')=='start' or len(form.cleaned_data['symbols'])>5:
            values=form.cleaned_data
            record=FetchRequest.objects.create(owner=request.user,workspace=workspace_for(request),name=values['name'],
                source=values['source'],symbols=values['symbols'],start=values['start'],end=values['end'],
                batch_size=values['batch_size'] or 5,prefer_cache=values['prefer_cache'],
                refresh_daily=values['refresh_daily'] and request.user.is_staff)
            return redirect('fetch_progress',pk=record.pk)
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
    return render(request,'lab/datasets.html',{'form':form,'datasets':scoped(Dataset,request),'asset_limit':settings.LAB_MAX_ASSETS,
        'fetch_requests':scoped(FetchRequest,request),'is_owner':request.user.is_staff})


@login_required
def dataset_detail(request,pk):
    dataset = get_object_or_404(scoped(Dataset,request),pk=pk)
    windows = split_windows(dataset.prices)
    form = TrainingForm(request.POST if request.method=='POST' else None, initial={'preset':'min-variance','estimator':'ledoit-wolf'})
    if request.method=='POST' and form.is_valid():
        try:
            from lab.views import limits
            draft = services.training_problem(request_scope(request), dataset, **form.cleaned_data)
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
        'holdout':existing_holdout(request,dataset), 'holdout_run':holdout_opening(request,dataset)})


usable_variables = services.usable_variables
evaluation_inputs = services.evaluation_inputs
provenance_notice = services.provenance_notice


def save_evaluation(request, experiment, dataset, variable, window, options):
    if not SOLVE_SLOTS.acquire(blocking=False):
        raise ProblemError('Other numerical requests are running. Please retry shortly.')
    try:
        return services.save_evaluation(request_scope(request), experiment, dataset, variable, window,
                                        options, evaluator=evaluate_portfolios)
    finally:
        SOLVE_SLOTS.release()


@login_required
def evaluation_setup(request,pk):
    experiment = get_object_or_404(scoped(Experiment,request),pk=pk)
    variables = usable_variables(experiment)
    if not variables:
        return HttpResponse('Evaluation needs a verified optimum with a decision vector. For a frontier, save a chosen solution first.',status=400)
    binding = experiment.spec.get('data',{})
    form = EvaluationForm(request.POST if request.method=='POST' else None,datasets=scoped(Dataset,request),variables=variables,
        spec=experiment.spec,initial={'dataset':binding.get('dataset_id'),'variable':'w' if 'w' in variables else variables[0]})
    if request.method=='POST' and form.is_valid():
        try:
            dataset,variable = form.cleaned_data['dataset'],form.cleaned_data['variable']
            weights = evaluation_inputs(experiment,dataset,variable)
            action = request.POST.get('action','validation')
            if action=='review_holdout':
                existing=existing_holdout(request,dataset)
                if existing:
                    messages.info(request,'The final holdout for this snapshot is already open. Returning its frozen result.')
                    return redirect('evaluation',pk=existing.pk)
                opening=holdout_opening(request,dataset)
                if opening:
                    messages.info(request,'The final holdout opening is already recorded. Showing its saved research evidence.')
                    return redirect('research_run',pk=opening.pk)
            if form.options()['mode']=='rolling':
                from lab.views import limits
                window='holdout' if action=='review_holdout' else 'validation'
                span=split_windows(dataset.prices)[window]
                indices=rebalance_indices(price_frame(dataset.prices).index[span['start']+1:span['end']+1],form.options()['frequency'])
                if len(indices)>settings.LAB_MAX_REFITS:
                    raise ProblemError(f'This schedule needs {len(indices)} solves; the request limit is {settings.LAB_MAX_REFITS}. Choose a less frequent schedule.')
                candidate,_=refit_spec(experiment.spec,dataset.prices,span['start'],np.zeros(len(weights)),form.options())
                build_problem(candidate,limits())
            if action=='review_holdout':
                existing = existing_holdout(request,dataset)
                if existing:
                    messages.info(request,'The final holdout for this data snapshot has already been opened. Returning its frozen result.')
                    return redirect('evaluation',pk=existing.pk)
                ticket = signing.dumps({'experiment':str(experiment.pk),'dataset':str(dataset.pk),'variable':variable,
                    'options':form.options(),'workspace':str(workspace_for(request))},salt=TICKET_SALT)
                return render(request,'lab/confirm_holdout.html',{'experiment':experiment,'dataset':dataset,
                    'weights':list(zip(dataset.prices['symbols'],weights)),'window':split_windows(dataset.prices)['holdout'],
                    'ticket':ticket,'options':form.options(),'notice':provenance_notice(experiment),
                    'refit_limit':settings.LAB_MAX_REFITS,'evaluation_seconds':settings.LAB_EVALUATION_SECONDS})
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
    return render(request,'lab/evaluation.html',{'evaluation':evaluation,'charts':figures,'metrics':rows,'allocations':allocations,
        'trades':evaluation.result['portfolio'].get('trades',[]),'refits':enumerate(evaluation.result['portfolio'].get('refits',[]))})


@login_required
def rebalance_detail(request,pk,index):
    from lab.views import limits
    evaluation=get_object_or_404(scoped(Evaluation,request),pk=pk)
    records=evaluation.result['portfolio'].get('refits',[])
    if not 0<=index<len(records):
        return HttpResponse('Unknown rolling solve.',status=404)
    record=records[index]
    spec,evidence=refit_spec(evaluation.experiment.spec,evaluation.dataset.prices,record['signal_index'],record['previous_weights'],evaluation.result['portfolio']['settings'])
    if evidence['parameter_digest']!=record['parameter_digest']:
        return HttpResponse('Estimator reconstruction differs from the frozen fingerprint. Restore the recorded dependency versions before inspecting this math.',status=409)
    return render(request,'lab/rebalance.html',{'evaluation':evaluation,'experiment':evaluation.experiment,'record':record,'preview':build_problem(spec,limits()).preview()})


def progress_payload(record):
    return {'completed':len(record.series),'total':len(record.symbols),'pending':len(fetching.pending(record)),
            'errors':record.errors,'message':record.message,'busy':bool(record.busy_until and record.busy_until>timezone.now()),
            'available':[s for s in record.symbols if s in record.series],
            'dataset_url':reverse('dataset',args=[record.dataset_id]) if record.dataset_id else None}


@login_required
def fetch_progress(request,pk):
    record=get_object_or_404(scoped(FetchRequest,request),pk=pk)
    return render(request,'lab/fetch_progress.html',{'record':record,'progress':progress_payload(record),
        'available':[s for s in record.symbols if s in record.series]})


@login_required
@require_POST
def fetch_batch(request,pk):
    record=get_object_or_404(scoped(FetchRequest,request),pk=pk)
    if not SOLVE_SLOTS.acquire(blocking=False):
        return JsonResponse({'error':'Other requests are running. Please retry shortly.'},status=503)
    try:
        fetching.next_batch(record,provider=fetch_prices)
        record.refresh_from_db()
        return JsonResponse(progress_payload(record))
    except ProblemError as error:
        return JsonResponse({'error':str(error)},status=409)
    finally:
        SOLVE_SLOTS.release()


@login_required
@require_POST
def fetch_action(request,pk):
    from django.db.models import Q
    from django.utils import timezone
    record=get_object_or_404(scoped(FetchRequest,request),pk=pk)
    now=timezone.now()
    locked=scoped(FetchRequest,request).filter(pk=pk).filter(Q(busy_until__isnull=True)|Q(busy_until__lt=now)).update(busy_until=now+timedelta(seconds=60))
    if not locked:
        return HttpResponse('A batch is running. Wait before changing this request.',status=409)
    try:
        record.refresh_from_db()
        action=request.POST.get('action')
        if action=='retry':
            record.errors={};record.batch_size=1;record.message='Retrying unfinished symbols individually.'
        elif action=='available' and request.POST.get('confirm')=='on':
            fetching.finalize(record,[s for s in record.symbols if s in record.series])
        elif action=='refresh':
            fetching.refresh_record(record,lease_owned=True)
        elif action=='watch' and request.user.is_staff:
            record.refresh_daily=request.POST.get('enabled')=='on'
        else:
            return HttpResponse('Choose an action and explicitly confirm any asset exclusions.',status=400)
        record.save()
    except ProblemError as error:
        messages.error(request,str(error))
    finally:
        FetchRequest.objects.filter(pk=pk).update(busy_until=None)
    return redirect('fetch_progress',pk=pk)
