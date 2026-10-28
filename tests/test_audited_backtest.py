import json

import pytest

from tradingagents import audited_backtest


def _inputs(tmp_path):
    prices = tmp_path / "prices.csv"
    signals = tmp_path / "signals.json"
    audits = tmp_path / "audits.json"
    diagnostic = tmp_path / "diagnostic.json"
    report = tmp_path / "report.html"
    prices.write_text("date,BTC-MXN\n2025-01-01,100\n2025-01-02,110\n", encoding="utf-8")
    signals.write_text(json.dumps([{"date": "2025-01-01", "ticker": "BTC-MXN", "rating": "Buy"}]), encoding="utf-8")
    event = {"published_at": "2024-12-31T12:00:00Z", "available_at": "2024-12-31T12:00:00Z"}
    audits.write_text(json.dumps([{
        "ticker": "BTC-MXN", "date": "2025-01-01",
        "start": "2024-12-31T00:00:00Z", "decision_time": "2025-01-01T00:00:00Z",
        "candle_interval_seconds": 86400,
        "candles": [{"open_time": "2024-12-31T00:00:00Z", "available_at": "2025-01-01T00:00:00Z"}],
        "sources": {name: [event] for name in ("news", "macro", "sentiment")},
    }]), encoding="utf-8")
    return prices, signals, audits, diagnostic, report


def test_observed_events_do_not_pass_gate(tmp_path, monkeypatch):
    paths = _inputs(tmp_path)
    monkeypatch.setattr(audited_backtest, "simulate_portfolio", lambda *args: pytest.fail("must not simulate"))
    assert audited_backtest.run(*paths) is False
    diagnostic = json.loads(paths[3].read_text(encoding="utf-8"))
    assert diagnostic["status"] == "blocked"
    assert diagnostic["signals"][0]["audit"]["status"] == "unknown"
    assert diagnostic["signals"][0]["audit"]["sources"]["news"]["coverage"] == "unknown"
    assert not paths[4].exists()


def test_missing_signal_audit_blocks(tmp_path):
    paths = _inputs(tmp_path)
    paths[2].write_text("[]", encoding="utf-8")
    assert audited_backtest.run(*paths) is False
    assert json.loads(paths[3].read_text(encoding="utf-8"))["signals"][0]["audit"]["status"] == "missing_audit"


def test_complete_label_without_source_evidence_still_blocks(tmp_path, monkeypatch):
    paths = _inputs(tmp_path)
    monkeypatch.setattr(audited_backtest, "_audit", lambda item: {"status": "complete"})
    assert audited_backtest.run(*paths) is False
    assert not paths[4].exists()


def test_future_complete_audit_runs_real_simulation_then_reports(tmp_path, monkeypatch):
    paths = _inputs(tmp_path)
    monkeypatch.setattr(audited_backtest, "_audit", lambda item: {
        "status": "complete", "prices": {"status": "timestamps_complete"},
        "sources": {name: {"coverage": "verified_complete"} for name in ("news", "macro", "sentiment")},
    })
    reports = []
    monkeypatch.setattr(audited_backtest, "quantstats_html", lambda result, path: reports.append((result, path)))
    monkeypatch.setattr(audited_backtest, "TelegramNotifications", lambda: type(
        "Disabled", (), {"enabled": False, "message": lambda self, text: False}
    )())
    assert audited_backtest.run(*paths) is True
    assert reports[0][0].trades.iloc[0]["ticker"] == "BTC-MXN"
    assert reports[0][1] == paths[4]


def test_output_cannot_overwrite_input(tmp_path):
    paths = list(_inputs(tmp_path))
    paths[3] = paths[0]
    with pytest.raises(ValueError, match="output paths"):
        audited_backtest.run(*paths)
    assert paths[0].read_text(encoding="utf-8").startswith("date,")
