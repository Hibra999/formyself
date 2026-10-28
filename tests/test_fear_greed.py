from datetime import UTC, datetime

import pytest
import requests

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.vendors import fear_greed


def _reading(day, value="50", classification="Neutral"):
    timestamp = str(int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp()))
    return {"timestamp": timestamp, "value": value, "value_classification": classification}


def _reply(monkeypatch, data, metadata=None):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": data, "metadata": {"error": None} if metadata is None else metadata}

    def get(url, **kwargs):
        assert url == fear_greed.API_URL
        assert kwargs["params"]["limit"] == 0
        return Response()

    monkeypatch.setattr(requests, "get", get)


def test_as_of_uses_exact_previous_day_not_today_or_future(monkeypatch):
    _reply(monkeypatch, [_reading("2024-01-01", "20", "Extreme Fear"),
                         _reading("2024-01-02", "80", "Extreme Greed")])
    history = fear_greed.fetch_fear_greed_history()
    result = fear_greed.fear_greed_as_of(history, "2024-01-02")
    assert result["reading_date"] == "2024-01-01"
    assert result["value"] == 20
    assert result["available_assumption"] == "2024-01-02"
    text = fear_greed.render_fear_greed(history, "2024-01-02")
    assert fear_greed.SOURCE_URL in text
    assert "not ETH/SOL-specific" in text
    assert "publication time and revisions are not verified" in text


def test_missing_day_does_not_reuse_a_stale_value(monkeypatch):
    _reply(monkeypatch, [_reading("2024-01-01")])
    history = fear_greed.fetch_fear_greed_history()
    with pytest.raises(VendorUnavailableError, match="2024-01-02"):
        fear_greed.fear_greed_as_of(history, "2024-01-03")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        fear_greed.fear_greed_as_of(history, "2024-1-3")


@pytest.mark.parametrize("data", [
    [],
    [_reading("2024-01-01", "101")],
    [_reading("2024-01-01", "not a number")],
    [_reading("2024-01-01", classification="unknown")],
    [_reading("2024-01-01", classification=[])],
    [_reading("2024-01-01"), _reading("2024-01-01")],
    [{"timestamp": "x", "value": "20", "value_classification": "Fear"}],
])
def test_rejects_empty_invalid_or_duplicate_readings(monkeypatch, data):
    _reply(monkeypatch, data)
    with pytest.raises(VendorUnavailableError):
        fear_greed.fetch_fear_greed_history()


def test_provider_error_and_network_error_do_not_look_like_no_sentiment(monkeypatch):
    _reply(monkeypatch, [_reading("2024-01-01")], {"error": "provider error"})
    with pytest.raises(VendorUnavailableError):
        fear_greed.fetch_fear_greed_history()

    def fail(*args, **kwargs):
        raise requests.Timeout()

    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(VendorUnavailableError):
        fear_greed.fetch_fear_greed_history()
