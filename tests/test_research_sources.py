from datetime import datetime

import pytest

from tradingagents import research_sources as sources
from tradingagents.dataflows.errors import VendorUnavailableError


def test_context_is_dated_attributed_and_reuses_daily_inputs(monkeypatch):
    calls = []
    monkeypatch.setattr(sources, "fetch_fear_greed_history", lambda: {"history": True})
    monkeypatch.setattr(sources, "render_fear_greed", lambda history, day: f"Bitcoin proxy {day}")
    monkeypatch.setattr(sources, "render_gdelt_events", lambda day, cache: f"GDELT {day.date()}")
    monkeypatch.setattr(sources, "get_global_news", lambda day: calls.append(day) or "Global news")
    monkeypatch.setattr(sources, "get_macro_data", lambda name, day: f"**Latest:** {name} {day}")
    monkeypatch.setattr(sources, "get_news", lambda ticker, start, end: f"News {ticker} {start} {end}")
    check = sources.build_source_check()
    first = check("BTC-USD", datetime(2024, 1, 8))
    second = check("ETH-USD", datetime(2024, 1, 8))
    assert calls == ["2024-01-08"]
    assert "Bitcoin proxy 2024-01-08" in first["context"]
    assert "**Latest:** cpi 2024-01-07" in first["context"]
    assert "News ETH-USD 2024-01-01 2024-01-08" in second["context"]
    assert first["coverage"]["status"] == "partial"
    assert "No historical Reddit" in first["coverage"]["social"]


def test_unavailable_essential_data_stops_preflight(monkeypatch):
    monkeypatch.setattr(sources, "fetch_fear_greed_history", lambda: {})
    monkeypatch.setattr(sources, "get_global_news", lambda day: "DATA_UNAVAILABLE")
    check = sources.build_source_check()
    with pytest.raises(VendorUnavailableError, match="global news unavailable"):
        check("BTC-USD", datetime(2024, 1, 8))
