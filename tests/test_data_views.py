"""Exercise every data/evaluation view and the final-holdout gate without vendors."""
from copy import deepcopy
from datetime import date
from unittest.mock import Mock
import numpy as np
import pytest
from django.core import signing
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from core.data import aligned_prices
from core.parser import ProblemError
from lab import data_views
from lab.forms import initial_from_spec
from lab.models import Dataset, Evaluation, Experiment, Problem
from conftest import post_data
from test_data import synthetic_frame

pytestmark=pytest.mark.django_db


@pytest.fixture
def fetcher(monkeypatch):
    def fake(source,symbols,start,end,seconds):
        frame=synthetic_frame(tuple(symbols))
        # Unique final data sentinel; neither chart nor HTML may include it.
        frame.iloc[241:,0]=123456.789
        return frame,{'provider':source,'feed':'iex' if source=='alpaca' else 'Yahoo historical','adjustment':'all' if source=='alpaca' else 'auto_adjust=True','library_version':'test'}
    mock=Mock(side_effect=fake)
    monkeypatch.setattr(data_views,'fetch_prices',mock)
    return mock


def fetch(client,symbols='SPY, AGG',source='alpaca'):
    return client.post('/datasets/',{'name':'Test history','source':source,'symbols':symbols,'start':'2023-01-01','end':'2024-12-31'})


def imported_solution(client,dataset,preset='min-variance'):
    response=client.post(reverse('dataset',args=[dataset.pk]),{'preset':preset,'estimator':'ledoit-wolf','lookback':''})
    assert response.status_code==302
    problem=Problem.objects.latest('updated_at')
    data=post_data(problem.spec)
    response=client.post(response.url,data)
    assert response.status_code==302
    return Experiment.objects.latest('created_at')


def options(dataset,action='validation',**overrides):
    return {'dataset':str(dataset.pk),'variable':'w','cost_bps':'10','borrow_rate':'.03','financing_rate':'0','risk_free_rate':'0','action':action,**overrides}


@pytest.mark.parametrize('symbols',['SPY','SPY, AGG'])
@pytest.mark.parametrize('source',['alpaca','yfinance'])
def test_fetch_redirects_and_creates_one_or_two_assets(client,owner,fetcher,symbols,source):
    client.force_login(owner)
    assert client.get('/datasets/').status_code==200
    response=fetch(client,symbols,source)
    assert response.status_code==302
    dataset=Dataset.objects.get()
    assert len(dataset.prices['symbols'])==len(symbols.split(','))
    assert dataset.source==source
    detail=client.get(response.url)
    assert detail.status_code==200 and b'Final holdout locked' in detail.content
    assert b'123456.789' not in detail.content
    assert len(detail.context['chart']['data'][0]['y'])==241
    assert client.get('/').status_code==200
    with pytest.raises(ValidationError): dataset.save()


def test_actual_tickers_are_required_and_errors_are_visible(client,owner,fetcher):
    client.force_login(owner)
    for value in ('top 100 market cap nasdaq tickers','',','.join(['SPY']+[f'A{i}' for i in range(100)])):
        response=fetch(client,value)
        assert response.status_code==200
        assert b'errorlist' in response.content
        assert Dataset.objects.count()==0
    fetcher.assert_not_called()
    response=fetch(client,'spy spy agg')
    assert response.status_code==302
    assert Dataset.objects.get().prices['symbols']==['SPY','AGG']


def test_cached_fingerprint_does_not_reset_with_name_or_column_order(client,owner,fetcher):
    client.force_login(owner)
    fetch(client)
    dataset=Dataset.objects.get()
    reordered=deepcopy(dataset.prices)
    reordered['symbols'].reverse()
    reordered['values']=[row[::-1] for row in reordered['values']]
    assert data_views.data_fingerprint(reordered,dataset.provenance)==dataset.digest
    assert fetch(client).url==reverse('dataset',args=[dataset.pk])
    assert Dataset.objects.count()==1


def test_provider_failure_and_busy_slot_release(client,owner,fetcher,monkeypatch):
    client.force_login(owner)
    fetcher.side_effect=ProblemError('No prices for SPY. Retry later.')
    response=fetch(client)
    assert b'No prices for SPY' in response.content and Dataset.objects.count()==0
    assert data_views.SOLVE_SLOTS.acquire(blocking=False)
    data_views.SOLVE_SLOTS.release()
    slots=Mock(); slots.acquire.return_value=False
    monkeypatch.setattr(data_views,'SOLVE_SLOTS',slots)
    response=fetch(client)
    assert response.status_code==503 and response['Retry-After']=='3'
    slots.release.assert_not_called()


def test_training_problem_binding_and_validation_snapshot(client,owner,fetcher):
    client.force_login(owner); fetch(client)
    dataset=Dataset.objects.get()
    experiment=imported_solution(client,dataset)
    assert experiment.spec['data']['symbols']==['SPY','AGG']
    assert experiment.spec['data']['estimation']['observations']==180
    assert client.get(reverse('result',args=[experiment.pk])).status_code==200
    assert client.get(reverse('evaluate',args=[experiment.pk])).status_code==200
    response=client.post(reverse('evaluate',args=[experiment.pk]),options(dataset))
    assert response.status_code==302
    evaluation=Evaluation.objects.get()
    assert evaluation.window=='validation'
    assert evaluation.result['portfolio']['dates']==dataset.prices['dates'][181:241]
    assert 'unchanged' in evaluation.result['provenance_notice']
    assert client.get(response.url).status_code==200
    with pytest.raises(ValidationError): evaluation.save()
    second=client.post(reverse('evaluate',args=[experiment.pk]),options(dataset,cost_bps='20'))
    assert second.url!=response.url
    evaluation.refresh_from_db()
    assert evaluation.result['portfolio']['settings']['cost_bps']==10


