"""Historical daily bars only. Secrets never enter payloads, messages, or logs."""
from datetime import datetime, time, timedelta, timezone
from importlib.metadata import version
import os
from pathlib import Path
import time as clock
from threading import Lock
from zoneinfo import ZoneInfo
import pandas as pd
import requests
from dotenv import dotenv_values
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from core.parser import ProblemError
from curl_cffi.requests import Session

# yfinance's shared cookie/session state is process-wide. A second concurrent
# request gets a retry message rather than swapping another user's transport.
YAHOO_SLOT = Lock()


def last_completed_day(now=None):
    """Conservative US closing-bar cutoff; weekends roll back to Friday."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo('America/New_York'))
    day = local.date() if local.hour>=17 else local.date()-timedelta(days=1)
    while day.weekday()>=5:
        day-=timedelta(days=1)
    return day


class YahooBudgetSession(Session):
    """Use the public session hook to bound each request by the remaining budget."""
    def __init__(self, seconds):
        super().__init__(impersonate='chrome')
        self.deadline = clock.monotonic()+seconds

    def request(self, method, url, **kwargs):
        remaining = self.deadline-clock.monotonic()
        if remaining <= 0:
            raise ProblemError('yfinance fetch budget exhausted. Try fewer symbols or a shorter date window.')
        kwargs['timeout'] = min(10,remaining)
        return super().request(method,url,**kwargs)


class BudgetAdapter(requests.adapters.HTTPAdapter):
    """Apply socket timeouts and a cooperative page-request budget."""
    def __init__(self, seconds):
        super().__init__(max_retries=0)
        self.deadline = clock.monotonic()+seconds

    def send(self, request, **kwargs):
        remaining = self.deadline-clock.monotonic()
        if remaining <= 0:
            raise requests.Timeout('Historical data request budget exhausted.')
        kwargs['timeout'] = min(10, remaining)
        return super().send(request, **kwargs)


def credentials():
    key, secret = os.getenv('ALPACA_API_KEY'), os.getenv('ALPACA_SECRET_KEY')
    if key or secret:
        if not key or not secret:
            raise ProblemError('Set both ALPACA_API_KEY and ALPACA_SECRET_KEY in your private .env. Never put keys in a form or chat.')
        return key, secret
    default = Path(__file__).resolve().parents[2]/'portfolio-lab'/'.env'
    path = Path(os.getenv('ALPACA_ENV_FILE') or default).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1]/path
    values = dotenv_values(path) if path.is_file() else {}
    key, secret = values.get('ALPACA_API_KEY'), values.get('ALPACA_SECRET_KEY')
    if not key or not secret:
        raise ProblemError('Alpaca credentials are missing. Set ALPACA_ENV_FILE to your existing private credentials file, or set both Alpaca variables in .env. You can also choose yfinance.')
    return key, secret


def fetch_prices(source, symbols, start, end, seconds=20):
    """Both providers take inclusive completed-day dates; never switch providers silently."""
    if source not in ('alpaca','yfinance'):
        raise ProblemError('Choose Alpaca or yfinance.')
    try:
        if source == 'alpaca':
            key, secret = credentials()
            client = StockHistoricalDataClient(api_key=key, secret_key=secret)
            # alpaca-py 0.44 has no public timeout option. Its Requests transport
            # was inspected and pinned; adapter behavior is covered by unit tests.
            client._session.mount('https://', BudgetAdapter(seconds))
            client._retry = 0  # Avoid the SDK's 30-second sleeps on rate limits.
            request = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Day,
                start=datetime.combine(start, time.min, tzinfo=timezone.utc),
                end=datetime.combine(end+timedelta(days=1), time.min, tzinfo=timezone.utc),
                adjustment=Adjustment.ALL, feed=DataFeed.IEX)
            try:
                bars = client.get_stock_bars(request).data
            finally:
                client._session.close()
            frame = pd.DataFrame({symbol: pd.Series({bar.timestamp.date():float(bar.close) for bar in bars.get(symbol,[])}, dtype=float)
                                  for symbol in symbols})
            provenance = {'provider':'alpaca', 'feed':'iex', 'adjustment':'all', 'library_version':version('alpaca-py')}
        else:
            import yfinance as yf
            if not YAHOO_SLOT.acquire(blocking=False):
                raise ProblemError('Another yfinance fetch is running. Please retry when it finishes.')
            try:
                with YahooBudgetSession(seconds) as session:
                    frame = yf.download(symbols, start=start.isoformat(), end=(end+timedelta(days=1)).isoformat(),
                        interval='1d', auto_adjust=True, actions=False, repair=False, keepna=True,
                        threads=False, progress=False, timeout=min(10,seconds), multi_level_index=True,session=session)
                    if clock.monotonic() >= session.deadline:
                        raise ProblemError('yfinance fetch budget exhausted. Try fewer symbols or a shorter date window.')
            finally:
                YAHOO_SLOT.release()
            if frame is None or frame.empty or 'Close' not in frame.columns.get_level_values(0):
                raise ProblemError('yfinance returned no daily prices. Check symbols and dates or retry later.')
            frame = frame['Close']
            provenance = {'provider':'yfinance', 'feed':'Yahoo historical', 'adjustment':'auto_adjust=True',
                          'library_version':version('yfinance')}
        # Vendors may include an endpoint bar; filter by our inclusive dates.
        frame.index = pd.to_datetime(frame.index)
        mask = (frame.index.date >= start) & (frame.index.date <= end)
        return frame.loc[mask], provenance
    except ProblemError:
        raise
    except Exception as error:
        # Provider exceptions can include request details: never return their text.
        code = getattr(error,'status_code',None)
        if source=='alpaca' and code in (401,403):
            raise ProblemError(f'Alpaca denied historical data access (HTTP {code}). Check that both keys are current and that your data subscription permits IEX historical bars.') from None
        if source=='alpaca' and code==429:
            raise ProblemError('Alpaca rate limit reached (HTTP 429). Wait before retrying; successful batches remain saved.') from None
        raise ProblemError(f'{source} could not fetch daily prices. Check credentials/access, ticker spelling, network connectivity, or rate limits; retry or explicitly choose another provider.') from None
