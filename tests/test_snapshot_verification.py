import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from tradingagents.dataflows.vendors.alpaca_news import _persist_snapshot, snapshot_sha256
from tradingagents.snapshot_verification import (
    audit_stored_alpaca_snapshot,
    inspect_graph_report_snapshots,
    load_alpaca_snapshot,
)

START = datetime(2024, 1, 1, tzinfo=UTC)
END = START + timedelta(days=1)


def _snapshot():
    return {
        "source": "alpaca", "symbol": "BTCUSD", "start": START.isoformat(),
        "end_exclusive": END.isoformat(), "pages": 1, "articles": [],
        "page_chain": [{"request_cursor_sha256": None, "next_cursor_sha256": None,
                        "http_status": 200, "count": 0}],
        "discarded": {"invalid_timestamp": 0, "outside_window": 0,
                      "revised_after_cut": 0, "duplicate": 0},
    }


def _save(root, snapshot):
    digest = snapshot_sha256(snapshot)
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    (root / f"{digest}.json").write_bytes(raw)
    return digest


def _heading(digest):
    return f"## Alpaca/Benzinga news (snapshot SHA256: {digest})"


def test_load_and_audit_snapshot_saved_by_vendor_format(tmp_path):
    snapshot = _snapshot()
    saved = _persist_snapshot(snapshot, tmp_path)
    digest = snapshot_sha256(snapshot)
    assert load_alpaca_snapshot(saved.parent, digest) == snapshot
    audit = audit_stored_alpaca_snapshot(saved.parent, digest, START, END, expected_symbol="BTCUSD")
    assert audit["snapshot_sha256"] == digest
    assert audit["coverage"] == "pagination_consistent"
    assert audit["status"] == "query_empty"


def test_tampering_wrong_name_and_noncanonical_bytes_are_rejected(tmp_path):
    digest = _save(tmp_path, _snapshot())
    (tmp_path / f"{digest}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="bytes do not match"):
        load_alpaca_snapshot(tmp_path, digest)
    with pytest.raises(ValueError, match="lowercase SHA256"):
        load_alpaca_snapshot(tmp_path, "../secrets")

    raw = b'{ "source": "alpaca" }'
    noncanonical = hashlib.sha256(raw).hexdigest()
    (tmp_path / f"{noncanonical}.json").write_bytes(raw)
    with pytest.raises(ValueError, match="not canonical"):
        load_alpaca_snapshot(tmp_path, noncanonical)


def test_graph_report_reports_present_missing_and_tampered_references(tmp_path):
    valid = _save(tmp_path, _snapshot())
    invalid = "a" * 64
    missing = "b" * 64
    (tmp_path / f"{invalid}.json").write_bytes(b"changed")
    state = {"news_report": _heading(valid) + "\r\n" + _heading(missing),
             "sentiment_report": _heading(invalid) + "\n" + _heading(valid)}
    result = inspect_graph_report_snapshots(tmp_path, state)
    assert result["references"]["news_report"] == sorted([valid, missing])
    assert result["verified"] == [valid]
    assert result["missing"] == [missing]
    assert result["invalid"] == [invalid]


def test_unmarked_or_absent_report_never_fabricates_a_reference(tmp_path):
    digest = _save(tmp_path, _snapshot())
    result = inspect_graph_report_snapshots(tmp_path, {"news_report": f"Article mentions {digest}"})
    assert result == {"references": {"news_report": [], "sentiment_report": []},
                      "verified": [], "missing": [], "invalid": []}
    with pytest.raises(ValueError, match="news_report must be text"):
        inspect_graph_report_snapshots(tmp_path, {"news_report": None})
