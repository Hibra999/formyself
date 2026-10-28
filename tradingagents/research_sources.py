"""Prepare dated, explicitly partial inputs for the research graph."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.vendors.alpaca_news import get_global_news, get_news
from tradingagents.dataflows.vendors.fear_greed import fetch_fear_greed_history, render_fear_greed
from tradingagents.dataflows.vendors.fred import get_macro_data
from tradingagents.dataflows.vendors.gdelt_events import render_gdelt_events


def build_source_check():
    """Load market sentiment once and return dated preflight/context preparation."""
    sentiment = fetch_fear_greed_history()
    by_day, gdelt_cache = {}, {}

    def check(ticker, when):
        if isinstance(when, datetime):
            if when.utcoffset() is not None:
                raise ValueError("research dates must be timezone-naive calendar dates")
            day = when.date()
        elif isinstance(when, date):
            day = when
        else:
            day = date.fromisoformat(str(when))
        key = day.isoformat()
        if key not in by_day:
            global_news = get_global_news(key)
            if "DATA_UNAVAILABLE" in global_news:
                raise VendorUnavailableError(f"Alpaca global news unavailable for {key}")
            macro_as_of = (day - timedelta(days=1)).isoformat()
            macro = [get_macro_data(indicator, macro_as_of) for indicator in ("cpi", "fed_funds_rate")]
            if any("**Latest:**" not in item for item in macro):
                raise VendorUnavailableError(f"FRED macro observations unavailable for {key}")
            index = render_fear_greed(sentiment, key)
            gdelt = render_gdelt_events(datetime.combine(day, datetime.min.time(), tzinfo=UTC), gdelt_cache)
            by_day[key] = (global_news, macro, index, gdelt)
        global_news, macro, index, gdelt = by_day[key]
        news = get_news(ticker, (day - timedelta(days=7)).isoformat(), key)
        if "DATA_UNAVAILABLE" in news:
            raise VendorUnavailableError(f"Alpaca news unavailable for {ticker} on {key}")
        context = "\n\n".join((news, global_news, *macro, index, gdelt))
        return {
            "context": context,
            "coverage": {
                "status": "partial",
                "prices": "Yahoo Finance daily closes",
                "news": "Alpaca/Benzinga; later revisions excluded; archive completeness unknown",
                "macro": "FRED CPI and federal funds rate at the prior day's vintage",
                "sentiment": "Alternative.me Bitcoin proxy, previous day; publication time unverified",
                "geopolitics": "GDELT records by date added; events may be older; two-day lag assumed",
                "social": "No historical Reddit or Stocktwits archive",
                "point_in_time": "Historical availability and model knowledge not fully verified",
            },
        }

    return check