def test_binding_survives_edit_clone_and_marks_edited_estimates(client,owner,fetcher):
    client.force_login(owner); fetch(client)
    dataset=Dataset.objects.get(); experiment=imported_solution(client,dataset)
    draft=experiment.problem
    changed=deepcopy(draft.spec)
    changed['parameters'][0]['value']=(np.asarray(changed['parameters'][0]['value'])*2).tolist()
    response=client.post(reverse('edit',args=[draft.pk]),post_data(changed,action='save'))
    assert response.status_code==302
    draft.refresh_from_db(); assert draft.spec['data']==experiment.spec['data']
    assert b'edited' in client.get(response.url).content
    clone=client.post(reverse('clone',args=[experiment.pk]))
    assert clone.status_code==302
    assert Problem.objects.latest('updated_at').spec['data']==experiment.spec['data']


def test_holdout_review_confirmation_frozen_options_and_one_final(client,owner,fetcher):
    client.force_login(owner); fetch(client)
    dataset=Dataset.objects.get(); experiment=imported_solution(client,dataset)
    setup=reverse('evaluate',args=[experiment.pk])
    review=client.post(setup,options(dataset,'review_holdout'))
    assert review.status_code==200 and b'Confirm final holdout' in review.content
    assert Evaluation.objects.count()==0 and b'123456.789' not in review.content
    ticket=review.context['ticket']
    assert client.get(reverse('confirm_holdout')).status_code==405
    assert client.post(reverse('confirm_holdout'),{'ticket':ticket}).status_code==400
    assert client.post(reverse('confirm_holdout'),{'ticket':ticket+'bad','confirm':'on'}).status_code==400
    response=client.post(reverse('confirm_holdout'),{'ticket':ticket,'confirm':'on','cost_bps':'999'})
    final=Evaluation.objects.get()
    assert final.window=='holdout'
    assert final.result['portfolio']['dates']==dataset.prices['dates'][241:]
    assert final.result['portfolio']['settings']['cost_bps']==10
    assert client.get(response.url).status_code==200
    again=client.post(reverse('confirm_holdout'),{'ticket':ticket,'confirm':'on'})
    assert again.url==response.url and Evaluation.objects.count()==1
    assert client.post(setup,options(dataset,'review_holdout',cost_bps='99')).url==response.url
    another=imported_solution(client,dataset,'mean-variance')
    assert client.post(reverse('evaluate',args=[another.pk]),options(dataset,'review_holdout')).url==response.url


def test_expired_confirmation(client,owner,fetcher,monkeypatch):
    client.force_login(owner); fetch(client)
    dataset=Dataset.objects.get(); experiment=imported_solution(client,dataset)
    response=client.post(reverse('evaluate',args=[experiment.pk]),options(dataset,'review_holdout'))
    future=signing.time.time()+601
    monkeypatch.setattr(signing.time,'time',lambda:future)
    expired=client.post(reverse('confirm_holdout'),{'ticket':response.context['ticket'],'confirm':'on'})
    assert expired.status_code==400 and Evaluation.objects.count()==0


def test_missing_mismatched_and_unverified_weights(client,owner,fetcher):
    client.force_login(owner)
    response=client.post('/problems/new/',post_data())
    experiment=Experiment.objects.get()
    assert b'No dataset exists' in client.get(reverse('evaluate',args=[experiment.pk])).content
    fetch(client,'SPY'); dataset=Dataset.objects.get()
    assert b'vector length' in client.post(reverse('evaluate',args=[experiment.pk]),options(dataset)).content
    imported=imported_solution(client,dataset)
    fetch(client,'SPY, AGG'); other=Dataset.objects.latest('created_at')
    assert b'different data snapshot' in client.post(reverse('evaluate',args=[imported.pk]),options(other)).content
    invalid=post_data(); invalid['constraints']+='\nw <= -1'
    client.post('/problems/new/',invalid)
    infeasible=Experiment.objects.latest('created_at')
    assert client.get(reverse('evaluate',args=[infeasible.pk])).status_code==400


def test_cross_guest_sessions_cannot_access_data_evaluations_or_confirmation(guest,fetcher):
    one,two=Client(),Client()
    one.force_login(guest);two.force_login(guest)
    fetch(one); dataset=Dataset.objects.get(); experiment=imported_solution(one,dataset)
    saved=one.post(reverse('evaluate',args=[experiment.pk]),options(dataset))
    review=one.post(reverse('evaluate',args=[experiment.pk]),options(dataset,'review_holdout'))
    for url in (reverse('dataset',args=[dataset.pk]),reverse('evaluate',args=[experiment.pk]),saved.url):
        assert two.get(url).status_code==404
    assert two.post(reverse('confirm_holdout'),{'ticket':review.context['ticket'],'confirm':'on'}).status_code==404
    assert two.post(reverse('dataset',args=[dataset.pk]),{'preset':'min-variance','estimator':'sample'}).status_code==404
    assert one.post(reverse('evaluate',args=[experiment.pk]),options(dataset,action='holdout')).status_code==200
    assert Evaluation.objects.filter(window='holdout').count()==0


def test_lookback_error_is_visible(client,owner,fetcher):
    client.force_login(owner);fetch(client);dataset=Dataset.objects.get()
    response=client.post(reverse('dataset',args=[dataset.pk]),{'preset':'cvar','estimator':'sample','lookback':'999'})
    assert response.status_code==200 and b'lookback must be between' in response.content
    assert Problem.objects.count()==0
