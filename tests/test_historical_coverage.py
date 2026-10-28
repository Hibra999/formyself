from datetime import UTC, datetime, timedelta, timezone

import pytest

from tradingagents.historical_coverage import audit_coverage

START = datetime(2025, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


def test_price_gaps_duplicates_and_candles_not_available_at_decision():
    candles = [
        {"open_time": START, "available_at": START + HOUR},
        {"open_time": START, "available_at": START + HOUR},
        {"open_time": START + HOUR, "available_at": START + 3 * HOUR},
    ]
    result = audit_coverage(START, START + 2 * HOUR, HOUR, candles, {})["prices"]
    assert result == {
        "status": "timestamps_incomplete", "expected": 2, "usable": 1,
        "missing": [START + HOUR], "duplicates": [START], "rejected": 1,
    }


def test_news_coverage_stays_unknown_and_excludes_future_and_undated():
    records = [
        {"published_at": START, "available_at": START + HOUR},
        {"published_at": START, "available_at": START + 3 * HOUR},
        {"published_at": None, "available_at": START},
        {"published_at": START + 2 * HOUR, "available_at": START + 2 * HOUR},
    ]
    result = audit_coverage(START, START + 2 * HOUR, HOUR, [], {"news": records})
    assert result["sources"]["news"] == {
        "status": "observed", "coverage": "unknown", "usable": 1,
        "undated": 1, "outside_window": 1, "unavailable_at_decision": 1,
    }
    assert result["prices"]["missing"] == [START, START + HOUR]


def test_complete_prices_and_empty_source_do_not_claim_event_coverage():
    local = timezone(timedelta(hours=-6))
    candles = [
        {"open_time": START.astimezone(local), "available_at": START + HOUR},
        {"open_time": START + HOUR, "available_at": START + 2 * HOUR},
    ]
    result = audit_coverage(START, START + 2 * HOUR, HOUR, candles, {"macro": []})
    assert result["prices"]["status"] == "timestamps_complete"
    assert result["sources"]["macro"]["status"] == "no_usable_records"
    assert result["sources"]["macro"]["coverage"] == "unknown"
    assert result["sources"]["news"]["status"] == "no_usable_records"
    assert result["sources"]["sentiment"]["status"] == "no_usable_records"
    assert result["status"] == "incomplete"


def test_observed_events_do_not_establish_complete_coverage():
    event = {"published_at": START, "available_at": START + HOUR}
    candle = {"open_time": START, "available_at": START + HOUR}
    result = audit_coverage(START, START + HOUR, HOUR, [candle], {
        "news": [event], "macro": [event], "sentiment": [event],
    })
    assert result["status"] == "unknown"
    assert all(source["coverage"] == "unknown" for source in result["sources"].values())


def test_rejects_naive_timestamps_invalid_window_and_impossible_event():
    with pytest.raises(ValueError, match="timezone-aware"):
        audit_coverage(datetime(2025, 1, 1), START + HOUR, HOUR, [], {})
    with pytest.raises(ValueError, match="whole number"):
        audit_coverage(START, START + HOUR, timedelta(minutes=40), [], {})
    with pytest.raises(ValueError, match="precedes publication"):
        audit_coverage(START, START + HOUR, HOUR, [], {
            "news": [{"published_at": START + HOUR, "available_at": START}],
        })
