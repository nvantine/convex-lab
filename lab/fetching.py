"""One resumable batch at a time. Network work never holds a DB transaction."""

from datetime import timedelta
import numpy as np
import pandas as pd
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from core.data import aligned_prices
from core.parser import ProblemError
from core.providers import fetch_prices
from lab.models import Dataset, FetchRequest


def pending(record):
    return [
        s for s in record.symbols if s not in record.series and s not in record.errors
    ]


def cached_series(record, symbol):
    if not record.prefer_cache:
        return None
    cutoff = timezone.now() - timedelta(hours=settings.LAB_CACHE_HOURS)
    candidates = FetchRequest.objects.filter(
        owner=record.owner,
        workspace=record.workspace,
        source=record.source,
        start__lte=record.start,
        end__gte=record.end,
        completed_at__gte=cutoff,
    ).exclude(pk=record.pk)
    for old in candidates:
        if symbol in old.series:
            item = old.series[symbol]
            from django.utils.dateparse import parse_datetime

            fetched_at = parse_datetime(item.get("fetched_at", ""))
            if fetched_at is None or fetched_at < cutoff:
                continue
            selected = [
                (d, v)
                for d, v in zip(item["dates"], item["values"])
                if str(record.start) <= d <= str(record.end)
            ]
            if selected:
                return {
                    **item,
                    "dates": [d for d, v in selected],
                    "values": [v for d, v in selected],
                }, old.provenance
    return None


def finalize(record, symbols=None):
    from lab.data_views import data_fingerprint

    symbols = record.symbols if symbols is None else symbols
    if not symbols or any(s not in record.series for s in symbols):
        raise ProblemError(
            "Fetch at least one valid symbol before saving available assets."
        )
    frame = pd.DataFrame(
        {
            s: pd.Series(
                record.series[s]["values"],
                index=pd.to_datetime(record.series[s]["dates"]),
                dtype=float,
            )
            for s in symbols
        }
    )
    payload, coverage = aligned_prices(
        frame, symbols, maximum=settings.LAB_MAX_PRICE_ROWS
    )
    provenance = {
        **record.provenance,
        **coverage,
        "requested_start": str(record.start),
        "requested_end": str(record.end),
        "excluded_symbols": [s for s in record.symbols if s not in symbols],
    }
    digest = data_fingerprint(payload, provenance)
    dataset = Dataset.objects.filter(
        owner=record.owner, workspace=record.workspace, digest=digest
    ).first()
    if dataset is None:
        dataset = Dataset.objects.create(
            owner=record.owner,
            workspace=record.workspace,
            name=record.name,
            source=record.source,
            prices=payload,
            provenance=provenance,
            digest=digest,
        )
    record.dataset = dataset
    record.completed_at = timezone.now()
    record.message = (
        "Saved a frozen dataset. Existing experiments keep their original data."
    )


def next_batch(record, provider=None):
    provider = provider or fetch_prices
    now = timezone.now()
    # Compare-and-set protects double clicks, two tabs, and the scheduled refresh.
    acquired = (
        FetchRequest.objects.filter(pk=record.pk)
        .filter(Q(busy_until__isnull=True) | Q(busy_until__lt=now))
        .update(busy_until=now + timedelta(seconds=settings.LAB_FETCH_SECONDS + 60))
    )
    if not acquired:
        raise ProblemError(
            "A batch is already running for this request. Wait and refresh progress."
        )
    try:
        record.refresh_from_db()
        if record.dataset:
            return
        symbols = pending(record)[: record.batch_size]
        need = []
        for symbol in symbols:
            cached = cached_series(record, symbol)
            if cached:
                record.series[symbol], record.provenance = cached
            else:
                need.append(symbol)
        if need:
            try:
                frame, provenance = provider(
                    record.source,
                    need,
                    record.start,
                    record.end,
                    settings.LAB_FETCH_SECONDS,
                )
                record.provenance = provenance
                for symbol in need:
                    try:
                        aligned_prices(
                            frame, [symbol], maximum=settings.LAB_MAX_PRICE_ROWS
                        )
                        series = frame[symbol].copy()
                        series.index = (
                            pd.DatetimeIndex(series.index).tz_localize(None).normalize()
                        )
                        record.series[symbol] = {
                            "dates": series.index.strftime("%Y-%m-%d").tolist(),
                            "values": [
                                float(v) if np.isfinite(v) else None for v in series
                            ],
                            "fetched_at": timezone.now().isoformat(),
                            "provider": provenance,
                        }
                    except ProblemError as error:
                        record.errors[symbol] = str(error)
            except ProblemError as error:
                for symbol in need:
                    record.errors[symbol] = str(error)
        record.message = (
            f"{len(record.errors)} symbols need attention."
            if record.errors
            else "All batches so far succeeded."
        )
        if len(record.series) == len(record.symbols):
            try:
                finalize(record)
            except ProblemError as error:
                record.message = str(error)
        record.save(
            update_fields=[
                "series",
                "provenance",
                "errors",
                "message",
                "dataset",
                "completed_at",
                "updated_at",
            ]
        )
    finally:
        FetchRequest.objects.filter(pk=record.pk).update(busy_until=None)


def refresh_record(record, lease_owned=False):
    """Full adjusted-history refresh: never mix corporate-action scales."""
    from core.providers import last_completed_day

    now = timezone.now()
    if not lease_owned:
        acquired = (
            FetchRequest.objects.filter(pk=record.pk)
            .filter(Q(busy_until__isnull=True) | Q(busy_until__lt=now))
            .update(busy_until=now + timedelta(seconds=60))
        )
        if not acquired:
            raise ProblemError("A batch is running. Retry the refresh later.")
    try:
        record.refresh_from_db()
        record.end = max(record.end, last_completed_day())
        record.series = {}
        record.errors = {}
        record.dataset = None
        record.completed_at = None
        record.prefer_cache = False
        record.message = "Refreshing adjusted history in small batches. Prior snapshots remain saved."
        record.save(
            update_fields=[
                "end",
                "series",
                "errors",
                "dataset",
                "completed_at",
                "prefer_cache",
                "message",
                "updated_at",
            ]
        )
    finally:
        if not lease_owned:
            FetchRequest.objects.filter(pk=record.pk).update(busy_until=None)
