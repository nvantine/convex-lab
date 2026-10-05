"""Batch durability, cache freshness, leases, and browser workspace boundaries."""
from datetime import timedelta
from io import StringIO
from unittest.mock import Mock
import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from core.parser import ProblemError
from lab import data_views, fetching
from lab.models import Dataset, FetchRequest
from test_data_views import fetcher

pytestmark=pytest.mark.django_db


def start(client,symbols='SPY,AGG',**kwargs):
    response=client.post('/datasets/',dict(name='Batches',source='alpaca',symbols=symbols,
        start='2023-01-01',end='2024-12-31',action='start',batch_size=5,**kwargs))
    assert response.status_code==302
    return FetchRequest.objects.latest('created_at')


def batch(client,record):
    return client.post(reverse('fetch_batch',args=[record.pk]))


def test_hundred_symbols_are_twenty_durable_batches(client,owner,fetcher):
    client.force_login(owner)
    record=start(client,','.join(f'A{i}' for i in range(100)))
    for i in range(20):
        response=batch(client,record)
        assert response.status_code==200
        assert response.json()['completed']==(i+1)*5
        assert '123456.789' not in response.content.decode()
        assert len(fetcher.call_args.args[1])==5
    assert fetcher.call_count==20
    record.refresh_from_db()
    assert record.dataset.prices['symbols']==record.symbols
    assert record.busy_until is None
    assert client.get(reverse('fetch_progress',args=[record.pk])).status_code==200


def test_partial_failure_retries_individually_without_repeating_good_symbols(client,owner,fetcher):
    client.force_login(owner);record=start(client)
    original=fetcher.side_effect
    def partial(*args):
        frame,meta=original(*args)
        return frame.drop(columns='AGG'),meta
    fetcher.side_effect=partial
    response=batch(client,record)
    assert response.json()['completed']==1 and response.json()['errors']['AGG']
    assert Dataset.objects.count()==0
    client.post(reverse('fetch_action',args=[record.pk]),{'action':'retry'})
    fetcher.side_effect=original
    assert batch(client,record).json()['dataset_url']
    assert fetcher.call_args.args[1]==['AGG']
    assert fetcher.call_count==2


def test_fresh_cache_is_scoped_and_never_rejuvenates_old_prices(client,owner,fetcher):
    client.force_login(owner);first=start(client);batch(client,first)
    second=start(client,prefer_cache='on');batch(client,second)
    assert fetcher.call_count==1
    assert Dataset.objects.count()==1
    first.refresh_from_db()
    for item in first.series.values(): item['fetched_at']=(timezone.now()-timedelta(days=2)).isoformat()
    first.save()
    # The reused cache carries original symbol timestamps too.
    second.refresh_from_db();second.series=first.series;second.save()
    third=start(client,prefer_cache='on');batch(client,third)
    assert fetcher.call_count==2


def test_leases_and_explicit_subset_confirmation(client,owner,fetcher):
    client.force_login(owner);record=start(client)
    record.busy_until=timezone.now()+timedelta(seconds=60);record.save()
    assert batch(client,record).status_code==409
    url=reverse('fetch_action',args=[record.pk])
    assert client.post(url,{'action':'refresh'}).status_code==409
    record.busy_until=None;record.save()
    assert client.post(url,{'action':'available'}).status_code==400
    assert client.post(url,{'action':'available','confirm':'on'}).status_code==302
    assert Dataset.objects.count()==0
    fetcher.side_effect=ProblemError('Rate limited; retry later.')
    assert batch(client,record).json()['errors']
    record.refresh_from_db();assert record.busy_until is None


def test_refresh_preserves_frozen_data_and_releases_lease(client,owner,fetcher):
    client.force_login(owner);record=start(client);batch(client,record)
    original=Dataset.objects.get();prices=original.prices
    client.post(reverse('fetch_action',args=[record.pk]),{'action':'refresh'})
    record.refresh_from_db()
    assert record.dataset is None and not record.series and record.busy_until is None
    original.refresh_from_db();assert original.prices==prices
    assert batch(client,record).status_code==200


def test_guest_requests_are_isolated_and_cannot_schedule(client,guest,fetcher):
    client.force_login(guest);record=start(client,refresh_daily='on')
    assert not record.refresh_daily
    two=Client();two.force_login(guest)
    for name in ('fetch_progress','fetch_batch','fetch_action'):
        url=reverse(name,args=[record.pk])
        assert two.get(url).status_code in (404,405)
        if name!='fetch_progress': assert two.post(url).status_code==404
    assert client.post(reverse('fetch_action',args=[record.pk]),{'action':'watch','enabled':'on'}).status_code==400


def test_daily_command_is_bounded_and_retries_previous_errors(client,owner,fetcher,monkeypatch):
    client.force_login(owner);record=start(client,refresh_daily='on')
    monkeypatch.setattr(fetching,'fetch_prices',fetcher)
    record.errors={'SPY':'old failure'};record.save()
    output=StringIO()
    call_command('refresh_datasets',owner=owner.username,max_batches=1,stdout=output)
    record.refresh_from_db()
    assert record.dataset and record.errors=={} and fetcher.call_count==1
    call_command('refresh_datasets',owner=owner.username,max_batches=1,stdout=output)
    assert fetcher.call_count==1
    assert 'historical batches' in output.getvalue()


def test_partial_asset_exclusion_is_explicit_and_recorded(client,owner,fetcher):
    client.force_login(owner);record=start(client)
    original=fetcher.side_effect
    fetcher.side_effect=lambda *a:(original(*a)[0].drop(columns='AGG'),original(*a)[1])
    batch(client,record)
    response=client.post(reverse('fetch_action',args=[record.pk]),{'action':'available','confirm':'on'})
    assert response.status_code==302
    record.refresh_from_db()
    assert record.dataset.prices['symbols']==['SPY']
    assert record.dataset.provenance['excluded_symbols']==['AGG']


def test_busy_slots_cache_failure_and_guest_scope(client,guest,fetcher,monkeypatch):
    client.force_login(guest);record=start(client);batch(client,record)
    two=Client();two.force_login(guest)
    other=start(two,prefer_cache='on');batch(two,other)
    assert fetcher.call_count==2
    capacity=Mock();capacity.acquire.return_value=False
    monkeypatch.setattr(data_views,'SOLVE_SLOTS',capacity)
    assert batch(client,record).status_code==503
    capacity.release.assert_not_called()
