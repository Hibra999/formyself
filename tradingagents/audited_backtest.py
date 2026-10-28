"""Audit supplied historical evidence before simulating supplied signals.

See ``docs/audited-backtest.md`` for input formats and current limitations.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from tradingagents.backtest_telegram import TelegramNotifications
from tradingagents.historical_coverage import audit_coverage
from tradingagents.portfolio_backtest import quantstats_html, simulate_portfolio


def _timestamp(value):
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _audit(item):
    candles = [{key: _timestamp(value) for key, value in candle.items()}
               for candle in item["candles"]]
    sources = {name: [{key: _timestamp(value) for key, value in event.items()}
                      for event in records]
               for name, records in item["sources"].items()}
    return audit_coverage(_timestamp(item["start"]), _timestamp(item["decision_time"]),
                          timedelta(seconds=item["candle_interval_seconds"]), candles, sources)


def run(prices_path: Path, signals_path: Path, audits_path: Path,
        diagnostic_path: Path, report_path: Path) -> bool:
    """Write a diagnostic and simulate only with verified complete coverage."""
    inputs = {path.resolve() for path in (prices_path, signals_path, audits_path)}
    outputs = {diagnostic_path.resolve(), report_path.resolve()}
    if inputs & outputs or len(outputs) != 2:
        raise ValueError("output paths must differ from inputs and each other")
    telegram = TelegramNotifications()
    telegram.message("Iniciando auditoría de datos para el backtest.")
    prices = pd.read_csv(prices_path, index_col="date", parse_dates=["date"])
    signals = json.loads(signals_path.read_text(encoding="utf-8"))
    audits = json.loads(audits_path.read_text(encoding="utf-8"))
    if not isinstance(signals, list) or not signals or not isinstance(audits, list):
        raise ValueError("signals must be a nonempty list and audits must be a list")
    indexed = {}
    for item in audits:
        key = (item["ticker"], item["date"])
        if key in indexed:
            raise ValueError(f"duplicate audit for {key}")
        decision = _timestamp(item["decision_time"])
        if decision.utcoffset() is None or decision.date().isoformat() != item["date"]:
            raise ValueError("audit decision_time must be timezone-aware and match its signal date")
        indexed[key] = _audit(item)

    diagnostics = []
    for signal in signals:
        key = (signal["ticker"], signal["date"])
        diagnostics.append({"ticker": key[0], "date": key[1],
                            "audit": indexed.get(key, {"status": "missing_audit"})})
    passed = all(
        item["audit"].get("status") == "complete"
        and item["audit"].get("prices", {}).get("status") == "timestamps_complete"
        and all(item["audit"].get("sources", {}).get(name, {}).get("coverage") == "verified_complete"
                for name in ("news", "macro", "sentiment"))
        for item in diagnostics
    )
    diagnostic_path.write_text(json.dumps({
        "status": "passed" if passed else "blocked",
        "note": "Event observations do not prove complete historical feed coverage.",
        "price_file": {"rows": len(prices), "tickers": list(prices.columns),
                       "note": "Prices are not verified against candle evidence."},
        "signals": diagnostics,
    }, indent=2, default=lambda value: value.isoformat()), encoding="utf-8")
    if not passed:
        telegram.message("Backtest bloqueado: falta verificar cobertura histórica.")
        return False

    result = simulate_portfolio(prices, signals)
    quantstats_html(result, report_path)
    telegram.message("Backtest terminado; enviando reporte QuantStats.")
    if telegram.enabled:
        telegram.document(report_path, caption="Audited portfolio backtest")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--signals", type=Path, required=True)
    parser.add_argument("--audits", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        passed = run(args.prices, args.signals, args.audits, args.diagnostic, args.report)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    if not passed:
        parser.exit(2, f"Blocked: coverage cannot be established; see {args.diagnostic}\n")
    print(f"Report: {args.report}")


if __name__ == "__main__":
    main()
