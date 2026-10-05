"""Historical SDK contract tests, with fake secrets and no network calls."""
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pandas as pd
import pytest
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.timeframe import TimeFrame
from core import providers
from core.parser import ProblemError


def test_alpaca_requests_only_adjusted_iex_daily_bars(monkeypatch):
    monkeypatch.setenv('ALPACA_API_KEY','fake-test-key')
    monkeypatch.setenv('ALPACA_SECRET_KEY','fake-test-secret')
    client=Mock()
    client.get_stock_bars.return_value=SimpleNamespace(data={'SPY':[
        SimpleNamespace(timestamp=datetime(2024,1,2,tzinfo=timezone.utc),close=100),
        SimpleNamespace(timestamp=datetime(2024,1,3,tzinfo=timezone.utc),close=101)]})
    ctor=Mock(return_value=client)
    monkeypatch.setattr(providers,'StockHistoricalDataClient',ctor)
    frame,provenance=providers.fetch_prices('alpaca',['SPY'],date(2024,1,2),date(2024,1,2))
    request=client.get_stock_bars.call_args.args[0]
    assert request.symbol_or_symbols==['SPY']
    assert request.feed==DataFeed.IEX and request.adjustment==Adjustment.ALL and request.timeframe.value=='1Day'
    # The SDK normalizes timezone-aware inputs to naive UTC for serialization.
    assert request.end==datetime(2024,1,3)
    assert request.start==datetime(2024,1,2)
    assert frame['SPY'].tolist()==[100]
    assert provenance['feed']=='iex' and provenance['adjustment']=='all'
    assert client._retry==0
    client._session.close.assert_called_once()
    assert client._session.mount.call_args.args[0]=='https://'


def test_provider_errors_never_echo_credentials(monkeypatch):
    monkeypatch.setattr(providers,'credentials',lambda:('fake-key','fake-secret'))
    monkeypatch.setattr(providers,'StockHistoricalDataClient',Mock(side_effect=RuntimeError('fake-secret')))
    with pytest.raises(ProblemError) as error:
        providers.fetch_prices('alpaca',['SPY'],date(2024,1,1),date(2024,2,1))
    assert 'fake-secret' not in str(error.value)
    assert 'credentials/access' in str(error.value)


def test_environment_and_private_file_credentials(monkeypatch,tmp_path):
    monkeypatch.delenv('ALPACA_API_KEY',raising=False)
    monkeypatch.delenv('ALPACA_SECRET_KEY',raising=False)
    path=tmp_path/'private.env'
    monkeypatch.setenv('ALPACA_ENV_FILE',str(path))
    with pytest.raises(ProblemError,match='missing'): providers.credentials()
    path.write_text('ALPACA_API_KEY=fake-key\nALPACA_SECRET_KEY=fake-secret\n')
    assert providers.credentials()==('fake-key','fake-secret')
    monkeypatch.setenv('ALPACA_API_KEY','other-fake-key')
    with pytest.raises(ProblemError,match='both'): providers.credentials()
    monkeypatch.setenv('ALPACA_SECRET_KEY','other-fake-secret')
    assert providers.credentials()==('other-fake-key','other-fake-secret')


def test_yfinance_explicit_adjustment_inclusive_end_and_session(monkeypatch):
    import yfinance
    index=pd.to_datetime(['2024-01-02','2024-01-03'])
    frame=pd.DataFrame([[100],[101]],index=index,columns=pd.MultiIndex.from_tuples([('Close','SPY')]))
    download=Mock(return_value=frame)
    monkeypatch.setattr(yfinance,'download',download)
    result,provenance=providers.fetch_prices('yfinance',['SPY'],date(2024,1,2),date(2024,1,2))
    options=download.call_args.kwargs
    assert options['auto_adjust'] and options['keepna']
    assert not options['threads'] and not options['repair']
    assert options['end']=='2024-01-03'
    assert isinstance(options['session'],providers.YahooBudgetSession)
    assert result['SPY'].tolist()==[100]
    assert provenance['provider']=='yfinance'


def test_empty_yfinance_and_concurrent_fetch_are_clear(monkeypatch):
    import yfinance
    monkeypatch.setattr(yfinance,'download',Mock(return_value=pd.DataFrame()))
    with pytest.raises(ProblemError,match='no daily prices'):
        providers.fetch_prices('yfinance',['BAD'],date(2024,1,1),date(2024,2,1))
    providers.YAHOO_SLOT.acquire()
    try:
        with pytest.raises(ProblemError,match='Another'):
            providers.fetch_prices('yfinance',['SPY'],date(2024,1,1),date(2024,2,1))
    finally:
        providers.YAHOO_SLOT.release()


def test_request_budget_on_both_transports(monkeypatch):
    adapter=providers.BudgetAdapter(20)
    adapter.deadline=10
    monkeypatch.setattr(providers.clock,'monotonic',lambda:8)
    parent=Mock(return_value=object())
    monkeypatch.setattr(providers.requests.adapters.HTTPAdapter,'send',parent)
    adapter.send(object())
    assert parent.call_args.kwargs['timeout']==2
    with providers.YahooBudgetSession(20) as session:
        session.deadline=10
        call=Mock(return_value=object())
        monkeypatch.setattr(providers.Session,'request',call)
        session.request('GET','https://example.test')
        assert call.call_args.kwargs['timeout']==2
        monkeypatch.setattr(providers.clock,'monotonic',lambda:11)
        with pytest.raises(ProblemError,match='budget'): session.request('GET','https://example.test')
    with pytest.raises(providers.requests.Timeout): adapter.send(object())


def test_pinned_sdk_transport_still_has_expected_fields():
    # No network: construction validates the private transport compatibility.
    with providers.StockHistoricalDataClient('fake-key','fake-secret')._session as session:
        assert isinstance(session,providers.requests.Session)


@pytest.mark.parametrize('instant,expected',[
    ('2026-10-05T20:30:00+00:00','2026-10-02'),
    ('2026-10-05T21:30:00+00:00','2026-10-05'),
    ('2026-10-04T22:30:00+00:00','2026-10-02'),
    ('2026-12-07T21:30:00+00:00','2026-12-04'),
    ('2026-12-07T22:30:00+00:00','2026-12-07')])
def test_completed_day_cutoff_accounts_for_weekends_and_dst(instant,expected):
    assert providers.last_completed_day(datetime.fromisoformat(instant)).isoformat()==expected


@pytest.mark.parametrize('code',[401,403,429])
def test_alpaca_access_and_rate_limit_errors_are_specific_but_sanitized(monkeypatch,code):
    monkeypatch.setattr(providers,'credentials',lambda:('fake','fake'))
    error=RuntimeError('private-secret');error.status_code=code
    monkeypatch.setattr(providers,'StockHistoricalDataClient',Mock(side_effect=error))
    with pytest.raises(ProblemError,match=str(code)) as caught:
        providers.fetch_prices('alpaca',['SPY'],date(2024,1,1),date(2024,2,1))
    assert 'private-secret' not in str(caught.value)
