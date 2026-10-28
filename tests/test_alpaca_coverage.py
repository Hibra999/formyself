from datetime import UTC, datetime, timedelta

import pytest

from tradingagents.dataflows.vendors.alpaca_news import snapshot_sha256
from tradingagents.historical_coverage import audit_alpaca_snapshot

START = datetime(2024, 1, 1, tzinfo=UTC)
END = START + timedelta(days=1)
TOKEN = "a" * 64


def _snapshot(articles=None):
    articles = [] if articles is None else articles
    return {
        "source": "alpaca", "symbol": "BTC/USD",
        "start": START.isoformat(), "end_exclusive": END.isoformat(),
        "pages": 1, "articles": articles,
        "discarded": {"invalid_timestamp": 0, "outside_window": 0,
                      "revised_after_cut": 0, "duplicate": 0},
        "page_chain": [{"request_cursor_sha256": None, "next_cursor_sha256": None,
                        "http_status": 200, "count": len(articles)}],
    }


def _article():
    return {"id": 123, "created_at": "2024-01-01T12:00:00Z",
            "updated_at": "2024-01-01T13:00:00Z", "headline": "News"}


def test_empty_success_is_not_reported_as_no_global_news():
    result = audit_alpaca_snapshot(_snapshot(), START, END, expected_symbol="BTC/USD")
    assert result["status"] == "query_empty"
    assert result["coverage"] == "pagination_consistent"
    assert result["usable"] == 0


def test_pagination_and_snapshot_digest_with_cutoff():
    snapshot = _snapshot([_article()])
    snapshot["pages"] = 2
    snapshot["page_chain"] = [
        {"request_cursor_sha256": None, "next_cursor_sha256": TOKEN, "http_status": 200, "count": 1},
        {"request_cursor_sha256": TOKEN, "next_cursor_sha256": None, "http_status": 200, "count": 0},
    ]
    result = audit_alpaca_snapshot(snapshot, START, END, expected_symbol="BTC/USD")
    assert result["status"] == "query_observed"
    assert result["errors"] == []
    assert result["snapshot_sha256"] == snapshot_sha256(snapshot)
    snapshot["articles"][0]["headline"] = "Changed"
    assert audit_alpaca_snapshot(snapshot, START, END, expected_symbol="BTC/USD")["snapshot_sha256"] != result["snapshot_sha256"]


def test_broken_pagination_and_counts_are_never_complete():
    snapshot = _snapshot([_article()])
    snapshot["pages"] = 2
    snapshot["page_chain"] = [
        {"request_cursor_sha256": None, "next_cursor_sha256": None, "http_status": 200, "count": 1},
        {"request_cursor_sha256": TOKEN, "next_cursor_sha256": TOKEN, "http_status": 200, "count": 1},
    ]
    result = audit_alpaca_snapshot(snapshot, START, END, expected_symbol="BTC/USD")
    assert result["status"] == "incomplete"
    assert result["coverage"] == "unknown"
    assert {"early_pagination_end", "broken_cursor_chain", "pagination_not_exhausted",
            "article_count_mismatch"} <= set(result["errors"])


def test_edits_after_cut_and_undated_articles_are_rejected():
    article = _article()
    article["updated_at"] = "2024-01-02T00:00:01Z"
    result = audit_alpaca_snapshot(_snapshot([article]), START, END, expected_symbol="BTC/USD")
    assert result["status"] == "incomplete"
    assert "article_outside_usable_window" in result["errors"]
    article["updated_at"] = None
    assert "invalid_article_timestamp" in audit_alpaca_snapshot(_snapshot([article]), START, END, expected_symbol="BTC/USD")["errors"]


def test_discarded_revisions_remain_visible_and_query_is_not_full_content():
    snapshot = _snapshot()
    snapshot["discarded"]["revised_after_cut"] = 1
    snapshot["page_chain"][0]["count"] = 1
    result = audit_alpaca_snapshot(snapshot, START, END, expected_symbol="BTC/USD")
    assert result["status"] == "query_with_exclusions"
    assert result["discarded"]["revised_after_cut"] == 1


def test_unaware_timestamps_wrong_window_and_bad_status_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        audit_alpaca_snapshot(_snapshot(), datetime(2024, 1, 1), END, expected_symbol="BTC/USD")
    snapshot = _snapshot()
    snapshot["end_exclusive"] = "2024-01-03T00:00:00Z"
    snapshot["page_chain"][0]["http_status"] = 429
    result = audit_alpaca_snapshot(snapshot, START, END, expected_symbol="BTC/USD")
    assert result["status"] == "incomplete"
    assert {"query_window_mismatch", "page_request_failed"} <= set(result["errors"])


def test_decision_boundary_earlier_window_and_wrong_symbol_are_rejected():
    article = _article()
    article["updated_at"] = END.isoformat()
    snapshot = _snapshot([article])
    snapshot["start"] = (START - timedelta(days=1)).isoformat()
    result = audit_alpaca_snapshot(snapshot, START, END, expected_symbol="ETH/USD")
    assert result["status"] == "incomplete"
    assert {"symbol_mismatch", "query_window_mismatch", "article_outside_usable_window"} <= set(result["errors"])


def test_missing_discard_category_does_not_prove_pagination_consistency():
    snapshot = _snapshot()
    del snapshot["discarded"]["revised_after_cut"]
    result = audit_alpaca_snapshot(snapshot, START, END, expected_symbol="BTC/USD")
    assert result["status"] == "incomplete"
    assert "invalid_discarded_counts" in result["errors"]
