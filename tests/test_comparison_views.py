from django.test import Client
from django.urls import reverse
import pytest
from lab.models import Dataset,Evaluation,Experiment
from conftest import post_data
from test_data_views import fetcher,fetch,imported_solution,options

pytestmark=pytest.mark.django_db


def test_compare_all_frozen_types_and_flag_assumptions(client,owner,fetcher):
    client.force_login(owner);fetch(client);dataset=Dataset.objects.get()
    experiment=imported_solution(client,dataset)
    setup=reverse('evaluate',args=[experiment.pk])
    a=client.post(setup,options(dataset));b=client.post(setup,options(dataset,cost_bps='20',frequency='weekly'))
    assert a.status_code==b.status_code==302
    ids=[str(e.pk) for e in Evaluation.objects.all()]
    response=client.get('/compare/',{'evaluation':ids,'experiment':str(experiment.pk)})
    assert response.status_code==200
    assert 'cost_bps' in response.context['differences'] and 'frequency' in response.context['differences']
    chart=response.context['charts'][0]['figure']
    assert chart['layout']['xaxis']['matches']=='x2'
    assert len(chart['data'])==4
    assert Evaluation.objects.filter(window='holdout').count()==0
    assert client.get('/compare/').status_code==200
    assert client.get('/compare/',{'experiment':'bad'}).status_code==400
    assert client.get('/compare/',{'evaluation':ids*4}).status_code==400


def test_optimization_vectors_and_guest_isolation(guest):
    one,two=Client(),Client();one.force_login(guest);two.force_login(guest)
    one.post('/problems/new/',post_data())
    a=Experiment.objects.get()
    data=post_data();data['constraints']+='\nw[0] <= 0.6';one.post('/problems/new/',data)
    b=Experiment.objects.latest('created_at')
    response=one.get('/compare/',{'experiment':[str(a.pk),str(b.pk)]})
    assert response.status_code==200 and len(response.context['charts'])==1
    assert 'Constraints' in response.context['differences']
    assert two.get('/compare/',{'experiment':str(a.pk)}).status_code==404


def test_rolling_refit_inspection_and_form_defaults(client,owner,fetcher):
    client.force_login(owner);fetch(client);dataset=Dataset.objects.get();experiment=imported_solution(client,dataset)
    setup=reverse('evaluate',args=[experiment.pk]);form=client.get(setup).context['form']
    assert form['mode'].value()=='rolling' and form['frequency'].value()=='monthly'
    result=client.post(setup,options(dataset,mode='rolling',frequency='weekly',lookback=30,
        estimator='sample',covariance_parameter='Sigma',solver='CLARABEL'))
    assert result.status_code==302
    evaluation=Evaluation.objects.get()
    assert len(evaluation.result['portfolio']['refits'])>5
    url=reverse('rebalance',args=[evaluation.pk,0]);page=client.get(url)
    assert page.status_code==200 and page.context['preview']['is_dcp']
    assert client.get(reverse('rebalance',args=[evaluation.pk,999])).status_code==404
    two=Client();assert two.get(url).status_code==302
    invalid=client.post(setup,options(dataset,mode='rolling',lookback=999,covariance_parameter='Sigma'))
    assert invalid.status_code==200 and b'Lookback must be between' in invalid.content


def test_rolling_holdout_freezes_policy_and_reuses_existing_before_preflight(client,owner,fetcher):
    client.force_login(owner);fetch(client);dataset=Dataset.objects.get();experiment=imported_solution(client,dataset)
    setup=reverse('evaluate',args=[experiment.pk])
    review=client.post(setup,options(dataset,action='review_holdout',mode='rolling',frequency='weekly',
        lookback=30,covariance_parameter='Sigma'))
    assert review.status_code==200
    response=client.post(reverse('confirm_holdout'),{'ticket':review.context['ticket'],'confirm':'on',
        'frequency':'daily','lookback':999})
    assert response.status_code==302
    evaluation=Evaluation.objects.get()
    assert evaluation.result['portfolio']['settings']['frequency']=='weekly'
    assert evaluation.result['portfolio']['settings']['lookback']==30
    again=client.post(setup,options(dataset,action='review_holdout',mode='rolling',lookback=999))
    assert again.url==response.url
