from types import SimpleNamespace

import pytest
import requests

from tradingagents.dataflows import router
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.errors import VendorNotConfiguredError, VendorUnavailableError
from tradingagents.dataflows.vendors import alpaca_news
from tradingagents.default_config import build_default_config


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "private_key_id")
    monkeypatch.setenv("ALPACA_API_SECRET", "private_secret")


def article(identifier, created="2025-01-01T12:00:00Z", updated="2025-01-01T12:00:00Z"):
    return {"id": identifier, "created_at": created, "updated_at": updated,
            "headline": f"News {identifier}", "summary": "Summary", "url": "https://example.com",
            "source": "benzinga"}


def test_paginated_crypto_snapshot_excludes_later_revisions_and_includes_last_day(credentials, monkeypatch):
    pages = [
        {"news": [article(1, created="2025-01-01T23:59:59Z", updated="2025-01-01T23:59:59Z"),
                  article(2, updated="2025-01-02T00:00:00Z")], "next_page_token": "opaque"},
        {"news": [article(3, created="2025-01-02T00:00:00Z", updated="2025-01-02T00:00:00Z"),
                  article(4, updated="2025-01-01T12:00:00")], "next_page_token": None},
    ]
    calls = []

    def get(url, params, headers, timeout):
        calls.append((url, params.copy(), headers.copy()))
        return SimpleNamespace(status_code=200, json=lambda: pages.pop(0))

    monkeypatch.setattr(requests, "get", get)
    result = alpaca_news.fetch_news("2025-01-01", "2025-01-01", "BTC-USD")
    assert calls[0][1]["symbols"] == "BTCUSD"
    assert calls[0][1]["end"] == "2025-01-02T00:00:00+00:00"
    assert calls[1][1]["page_token"] == "opaque"
    assert [a["id"] for a in result["articles"]] == ["1"]
    assert result["discarded"] == {"invalid_timestamp": 1, "outside_window": 1,
                                   "revised_after_cut": 1, "duplicate": 0}
    assert result["page_chain"][0]["request_cursor_sha256"] is None
    assert result["page_chain"][0]["next_cursor_sha256"] == result["page_chain"][1]["request_cursor_sha256"]
    assert result["page_chain"][1]["next_cursor_sha256"] is None
    assert sum(page["count"] for page in result["page_chain"]) == len(result["articles"]) + sum(result["discarded"].values())
    assert "private" not in str(result) and "opaque" not in str(result)
    report = alpaca_news._report(result, 10)
    assert alpaca_news.snapshot_sha256(result) in report
    assert "News 1" in report and "News 2" not in report


@pytest.mark.parametrize("ticker,expected", [("BTC-USD", "BTCUSD"), ("ETH-USD", "ETHUSD"),
                                             ("SOL-USD", "SOLUSD"), ("SPY", "SPY")])
def test_symbol_mapping(ticker, expected):
    assert alpaca_news._symbol(ticker) == expected


def test_rejects_unsupported_symbols_and_missing_credentials(monkeypatch):
    with pytest.raises(ValueError, match="unsupported"):
        alpaca_news.fetch_news("2025-01-01", "2025-01-01", "EURUSD=X")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    with pytest.raises(VendorNotConfiguredError):
        alpaca_news.fetch_news("2025-01-01", "2025-01-01", "SPY")


def test_repeated_page_token_fails_closed(credentials, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: {"news": [article(1)], "next_page_token": "same"}))
    with pytest.raises(VendorUnavailableError, match="repeated"):
        alpaca_news.fetch_news("2025-01-01", "2025-01-01", "SPY")


def test_network_exception_does_not_leak_credentials(credentials, monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("private_key_id private_secret")
    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(VendorUnavailableError) as exc:
        alpaca_news.fetch_news("2025-01-01", "2025-01-01", "SPY")
    assert "private" not in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def test_rate_limit_is_explicit_and_does_not_expose_response(credentials, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: SimpleNamespace(
        status_code=429, text="private_key_id private_secret"))
    with pytest.raises(VendorUnavailableError, match="HTTP 429") as exc:
        alpaca_news.fetch_news("2025-01-01", "2025-01-01", "SPY")
    assert "private" not in str(exc.value)


def test_page_limit_fails_rather_than_returning_partial_data(credentials, monkeypatch):
    monkeypatch.setattr(alpaca_news, "MAX_PAGES", 1)
    monkeypatch.setattr(requests, "get", lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: {"news": [article(1)], "next_page_token": "next"}))
    with pytest.raises(VendorUnavailableError, match="pagination limit"):
        alpaca_news.fetch_news("2025-01-01", "2025-01-01", "SPY")


def test_empty_result_is_unavailable_not_an_absence(credentials, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: {"news": [], "next_page_token": None}))
    assert "DATA_UNAVAILABLE" in alpaca_news.get_news("SPY", "2025-01-01", "2025-01-01")


def test_router_uses_alpaca_only_for_selected_news_tools(credentials, monkeypatch):
    calls = []
    def get(url, params, headers, timeout):
        calls.append(params.copy())
        return SimpleNamespace(status_code=200, json=lambda: {"news": [article(1)], "next_page_token": None})
    monkeypatch.setattr(requests, "get", get)
    with run_config({"tool_vendors": {"get_news": "alpaca", "get_global_news": "alpaca"}}):
        assert "News 1" in router.route_to_vendor("get_news", "ETH-USD", "2025-01-01", "2025-01-01")
        assert "News 1" in router.route_to_vendor("get_global_news", "2025-01-01", 1, 10)
        assert router.get_vendor("core_stock_apis", "get_stock_data") == "yfinance"
        assert router.get_vendor("macro_data", "get_macro_indicators") == "fred"
    assert calls[0]["symbols"] == "ETHUSD" and "symbols" not in calls[1]


def test_news_vendor_env_does_not_change_prices_macro_or_insider(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_NEWS_VENDOR", "alpaca")
    config = build_default_config()
    with run_config(config):
        assert router.get_vendor("news_data", "get_news") == "alpaca"
        assert router.get_vendor("news_data", "get_global_news") == "alpaca"
        assert router.get_vendor("news_data", "get_insider_transactions") == "yfinance"
        assert router.get_vendor("core_stock_apis", "get_stock_data") == "yfinance"
        assert router.get_vendor("macro_data", "get_macro_indicators") == "fred"
